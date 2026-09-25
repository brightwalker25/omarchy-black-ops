"""The software watch, for bin/black-ops.

docs/contract.md, section 5, fixes what this module provides and what it may
write. bin/black-ops loads it by path and calls only these functions:

    make_row(api)            -> the "watch" Row, optional
    report(ctx, api)         -> the "watch" object of the status JSON
    flagged(ctx, api)        -> the items the watch flags
    cli(ctx, api, argv)      -> exit status of `black-ops watch ...` and
                                `black-ops review ...`; argv[0] is the verb

What it does: it keeps an inventory of the software installed on the machine
(pacman packages, flatpaks, AppImages, pip distributions, global npm packages,
mise installs and loose programs in the user's folders) and reads the files
of whatever is new or has changed, looking for signs of telemetry: telemetry
libraries by name, the byte strings of the signatures file, Sentry keys,
telemetry switches, Electron crash upload settings, and what such programs
leave behind in the home folder. It reads files and nothing else. It never
runs a program it scans, needs no root, and sends nothing anywhere.

A finding with a real telemetry match is flagged for review, in amber. A
weaker sign, such as an update check or a flatpak with broad access, is kept
as a note that `black-ops watch list --notes` shows, and never changes a
colour.
"""
import configparser
import contextlib
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import resource
import shutil
import stat
import struct
import subprocess
import sys
import time
import tomllib
from pathlib import Path

SCHEMA = 1
MAX_FILE = 512 * 1024 * 1024
STALE_AFTER = 8 * 86400
REAL_KINDS = ("telemetry", "analytics", "crash-report")
GREP = "/usr/bin/grep"
# One scan stops starting new work after this long; what is left is picked up
# by the next scan, because it is not in the inventory yet.
SCAN_BUDGET = 3 * 3600
BATCH_FILES = 400
BATCH_BYTES = 1024 * 1024 * 1024
GREP_MEMORY = 2 * 1024 * 1024 * 1024
MAX_EVIDENCE = 8
ARTEFACT_BUDGET = 40000
HOOK_NAME = "90-omarchy-black-ops-watch.hook"
ID_RE = re.compile(r"^[0-9a-f]{16}$")
NAME_RE = re.compile(r"^[A-Za-z0-9@._+-]+$")

# ------------------------------------------------------------------ signals

# Signatures the watch uses on its own, for signals that have no host of
# their own, such as a telemetry switch. They are not in data/signatures.toml
# because listen mode matches hosts and these have none. Each id starts with
# "watch-", so it can never clash with an id from that file.
WATCH_SIGNATURES = {
    "watch-kill-switch": ("", "telemetry", "A setting that turns off the program's own telemetry."),
    "watch-sdk-wandb": ("Weights & Biases", "telemetry", "The wandb library, which reports usage and errors."),
    "watch-sdk-gradio": ("Gradio", "analytics", "Gradio, which sends usage analytics by default."),
    "watch-sdk-streamlit": ("Streamlit", "analytics", "Streamlit, which gathers usage statistics by default."),
    "watch-sdk-langsmith": ("LangChain", "telemetry", "The LangSmith client, which uploads traces when tracing is on."),
    "watch-sdk-opentelemetry": ("OpenTelemetry", "telemetry", "An OpenTelemetry exporter, which sends traces or metrics to a collector."),
    "watch-sdk-scarf": ("Scarf", "analytics", "Scarf, which reports installs and usage."),
    "watch-electron-crash": ("Electron", "crash-report", "An Electron crash reporter set to upload reports."),
    "watch-runtime": ("", "telemetry", "Files a program leaves after collecting or sending telemetry."),
    "watch-own-endpoint": ("", "telemetry", "A telemetry or crash report host of the program's own vendor."),
    # Notes only.
    "watch-update-check": ("", "update-check", "The program checks for updates by itself."),
    "watch-exposure": ("Flatpak", "lookup", "A flatpak with network access and the whole file system."),
    "watch-install-id": ("", "lookup", "A file holding an installation id."),
    "watch-geodb": ("", "lookup", "A downloaded IP location database."),
    "watch-crashpad": ("", "crash-report", "Crash reports a Chromium based program has written."),
    "watch-not-scanned": ("", "lookup", "A compressed file the watch could not read."),
    "watch-block-list": ("", "lookup", "A telemetry host a script lists in order to block it."),
}

# Telemetry libraries by name. (patterns, ecosystem, signature, what it is,
# known opt-out or None). A pattern is matched with fnmatch against the
# name, lower-cased, with "_" and "." made "-" for pip.
SDKS = [
    (("sentry-sdk", "raven"), "pip", "sentry-ingest", "Sentry's crash reporting library", None),
    (("@sentry/*",), "npm", "sentry-ingest", "Sentry's crash reporting library", None),
    (("posthog", "posthog-*"), "any", "posthog", "PostHog's analytics library", None),
    (("wandb",), "pip", "watch-sdk-wandb", "the Weights & Biases client",
     "WANDB_ERROR_REPORTING=false, WANDB_MODE=offline"),
    (("gradio",), "pip", "watch-sdk-gradio", "Gradio", "GRADIO_ANALYTICS_ENABLED=False"),
    (("streamlit",), "pip", "watch-sdk-streamlit", "Streamlit",
     "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false"),
    (("onnxruntime", "onnxruntime-*"), "pip", "microsoft-1ds", "onnxruntime, with Microsoft's 1DS telemetry",
     "onnxruntime.disable_telemetry_events() in code; block the 1DS hosts"),
    (("chromadb",), "pip", "posthog", "Chroma, which reports to PostHog", "ANONYMIZED_TELEMETRY=False"),
    (("langsmith",), "any", "watch-sdk-langsmith", "the LangSmith client", "LANGSMITH_TRACING=false"),
    (("opentelemetry-exporter*",), "pip", "watch-sdk-opentelemetry", "an OpenTelemetry exporter",
     "OTEL_SDK_DISABLED=true"),
    (("@opentelemetry/exporter-*",), "npm", "watch-sdk-opentelemetry", "an OpenTelemetry exporter",
     "OTEL_SDK_DISABLED=true"),
    (("scarf-js", "@scarf/scarf", "scarf-sdk"), "any", "watch-sdk-scarf", "Scarf's install analytics",
     "SCARF_ANALYTICS=false"),
    (("statsig", "statsig-*", "@statsig/*"), "any", "statsig", "Statsig's feature flag and event library",
     None),
    (("mixpanel", "mixpanel-*"), "any", "mixpanel", "Mixpanel's analytics library", None),
    (("@amplitude/*", "amplitude-analytics"), "any", "amplitude", "Amplitude's analytics library", None),
    (("@segment/*", "analytics-node", "segment-analytics-python"), "any", "segment",
     "Segment's analytics library", None),
]

# Browsers carry Google Analytics hosts in their block lists and link tables,
# so for them that signature says nothing.
BROWSERS = {"firefox", "zen", "zen-browser", "zen-browser-bin", "brave", "brave-bin",
            "brave-browser", "chromium", "google-chrome", "vivaldi", "librewolf",
            "mullvad-browser", "mullvad-browser-bin", "tor-browser", "floorp", "waterfox",
            "opera", "microsoft-edge-stable-bin", "thorium-browser-bin"}
BROWSER_ONLY_NOISE = {"google-analytics"}

KILL_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:DISABLE_)?(?:TELEMETRY|ANALYTICS)[A-Z0-9_]*")
UPDATE_RE = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:DISABLE_UPDATE|AUTOUPDATER)[A-Z0-9_]*")
DSN_RE = re.compile(r"o[0-9]+\.ingest(?:\.us|\.de)?\.sentry\.io")
# Names shaped like a switch, as opposed to a constant that happens to hold
# the word, such as a telemetry event's name.
SWITCH_SUFFIX = re.compile(r"(?:DISABLE_TELEMETRY|DISABLE_ANALYTICS|NO_TELEMETRY|TELEMETRY_DISABLED?|"
                           r"TELEMETRY_OPT_?OUT|TELEMETRY_ENABLED?|TELEMETRY_OFF|ANALYTICS_DISABLED?|"
                           r"ANALYTICS_ENABLED?|ANALYTICS_OPT_?OUT)$")
# OpenTelemetry's semantic convention constants, and prefixes that mark a
# constant rather than an environment variable.
NOT_A_SWITCH = ("SEMRESATTRS_TELEMETRY_", "ATTR_TELEMETRY_", "SEMATTRS_TELEMETRY_", "PREF_", "IS_",
                "HAS_", "SHOULD_", "KEY_", "EVENT_", "TYPE_", "CATEGORY_")

# What the grep pass looks for, besides the signature strings. Kept in step
# with classify().
EXTRA_PATTERNS = [
    r"o[0-9]+\.ingest(\.us|\.de)?\.sentry\.io",
    r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*_(DISABLE_)?(TELEMETRY|ANALYTICS)[A-Z0-9_]*",
    r"DO_NOT_TRACK",
    r"[A-Z][A-Z0-9]*(_[A-Z0-9]+)*_(DISABLE_UPDATE|AUTOUPDATER)[A-Z0-9_]*",
    r"uploadToServer: ?(!0|true)",
    r"latest-linux\.yml",
    r"setFeedURL",
    # A host of the program's own, with the character on each side, so that
    # opentelemetry.proto.common is not read as a host.
    r"(^|[^a-z0-9-])(telemetry|sentry|crash-?reports?)\.[a-z0-9-]+(\.[a-z0-9-]+)*"
    r"\.(com|io|net|org|app|dev|ai)([^a-z0-9.-]|$)",
    r"(^|[^a-z0-9-])[a-z0-9]+-(telemetry|sentry)\.[a-z0-9-]+(\.[a-z0-9-]+)*"
    r"\.(com|io|net|org|app|dev|ai)([^a-z0-9.-]|$)",
]
OWN_HOST_RE = re.compile(r"(?:(?:telemetry|sentry|crash-?reports?)|[a-z0-9]+-(?:telemetry|sentry))"
                         r"\.[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|io|net|org|app|dev|ai)")
# Hosts of that shape that are documentation, examples or libraries rather
# than an endpoint the program reports to.
OWN_HOST_IGNORE = re.compile(r"(^|\.)(example|your-company|yourcompany|mycompany|localhost|opentelemetry|"
                             r"google|googleapis|gstatic|github|githubusercontent|readthedocs|docs)\.|"
                             # OpenTelemetry's attribute names, such as telemetry.sdk.version.
                             r"^telemetry\.(sdk|auto|distro)\.")
# A telemetry host in a script that exists to block it, such as a tool that
# writes the host into /etc/hosts. Only a small text file counts, and only
# when every line naming the host maps it to a null address, or the file
# holds a block list, refers to /etc/hosts and has a null address. A file
# that also names the host in a URL is flagged all the same, so a client is
# never let off. What is let off is kept as a note.
BLOCK_TEXT_MAX = 256 * 1024
BLOCK_MARKER_RE = re.compile(r"\b(?:BLOCKED_HOSTS|BLOCKED_DOMAINS|BLOCKLIST|BLOCK_LIST|blocked_hosts|"
                             r"blocked_domains|blockedHosts)\b")
NULL_ADDRESS = r"(?<![\w.:])(?:0\.0\.0\.0|127\.0\.0\.1|::1|::)[ \t]+(?:[A-Za-z0-9.-]+[ \t]+)*[A-Za-z0-9.-]*"
# Code a program brings itself, as opposed to the browser engine it is
# built on. Google Analytics hosts in an engine's binary are block lists and
# link tables, so that signature counts only in code.
APP_CODE = (".asar", ".js", ".mjs", ".cjs", ".html", ".htm", ".py", ".jsc")

# Folders and file types never worth reading: pictures, fonts, translations,
# documentation, compressed archives and object files.
SKIP_DIRS = ("usr/share/doc/", "usr/share/man/", "usr/share/info/", "usr/share/locale/",
             "usr/share/icons/", "usr/share/pixmaps/", "usr/share/fonts/", "usr/share/licenses/",
             "usr/share/zoneinfo/", "usr/share/i18n/", "usr/share/help/", "usr/share/gtk-doc/",
             "usr/share/themes/", "usr/share/backgrounds/", "usr/share/wallpapers/",
             "usr/share/sounds/", "usr/share/X11/", "usr/share/terminfo/", "usr/share/kbd/",
             "usr/share/hwdata/", "usr/share/unicode/", "usr/share/mime/", "usr/share/texmf",
             "usr/share/consolefonts/", "usr/include/", "usr/lib/modules/", "usr/lib/firmware/",
             "usr/src/", "boot/", "etc/", "var/")
SKIP_SUFFIXES = (".png", ".svg", ".svgz", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".ttf",
                 ".otf", ".woff", ".woff2", ".mo", ".po", ".h", ".hpp", ".gz", ".xz", ".zst", ".bz2",
                 ".ko", ".pyc", ".pyi", ".a", ".o", ".md", ".rst", ".txt", ".css", ".wav", ".ogg",
                 ".mp3", ".mp4", ".webm", ".pdf", ".map", ".d.ts", ".qm", ".pak.info", ".lock",
                 ".typed", ".license", ".h5", ".pt", ".bin", ".safetensors", ".onnx", ".gguf")
CODE_SUFFIXES = (".js", ".mjs", ".cjs", ".node", ".asar", ".jsc", ".py", ".json")


# ------------------------------------------------------------------ paths

def paths(ctx):
    """Every path the watch uses, from ctx, so the tests can move them."""
    var = Path(ctx.environ.get("BLACK_OPS_VAR", "/var"))
    root = Path(ctx.environ.get("BLACK_OPS_ROOT", "/"))
    return {
        "var": var,
        "root": root,
        "spool": var / "lib/omarchy-black-ops/pending",
        "flatpak_system": var / "lib/flatpak/app",
        "hook": ctx.etc / "pacman.d/hooks" / HOOK_NAME,
        "spool_prog": Path(ctx.helper_path).parent / "watch-spool",
        "inventory": ctx.watch_dir / "inventory/index.json",
        "seen": ctx.watch_dir / "inventory/spool-seen.txt",
        "store": ctx.watch_dir / "watch.json",
        "reviews": ctx.watch_dir / "reviewed.toml",
        "lock": ctx.watch_dir / "watch.lock",
        "config": ctx.config_home / "omarchy-black-ops/watch.toml",
    }


def home_path(ctx, text):
    text = str(text)
    if text == "~":
        return ctx.home
    if text.startswith("~/"):
        return ctx.home / text[2:]
    return Path(text)


def load_config(ctx):
    """~/.config/omarchy-black-ops/watch.toml, which is optional:

        venvs = ["~/somewhere/.venv"]    # virtual environments to add
        venv_roots = ["~/AI", "~/Work"]  # folders searched for pyvenv.cfg
        venv_depth = 4                   # how deep that search goes
        skip = ["~/Downloads"]           # folders never read
    """
    text = _read(paths(ctx)["config"])
    try:
        data = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        data = {}
    roots = data.get("venv_roots")
    if not isinstance(roots, list):
        roots = ["~/AI", "~/Work", "~/Projects", "~/projects", "~/src", "~/code", "~/.venvs",
                 "~/.virtualenvs", "~/.local/share/virtualenvs", "~/.local/share/pipx/venvs",
                 "~/.local/pipx/venvs", "~/.local/share/uv/tools"]
    venvs = data.get("venvs") if isinstance(data.get("venvs"), list) else []
    skip = data.get("skip") if isinstance(data.get("skip"), list) else []
    depth = data.get("venv_depth")
    if not isinstance(depth, int) or not 1 <= depth <= 8:
        depth = 4
    return {"venv_roots": [home_path(ctx, r) for r in roots if isinstance(r, str)],
            "venvs": [home_path(ctx, v) for v in venvs if isinstance(v, str)],
            "skip": [str(home_path(ctx, s)) for s in skip if isinstance(s, str)],
            "venv_depth": depth}


def _read(path, limit=None):
    try:
        with open(path, "rb") as fh:
            data = fh.read() if limit is None else fh.read(limit)
        return data.decode("utf-8", "replace")
    except OSError:
        return None


def _lstat(path):
    try:
        return os.lstat(path)
    except OSError:
        return None


def _is_reg(info):
    return info is not None and stat.S_ISREG(info.st_mode)


# ------------------------------------------------------------ signatures

def load_signatures(api):
    """{id: signature} from data/signatures.toml, plus the watch's own."""
    sigs = {}
    try:
        data = tomllib.loads((Path(api.LIB_DIR).parent / "data/signatures.toml").read_text())
        for sig in data.get("signature", []):
            if isinstance(sig, dict) and isinstance(sig.get("id"), str):
                sigs[sig["id"]] = {"vendor": sig.get("vendor", ""), "kind": sig.get("kind", ""),
                                   "strings": [s for s in sig.get("strings", [])
                                               if isinstance(s, str) and len(s) >= 8],
                                   "about": sig.get("about", "")}
    except (OSError, tomllib.TOMLDecodeError):
        pass
    for sid, (vendor, kind, about) in WATCH_SIGNATURES.items():
        sigs.setdefault(sid, {"vendor": vendor, "kind": kind, "strings": [], "about": about})
    return sigs


def ere_escape(text):
    return re.sub(r"([.\[\]()*+?{}|^$\\])", r"\\\1", text)


def build_pattern(sigs):
    """One extended regular expression for the whole grep pass, and a map
    from each literal string back to its signature."""
    literals = {}
    for sid, sig in sigs.items():
        for s in sig["strings"]:
            literals.setdefault(s, sid)
    parts = [ere_escape(s) for s in sorted(literals)] + EXTRA_PATTERNS
    return "|".join(parts), literals


# ---------------------------------------------------------- classification

def switch_shaped(name):
    """Whether a name reads as a telemetry switch rather than as a constant
    that happens to hold the word."""
    if len(name) > 48 or name.startswith(NOT_A_SWITCH):
        return False
    if name.count("TELEMETRY") + name.count("ANALYTICS") > 1:
        return False                      # two strings run together
    return bool(SWITCH_SUFFIX.search(name)) or name.endswith(("_TELEMETRY", "_ANALYTICS"))


def is_switch(name, program=""):
    """Whether a switch is the program's own: one with no prefix, such as
    DISABLE_TELEMETRY, or one that starts with the program's name, such as
    GH_TELEMETRY in gh. A switch named for another tool, such as
    DOTNET_CLI_TELEMETRY_OPTOUT in a version manager, is a note."""
    if not switch_shaped(name):
        return False
    if name.startswith(("DISABLE_", "ENABLE_", "NO_TELEMETRY")) or name in ("TELEMETRY_DISABLED",):
        return True
    head = name.split("_", 1)[0].lower()
    stem = re.sub(r"[^a-z0-9]", "", (program or "").lower().split("/")[-1])
    stem = re.sub(r"(bin|git|cli|desktop)$", "", stem) or stem
    return bool(stem) and len(head) >= 2 and (stem.startswith(head) or head.startswith(stem))


def classify(match, literals, sigs, file_path, is_browser):
    """What one string grep found means: (signature id, real, string), or
    None for a match that says nothing."""
    code = file_path.endswith(APP_CODE) or "/app.asar" in file_path
    if match in literals:
        sid = literals[match]
        if sid in BROWSER_ONLY_NOISE and (is_browser or not code):
            return None
        return sid, sigs[sid]["kind"] in REAL_KINDS, match
    if DSN_RE.fullmatch(match):
        return "sentry-ingest", True, match
    host = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", match)
    if host != match and OWN_HOST_RE.fullmatch(host):
        match = host
        if is_browser or OWN_HOST_IGNORE.search(match) or match.endswith((".sentry.io",)):
            return None
        return "watch-own-endpoint", True, match
    if match.startswith("uploadToServer"):
        return ("watch-electron-crash", True, "uploadToServer: true") if code else None
    if match in ("latest-linux.yml", "setFeedURL"):
        return ("watch-update-check", False, match) if code else None
    if match == "DO_NOT_TRACK":
        return "watch-kill-switch", False, match
    if UPDATE_RE.fullmatch(match):
        if len(match) > 48:
            return None
        return "watch-update-check", False, match
    if KILL_RE.fullmatch(match):
        # A browser's telemetry is set through its preferences, and its
        # code is full of constants with the word in them.
        if is_browser:
            return None
        return "watch-kill-switch", None, match      # decided per unit, see findings_of()
    return None


def block_list_text(path):
    """The text of a file that could be a block list, or None: a small
    regular file that is plain UTF-8, never a binary or a compressed file."""
    if path.endswith((".br", ".asar")) or "/app.asar" in path:
        return None
    info = _lstat(path)
    if not _is_reg(info) or info.st_size > BLOCK_TEXT_MAX:
        return None
    try:
        with open(path, "rb") as fh:
            data = fh.read(BLOCK_TEXT_MAX + 1)
        if b"\0" in data or len(data) > BLOCK_TEXT_MAX:
            return None
        return data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def blocks_host(text, host):
    """Whether a text file names a host only in order to block it."""
    if not text or host not in text:
        return False
    esc = re.escape(host)
    if re.search(r"(?://|@)[A-Za-z0-9.-]*" + esc, text):
        return False                      # used in a URL, so it is contacted
    lines = [line for line in text.splitlines() if host in line]
    if all(re.search(NULL_ADDRESS + esc, line) for line in lines):
        return True
    return (bool(BLOCK_MARKER_RE.search(text)) and "/etc/hosts" in text
            and bool(re.search(r"0\.0\.0\.0|127\.0\.0\.1", text)))


def sdk_rule(name, eco):
    """The SDKS entry a package name matches, or None."""
    low = name.lower()
    norm = re.sub(r"[-_.]+", "-", low) if eco == "pip" else low
    for patterns, rule_eco, sid, what, opt in SDKS:
        if rule_eco not in ("any", eco):
            continue
        if any(fnmatch.fnmatchcase(norm, p) for p in patterns):
            return sid, what, opt
    return None


def node_module_names(path):
    """Package names in a path, from each node_modules segment in it."""
    parts = Path(path).parts
    out = []
    for i, p in enumerate(parts[:-1]):
        if p == "node_modules":
            nxt = parts[i + 1]
            if nxt.startswith("@") and i + 2 < len(parts):
                out.append(f"{nxt}/{parts[i + 2]}")
            elif not nxt.startswith("."):
                out.append(nxt)
    return out


def asar_modules(path):
    """Package names under node_modules inside an Electron app.asar, read
    from the archive's JSON header without unpacking anything."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
            if len(head) < 16:
                return set()
            _, _, _, size = struct.unpack("<4I", head)
            if size <= 0 or size > 64 * 1024 * 1024:
                return set()
            header = json.loads(fh.read(size).decode("utf-8", "replace"))
    except (OSError, ValueError, struct.error):
        return set()
    names = set()

    def walk(node, depth):
        files = node.get("files") if isinstance(node, dict) else None
        if not isinstance(files, dict) or depth > 40:
            return
        for name, child in files.items():
            if name == "node_modules" and isinstance(child, dict):
                for mod, sub in (child.get("files") or {}).items():
                    if mod.startswith("@") and isinstance(sub, dict):
                        for inner in (sub.get("files") or {}):
                            names.add(f"{mod}/{inner}")
                    elif not mod.startswith("."):
                        names.add(mod)
                    walk(sub, depth + 1)
                    if mod.startswith("@") and isinstance(sub, dict):
                        for inner in (sub.get("files") or {}).values():
                            walk(inner, depth + 2)
            else:
                walk(child, depth + 1)

    walk(header, 0)
    return names


# ---------------------------------------------------------------- grep pass

def _limit_child():
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (GREP_MEMORY, GREP_MEMORY))
    with contextlib.suppress(OSError):
        os.nice(10)


def grep_available():
    return os.access(GREP, os.X_OK)


def grep_files(files, pattern, deadline, source=None, label=None):
    """{path: set of matched strings} for these files, read by GNU grep in
    one pass. With `source`, grep reads the standard output of that command
    instead, under the name `label`. Returns (matches, error or "")."""
    out = {}
    env = {"LC_ALL": "C", "PATH": "/usr/bin:/bin"}
    cmd = [GREP, "-a", "-o", "-H", "-Z", "-E", "-s", "-e", pattern]
    feeder = None
    if source is not None:
        cmd += ["--label=" + label, "-"]
        try:
            feeder = subprocess.Popen(source, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, env=env, preexec_fn=_limit_child)
        except OSError as exc:
            return out, f"{source[0]}: {exc.strerror}"
        stdin = feeder.stdout
    else:
        cmd += ["--"] + list(files)
        stdin = subprocess.DEVNULL
    try:
        proc = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                env=env, preexec_fn=_limit_child)
    except OSError as exc:
        if feeder:
            feeder.kill()
        return out, f"grep: {exc.strerror}"
    if feeder:
        feeder.stdout.close()
    error = ""
    try:
        for line in proc.stdout:
            if time.monotonic() > deadline:
                error = "time limit"
                break
            name, sep, match = line.rstrip(b"\n").partition(b"\0")
            if not sep or not match:
                continue
            found = out.setdefault(name.decode("utf-8", "surrogateescape"), set())
            if len(found) < 200:
                found.add(match[:200].decode("ascii", "replace"))
    finally:
        if error:
            proc.kill()
            if feeder:
                feeder.kill()
        proc.stdout.close()
        proc.wait()
        if feeder:
            feeder.wait()
    return out, error


# ------------------------------------------------------------- the inventory

class Unit:
    """One thing installed: a package, an app, a tool, a virtual
    environment. Its files are what the grep pass reads; its names are the
    package names found inside it, for the library signals."""

    def __init__(self, key, source, program, version=None, package=None, exe=None):
        self.key = key
        self.source = source
        self.program = program
        self.version = version
        self.package = package
        self.exe = exe
        self.files = {}         # path -> (size, mtime) of files to read
        self.streams = []       # (label, command) for compressed files
        self.names = {}         # package name -> (ecosystem, path it was found at)
        self.notes = []         # (signature, path, string)
        self.browser = False
        self.foreign = False

    def fingerprint(self):
        return {"version": self.version, "files": len(self.files), "names": len(self.names)}


def wanted_file(rel):
    """Whether a file, by its path, can hold code worth reading."""
    rel = rel.lstrip("/")
    if rel.startswith(SKIP_DIRS) or "/__pycache__/" in rel:
        return False
    low = rel.lower()
    if low.endswith(SKIP_SUFFIXES):
        return False
    if "/share/" in rel and not low.endswith(CODE_SUFFIXES + (".pak",)) and "/bin/" not in rel:
        return False
    return True


def add_file(unit, path, skip=()):
    info = _lstat(path)
    if not _is_reg(info) or info.st_size == 0:
        return False
    sp = str(path)
    if any(sp == s or sp.startswith(s + "/") for s in skip):
        return False
    if info.st_size > MAX_FILE:
        unit.notes.append(("watch-not-scanned", sp, "larger than 512 MiB"))
        return False
    if "\n" in sp:
        return False
    if sp.endswith(".br"):
        unit.streams.append((sp, "brotli", info.st_size, int(info.st_mtime)))
        return True
    unit.files[sp] = (info.st_size, int(info.st_mtime))
    return True


def walk_files(top, skip=(), max_files=200000):
    """Regular files under a folder, never following a link."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        if any(dirpath == s or dirpath.startswith(s + "/") for s in skip):
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
        for f in filenames:
            count += 1
            if count > max_files:
                return
            yield os.path.join(dirpath, f)


def parse_pacman_desc(text):
    fields, key = {}, None
    for line in (text or "").split("\n"):
        if line.startswith("%") and line.endswith("%"):
            key = line.strip("%")
            fields[key] = []
        elif key and line:
            fields[key].append(line)
    return fields


def sync_names(ctx):
    """Names of the packages the sync databases carry, so that the rest can
    be marked as foreign (built from the AUR or by hand)."""
    import tarfile
    names = set()
    sync = Path(ctx.pacman_db).parent / "sync"
    try:
        dbs = sorted(sync.glob("*.db"))
    except OSError:
        return None
    if not dbs:
        return None
    for db in dbs:
        try:
            with tarfile.open(db, "r:*") as tar:
                for m in tar:
                    if m.isdir():
                        name = m.name.rstrip("/")
                        parts = name.rsplit("-", 2)
                        if len(parts) == 3:
                            names.add(parts[0])
        except (OSError, tarfile.TarError, EOFError):
            continue
    return names


def desktop_is_browser(path):
    text = _read(path, 65536) or ""
    return bool(re.search(r"^Categories=.*\bWebBrowser\b", text, re.M))


def pacman_units(ctx, only=None):
    root = paths(ctx)["root"]
    units = []
    try:
        entries = sorted(os.listdir(ctx.pacman_db))
    except OSError:
        return units
    repo = sync_names(ctx)
    for entry in entries:
        d = Path(ctx.pacman_db) / entry
        desc = parse_pacman_desc(_read(d / "desc"))
        name = (desc.get("NAME") or [""])[0]
        if not name or (only is not None and name not in only):
            continue
        version = (desc.get("VERSION") or [""])[0]
        unit = Unit(f"pacman:{name}", "pacman", name, version, package=name)
        unit.foreign = repo is not None and name not in repo
        unit.browser = name in BROWSERS
        files = parse_pacman_desc(_read(d / "files")).get("FILES", [])
        for rel in files:
            if rel.endswith("/"):
                m = re.search(r"(?:^|/)site-packages/([^/]+)\.(?:dist|egg)-info/$", rel)
                if m:
                    dist = m.group(1).rsplit("-", 1)[0]
                    site = root / rel.rstrip("/").rsplit("/", 1)[0]
                    pkg_dir = site / re.sub(r"[-.]", "_", dist)
                    where = pkg_dir if pkg_dir.is_dir() else root / rel.rstrip("/")
                    unit.names.setdefault(dist, ("pip", str(where)))
                for nm in node_module_names(rel.rstrip("/") + "/x"):
                    unit.names.setdefault(nm, ("npm", str(root / rel.rstrip("/"))))
                continue
            if rel.startswith("usr/share/applications/") and rel.endswith(".desktop"):
                if desktop_is_browser(root / rel):
                    unit.browser = True
            if rel.startswith("usr/bin/") and unit.exe is None:
                unit.exe = "/" + rel
            if wanted_file(rel):
                add_file(unit, root / rel)
        units.append(unit)
    return units


def pacman_owned_opt(ctx):
    """Top-level folders under /opt that some package owns."""
    owned = set()
    try:
        entries = os.listdir(ctx.pacman_db)
    except OSError:
        return owned
    for entry in entries:
        text = _read(Path(ctx.pacman_db) / entry / "files") or ""
        for m in re.finditer(r"^opt/([^/\n]+)/", text, re.M):
            owned.add(m.group(1))
    return owned


def flatpak_units(ctx, cfg):
    units = []
    p = paths(ctx)
    for scope, base in (("system", p["flatpak_system"]), ("user", ctx.data_home / "flatpak/app")):
        try:
            apps = sorted(os.listdir(base))
        except OSError:
            continue
        for app in apps:
            active = base / app / "current/active"
            try:
                commit = os.path.basename(os.path.realpath(active))
            except OSError:
                continue
            meta_path = active / "metadata"
            meta = configparser.ConfigParser(strict=False, interpolation=None)
            with contextlib.suppress(configparser.Error):
                meta.read_string(_read(meta_path) or "")
            unit = Unit(f"flatpak:{scope}:{app}", "flatpak", app, commit[:12], package=app)
            ctxs = meta["Context"] if meta.has_section("Context") else {}
            shared = set(filter(None, (ctxs.get("shared", "") or "").split(";")))
            fs = set(filter(None, (ctxs.get("filesystems", "") or "").split(";")))
            unit.permissions = {"shared": sorted(shared), "filesystems": sorted(fs)}
            if "network" in shared and fs & {"host", "host:rw", "home", "home:rw", "host-os", "host-etc"}:
                broad = sorted(fs & {"host", "host:rw", "home", "home:rw", "host-os", "host-etc"})
                unit.notes.append(("watch-exposure", str(meta_path),
                                   "shared=network with filesystems=" + ",".join(broad)))
            unit.browser = app.lower().split(".")[-1] in {b.split("-")[0] for b in BROWSERS}
            files = active / "files"
            for f in walk_files(files, cfg["skip"]):
                rel = os.path.relpath(f, files)
                if wanted_file("usr/" + rel) or rel.startswith(("bin/", "extra/")):
                    for nm in node_module_names(rel):
                        unit.names.setdefault(nm, ("npm", f))
                    m = re.search(r"site-packages/([^/]+)\.dist-info/METADATA$", rel)
                    if m:
                        unit.names.setdefault(m.group(1).rsplit("-", 1)[0], ("pip", os.path.dirname(f)))
                    add_file(unit, f)
            units.append(unit)
    return units


def elf_end(path):
    """Where the ELF part of an AppImage ends, which is where its squashfs
    starts, or None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(64)
    except OSError:
        return None
    if len(head) < 64 or head[:4] != b"\x7fELF" or head[4] != 2:
        return None
    shoff, = struct.unpack_from("<Q", head, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", head, 0x3A)
    return shoff + shentsize * shnum


def is_appimage(path, info):
    if not _is_reg(info):
        return False
    if path.lower().endswith(".appimage"):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(11)
    except OSError:
        return False
    return head[:4] == b"\x7fELF" and head[8:11] == b"AI\x02"


def appimage_program(path):
    stem = os.path.basename(path)
    stem = re.sub(r"\.appimage$", "", stem, flags=re.I)
    stem = re.split(r"[-_ ](?:v?\d)", stem)[0]
    stem = re.sub(r"[-_.](x86_64|amd64|linux|aarch64)$", "", stem, flags=re.I)
    return stem or os.path.basename(path)


def appimage_unit(ctx, path, info):
    program = appimage_program(path)
    unit = Unit(f"appimage:{program.lower()}", "appimage", program,
                f"{info.st_size}-{int(info.st_mtime)}")
    unit.appimage = path
    unit.appimage_stat = (info.st_size, int(info.st_mtime))
    return unit


def appimage_payload(ctx, unit, deadline, pattern):
    """Read an AppImage's payload through unsquashfs, when it is installed,
    one file at a time, without running the AppImage or unpacking it to
    disk. Returns {label: matches} and notes."""
    tool = shutil.which("unsquashfs", path=ctx.environ.get("PATH", ""))
    path = unit.appimage
    if not tool:
        unit.notes.append(("watch-not-scanned", path,
                           "AppImage payload not read: unsquashfs is not installed"))
        return {}
    off = elf_end(path)
    if not off:
        unit.notes.append(("watch-not-scanned", path, "AppImage payload not found"))
        return {}
    rc, out, _ = ctx.run([tool, "-o", str(off), "-lls", "-d", "", path], timeout=60)
    if rc != 0:
        unit.notes.append(("watch-not-scanned", path, "unsquashfs could not list the payload"))
        return {}
    found = {}
    for line in out.splitlines():
        m = re.match(r"^-\S+\s+\S+\s+(\d+)\s+\S+\s+\S+\s+(?:squashfs-root)?/?(.*)$", line)
        if not m:
            continue
        size, inner = int(m.group(1)), m.group(2)
        if size == 0 or size > MAX_FILE or not wanted_file("usr/" + inner) or "\n" in inner:
            continue
        for nm in node_module_names(inner):
            unit.names.setdefault(nm, ("npm", f"{path}!/{inner}"))
        if not (inner.endswith((".asar", ".js", ".node", ".so")) or "/" not in inner
                or inner.startswith(("usr/bin/", "bin/")) or ".so." in inner):
            continue
        label = f"{path}!/{inner}"
        got, err = grep_files([], pattern, deadline, source=[tool, "-o", str(off), "-cat", path, inner],
                              label=label)
        for k, v in got.items():
            found.setdefault(k, set()).update(v)
        if err:
            break
    return found


def local_units(ctx, cfg, owned_opt):
    """Programs in the user's own folders, loose AppImages anywhere they
    usually go, and folders under /opt no package owns."""
    units = {}
    h = ctx.home
    folders = [(h / ".local/bin", "local"), (h / ".cargo/bin", "cargo"), (h / "bin", "local")]
    for top, source in folders:
        try:
            names = sorted(os.listdir(top))
        except OSError:
            continue
        for name in names:
            path = str(top / name)
            info = _lstat(path)
            if not _is_reg(info) or any(path.startswith(s + "/") for s in cfg["skip"]):
                continue
            if is_appimage(path, info):
                u = appimage_unit(ctx, path, info)
                units[u.key] = u
                continue
            key = f"{source}:{path}"
            u = Unit(key, source, name, f"{info.st_size}-{int(info.st_mtime)}", exe=path)
            if add_file(u, path, cfg["skip"]):
                units[key] = u
    # AppImages in the usual places; ~/Downloads is read for AppImages only.
    for top in (h / "Applications", h / "Downloads", h / "AppImages", h / ".local/share/applications",
                h, paths(ctx)["root"] / "opt"):
        try:
            names = sorted(os.listdir(top))
        except OSError:
            continue
        for name in names:
            path = str(top / name)
            if any(path == s or path.startswith(s + "/") for s in cfg["skip"]):
                continue
            info = _lstat(path)
            if is_appimage(path, info):
                u = appimage_unit(ctx, path, info)
                units.setdefault(u.key, u)
    opt = paths(ctx)["root"] / "opt"
    try:
        names = sorted(os.listdir(opt))
    except OSError:
        names = []
    for name in names:
        top = opt / name
        info = _lstat(top)
        if name in owned_opt or info is None or not stat.S_ISDIR(info.st_mode):
            continue
        u = Unit(f"local:{top}", "local", name, None)
        newest = 0
        for f in walk_files(top, cfg["skip"]):
            rel = os.path.relpath(f, opt)
            for nm in node_module_names(rel):
                u.names.setdefault(nm, ("npm", f))
            if wanted_file("opt/" + rel):
                if add_file(u, f):
                    newest = max(newest, u.files.get(f, (0, 0))[1])
        u.version = str(newest)
        units[u.key] = u
    return list(units.values())


def npm_roots(ctx):
    """Folders holding globally installed npm packages."""
    h = ctx.home
    roots = []
    prefix = ctx.environ.get("NPM_CONFIG_PREFIX") or ctx.environ.get("npm_config_prefix")
    npmrc = _read(h / ".npmrc") or ""
    m = re.search(r"^\s*prefix\s*=\s*(.+?)\s*$", npmrc, re.M)
    for p in (prefix, m.group(1) if m else None, str(h / ".npm-global"), str(h / ".local")):
        if p:
            roots.append(home_path(ctx, p) / "lib/node_modules")
    roots.append(ctx.data_home / "mise/installs/node")      # versions, handled below
    return roots


def npm_package_units(ctx, cfg, node_modules, source="npm", tag=""):
    units = []
    try:
        names = sorted(os.listdir(node_modules))
    except OSError:
        return units
    tops = []
    for n in names:
        if n.startswith("."):
            continue
        if n.startswith("@"):
            try:
                tops += [f"{n}/{m}" for m in sorted(os.listdir(Path(node_modules) / n))]
            except OSError:
                pass
        else:
            tops.append(n)
    for name in tops:
        if name in ("npm", "corepack"):
            continue
        top = Path(node_modules) / name
        info = _lstat(top)
        if info is None or not stat.S_ISDIR(info.st_mode):
            continue
        pkg = {}
        with contextlib.suppress(ValueError, TypeError):
            pkg = json.loads(_read(top / "package.json") or "{}")
        version = pkg.get("version") if isinstance(pkg, dict) else None
        u = Unit(f"{source}:{top}", source, name.split("/")[-1] if not tag else f"{tag}", version,
                 package=name)
        units.append(scan_tree(u, top, cfg))
    return units


def scan_tree(unit, top, cfg):
    """Fill a unit from a folder: package names from node_modules and
    dist-info folders, and the files worth reading."""
    for f in walk_files(top, cfg["skip"]):
        rel = os.path.relpath(f, top)
        for nm in node_module_names(rel):
            unit.names.setdefault(nm, ("npm", str(Path(f).parent)))
        m = re.search(r"(?:^|/)site-packages/([^/]+)\.dist-info/METADATA$", rel)
        if m:
            unit.names.setdefault(m.group(1).rsplit("-", 1)[0], ("pip", os.path.dirname(f)))
        if wanted_file("usr/lib/" + rel):
            add_file(unit, f, cfg["skip"])
    return unit


def mise_units(ctx, cfg):
    units = []
    base = ctx.data_home / "mise/installs"
    try:
        tools = sorted(os.listdir(base))
    except OSError:
        return units
    for tool in tools:
        try:
            versions = sorted(os.listdir(base / tool))
        except OSError:
            continue
        # Only the version in use: the one "latest" points at, or else the
        # newest. Older versions kept on disk are not what runs.
        real = [v for v in versions if (lambda i: i is not None and stat.S_ISDIR(i.st_mode))(_lstat(base / tool / v))]
        latest = base / tool / "latest"
        active = None
        if os.path.islink(latest):
            target = os.path.basename(os.path.realpath(latest))
            active = target if target in real else None
        if active is None and real:
            active = max(real, key=lambda v: (_lstat(base / tool / v).st_mtime, v))
        for ver in ([active] if active else []):
            top = base / tool / ver
            if tool == "node":
                for u in npm_package_units(ctx, cfg, top / "lib/node_modules"):
                    units.append(u)
                continue
            if tool == "python":
                for sp in sorted(top.glob("lib/python3*/site-packages")):
                    units.append(pip_unit(ctx, sp, f"mise python {ver}"))
                continue
            u = Unit(f"mise:{tool}", "mise", re.sub(r"^(npm|pipx|cargo|ubi|aqua|github)[-:]", "", tool),
                     ver, package=tool)
            units.append(scan_tree(u, top, cfg))
    return units


def find_venvs(ctx, cfg):
    found = []
    seen = set()
    for v in cfg["venvs"]:
        if (v / "pyvenv.cfg").is_file():
            found.append(v)
    for root in cfg["venv_roots"]:
        base_depth = len(Path(root).parts)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if any(dirpath == s or dirpath.startswith(s + "/") for s in cfg["skip"]):
                dirnames[:] = []
                continue
            if "pyvenv.cfg" in filenames:
                found.append(Path(dirpath))
                dirnames[:] = []
                continue
            if len(Path(dirpath).parts) - base_depth >= cfg["venv_depth"]:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "site-packages",
                                                            "__pycache__")]
    out = []
    for v in found:
        real = os.path.realpath(v)
        if real not in seen:
            seen.add(real)
            out.append(v)
    return out


def venv_label(venv):
    name = venv.name
    if name.lower() in (".venv", "venv", "env", ".env", "virtualenv"):
        return venv.parent.name
    return name


def pip_unit(ctx, site, label):
    """A site-packages folder, as one unit whose names are its
    distributions. pip packages are recognised by name only; their files are
    not read."""
    u = Unit(f"pip:{site}", "pip", label, None)
    u.dists = {}
    try:
        entries = sorted(os.listdir(site))
    except OSError:
        return u
    for e in entries:
        m = re.match(r"^(.+?)-([^-]+)\.(dist|egg)-info$", e)
        if not m:
            continue
        name, version = m.group(1), m.group(2)
        info = _lstat(Path(site) / e)
        u.dists[str(Path(site) / e)] = (name, version, int(info.st_mtime) if info else 0)
        # The package's own folder does not change name between versions,
        # so an item found there keeps its id through upgrades.
        pkg_dir = Path(site) / re.sub(r"[-.]", "_", name)
        where = pkg_dir if pkg_dir.is_dir() else Path(site) / e
        u.names.setdefault(name, ("pip", str(where)))
    u.version = str(len(u.dists))
    return u


def pip_units(ctx, cfg):
    units = []
    for sp in sorted((ctx.home / ".local/lib").glob("python3*/site-packages")):
        units.append(pip_unit(ctx, sp, "user site-packages"))
    for venv in find_venvs(ctx, cfg):
        for sp in sorted(venv.glob("lib/python3*/site-packages")):
            units.append(pip_unit(ctx, sp, f"{venv_label(venv)} venv"))
    return units


def all_units(ctx, cfg, only_pacman=None):
    if only_pacman is not None:
        return pacman_units(ctx, only_pacman)
    units = pacman_units(ctx)
    units += flatpak_units(ctx, cfg)
    owned = pacman_owned_opt(ctx)
    units += local_units(ctx, cfg, owned)
    for root in npm_roots(ctx):
        if root.name == "node" and root.parent.name == "installs":
            continue
        units += npm_package_units(ctx, cfg, root)
    units += mise_units(ctx, cfg)
    units += pip_units(ctx, cfg)
    by_key = {}
    for u in units:
        by_key.setdefault(u.key, u)
    return list(by_key.values())


def inventory_items(unit, now, scanned_at, found_sigs):
    """The unit's entries in inventory/index.json."""
    items = []
    base = {"source": unit.source if unit.source != "cargo" else "cargo",
            "package": unit.package, "version": unit.version, "unit": unit.key,
            "scannedAt": scanned_at}
    for path, (size, mtime) in sorted(unit.files.items()):
        items.append(dict(base, path=path, sha256=None, size=size, mtime=mtime,
                          signatures=sorted(found_sigs.get(path, ()))))
    for label, _, size, mtime in unit.streams:
        items.append(dict(base, path=label, sha256=None, size=size, mtime=mtime,
                          signatures=sorted(found_sigs.get(label, ()))))
    if getattr(unit, "appimage", None):
        size, mtime = unit.appimage_stat
        items.append(dict(base, path=unit.appimage, sha256=None, size=size, mtime=mtime,
                          signatures=sorted(found_sigs.get(unit.appimage, ()))))
    for path, (name, version, mtime) in sorted(getattr(unit, "dists", {}).items()):
        items.append(dict(base, path=path, package=name, version=version, sha256=None, size=None,
                          mtime=mtime, signatures=sorted(found_sigs.get(path, ()))))
    if not items:
        items.append(dict(base, path=unit.key, sha256=None, size=None, mtime=None, signatures=[]))
    return items


def unit_changed(unit, previous):
    """Whether a unit differs from its entries in the last inventory."""
    if not previous:
        return True
    now = inventory_items(unit, 0, 0, {})
    key = lambda i: (i["path"], i.get("size"), i.get("mtime"), i.get("version"))
    return sorted(map(key, now)) != sorted(map(key, previous))


# ------------------------------------------------------------ runtime traces

def artefact_program(ctx, path):
    """The program a trace in the home folder belongs to, from the folder
    it sits in."""
    rel = Path(path).relative_to(ctx.home).parts
    if len(rel) >= 3 and rel[0] in (".config", ".cache") or len(rel) >= 4 and rel[:2] == (".local", "share"):
        name = rel[1] if rel[0] != ".local" else rel[2]
    elif len(rel) >= 3 and rel[:2] == (".var", "app"):
        name = rel[2]
    else:
        name = rel[0]
    return name.lstrip(".") or name


def artefact_scan(ctx, cfg):
    """Traces programs leave after collecting or sending telemetry: Glean's
    queued pings, submitted crash reports, a consent file holding a client
    id, installation ids and downloaded location databases. Returns units,
    one per program."""
    units = {}
    h = ctx.home
    tops = [h / ".config", h / ".local/share", h / ".var/app"]
    try:
        tops += [h / n for n in sorted(os.listdir(h)) if n.startswith(".")
                 and n not in (".config", ".local", ".cache", ".var", ".npm", ".cargo", ".rustup",
                               ".git", ".ssh", ".gnupg")]
    except OSError:
        pass
    budget = [ARTEFACT_BUDGET]

    def add(path, sid, real, what):
        program = artefact_program(ctx, path)
        key = f"artefact:{program}"
        u = units.get(key)
        if u is None:
            u = units[key] = Unit(key, "local", program, None)
            u.artefacts = []
        u.artefacts.append((sid, real, str(path), what))

    for top in tops:
        info = _lstat(top)
        if info is None or not stat.S_ISDIR(info.st_mode):
            continue
        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            budget[0] -= len(dirnames) + len(filenames)
            if budget[0] <= 0:
                return list(units.values())
            if any(dirpath == s or dirpath.startswith(s + "/") for s in cfg["skip"]):
                dirnames[:] = []
                continue
            depth = len(Path(dirpath).relative_to(top).parts)
            if depth >= 6:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in ("node_modules", ".git", "site-packages",
                                                            "Cache", "Code Cache", "GPUCache",
                                                            "cache2", "IndexedDB", "Service Worker")]
            base = os.path.basename(dirpath)
            parent = os.path.basename(os.path.dirname(dirpath))
            if base == "pending_pings" and parent == "glean" and filenames:
                add(dirpath, "watch-runtime", True, f"{len(filenames)} Glean pings waiting to be sent")
            if base == "submitted" and parent == "Crash Reports" and filenames:
                add(dirpath, "watch-runtime", True, f"{len(filenames)} crash reports submitted")
            if base == "completed" and parent == "Crash Reports" and filenames:
                add(dirpath, "watch-crashpad", False, f"{len(filenames)} crash reports written")
            for f in filenames:
                full = os.path.join(dirpath, f)
                if f == "Consent To Send Stats":
                    info = _lstat(full)
                    if _is_reg(info) and info.st_size > 0:
                        add(full, "watch-runtime", True, "usage statistics consent with a client id")
                elif f in ("installation_id", "Installation ID", "installation-id", "machine-id.txt"):
                    add(full, "watch-install-id", False, f)
                elif re.fullmatch(r"\.?telemetry[-_.]?(id|stamp|state|json)?(\.json)?", f, re.I) \
                        or f in ("TelemetryID", "telemetry-id", "telemetry.sqlite"):
                    add(full, "watch-runtime", True, f"telemetry file {f}")
                elif re.fullmatch(r"(GeoLite2|GeoIP|dbip)[-\w]*\.(mmdb|dat)", f, re.I):
                    add(full, "watch-geodb", False, f)
    return list(units.values())


# ------------------------------------------------------------------ findings

def item_id(path, signature):
    parts = ["watch", "static", path, signature]
    return hashlib.sha256("\0".join(parts).encode("utf-8", "surrogateescape")).hexdigest()[:16]


def summary_for(sid, sig, strings, what=None):
    vendor = sig.get("vendor") or ""
    kind = sig.get("kind")
    if sid == "watch-kill-switch":
        name = sorted(strings, key=len)[0] if strings else "a switch"
        return f"Reads {name[:60]}, a switch for its own telemetry."
    if sid == "watch-electron-crash":
        return "Its Electron crash reporter is set to upload reports."
    if sid == "watch-runtime":
        return f"Has left telemetry traces: {what}."[:119] if what else "Has left telemetry traces."
    if what:
        return f"Bundles {what}."[:119]
    if sid == "sentry-ingest" and any(DSN_RE.fullmatch(s) for s in strings):
        return "Has a Sentry crash report key built in."
    word = {"telemetry": "telemetry", "analytics": "analytics", "crash-report": "crash report"}.get(kind, kind)
    return f"Has {vendor}'s {word} endpoint built in."[:119]


def best_match(sid, strings):
    """The one string that best shows why an item was flagged."""
    if not strings:
        return None
    if sid == "sentry-ingest":
        dsn = [s for s in strings if DSN_RE.fullmatch(s)]
        if dsn:
            return dsn[0]
    if sid == "watch-kill-switch":
        return sorted(strings, key=lambda n: (not re.search("DISABLE|OPT_?OUT|NO_", n), len(n), n))[0]
    return sorted(strings, key=lambda x: (-len(x), x))[0]


def findings_of(unit, matches, sigs):
    """Findings for a unit from its grep matches, its package names and its
    traces. Returns (items, notes): items are flagged, notes are not."""
    by_sig = {}           # sid -> {"files": {path: set}, "what": str, "opt": str}
    notes = []
    switches = {}         # name -> set of files
    texts = {}            # path -> its text, for the block list check
    for path, found in matches.items():
        for m in found:
            c = classify(m, unit.literals, sigs, path, unit.browser)
            if c is None:
                continue
            sid, real, s = c
            if real and (sid == "watch-own-endpoint" or not sid.startswith("watch-")):
                if path not in texts:
                    texts[path] = block_list_text(path)
                if blocks_host(texts[path], s):
                    notes.append(("watch-block-list", path, s))
                    continue
            if sid == "watch-kill-switch":
                if s != "DO_NOT_TRACK":
                    switches.setdefault(s, set()).add(path)
                else:
                    switches.setdefault(s, set()).add(path)
                continue
            if real:
                by_sig.setdefault(sid, {"files": {}, "what": None, "opt": None})["files"] \
                    .setdefault(path, set()).add(s)
            else:
                notes.append((sid, path, s))
    real_switches = {n: fs for n, fs in switches.items()
                     if n != "DO_NOT_TRACK" and is_switch(n, unit.program)}
    for n, fs in real_switches.items():
        for f in fs:
            by_sig.setdefault("watch-kill-switch", {"files": {}, "what": None, "opt": None})["files"] \
                .setdefault(f, set()).add(n)
    for n, fs in switches.items():
        if n not in real_switches:
            notes.append(("watch-kill-switch", sorted(fs)[0], n))
    for name, (eco, where) in sorted(unit.names.items()):
        rule = sdk_rule(name, eco)
        if rule is None:
            continue
        sid, what, opt = rule
        e = by_sig.setdefault(sid, {"files": {}, "what": None, "opt": None})
        e["files"].setdefault(where, set()).add(name)
        e["what"] = e["what"] or what
        e["opt"] = e["opt"] or opt
    for sid, real, path, what in getattr(unit, "artefacts", []):
        if real:
            e = by_sig.setdefault(sid, {"files": {}, "what": None, "opt": None, "trace": what})
            e["files"].setdefault(path, set()).add(what)
            e["trace"] = e.get("trace") or what
        else:
            notes.append((sid, path, what))
    notes += unit.notes
    notes = notes[:40]
    candidates = [n for n in switches if n != "DO_NOT_TRACK" and switch_shaped(n)
                  and (n in real_switches or SWITCH_SUFFIX.search(n))]
    opt_names = sorted(candidates, key=lambda n: (n not in real_switches,
                                                  not re.search("DISABLE|OPT_?OUT|NO_", n), len(n), n))
    if "DO_NOT_TRACK" in switches:
        opt_names.append("DO_NOT_TRACK=1")
    items = []
    for sid, e in sorted(by_sig.items()):
        sig = sigs.get(sid, {"vendor": "", "kind": "telemetry"})
        files = e["files"]
        strings = sorted({s for v in files.values() for s in v})
        path = sorted(files)[0]
        evidence = [{"file": f, "match": s} for f in sorted(files) for s in sorted(files[f])]
        if sid == "watch-kill-switch":
            opt = opt_names[0] if opt_names else None
        else:
            opt = e["opt"] or (opt_names[0] if opt_names else None)
        items.append({
            "id": item_id(path, sid),
            "kind": "static",
            "severity": "warn",
            "program": unit.program,
            "exe": unit.exe,
            "package": unit.package if unit.source == "pacman" else None,
            "path": path,
            "host": None,
            "signature": sid,
            "vendor": sig.get("vendor") or unit.program,
            "summary": summary_for(sid, sig, strings, e.get("trace") if sid == "watch-runtime" else e["what"]),
            "count": len(evidence),
            "match": best_match(sid, strings),
            "evidence": evidence[:MAX_EVIDENCE],
            "optOut": opt,
            "strings": strings[:50],
            "unit": unit.key,
            "source": unit.source,
            "ecosystem": unit.source,
            "version": unit.version,
        })
    note_items = []
    seen = set()
    for sid, path, s in notes:
        if (sid, path, s) in seen:
            continue
        seen.add((sid, path, s))
        note_items.append({"program": unit.program, "unit": unit.key, "signature": sid,
                           "path": path, "match": s,
                           "about": WATCH_SIGNATURES.get(sid, ("", "", sigs.get(sid, {}).get("about", "")))[2]})
    return items, note_items


# ---------------------------------------------------------------- the store

def empty_store():
    return {"schema": SCHEMA, "lastScan": None, "lastScanKind": None, "lastScanError": "",
            "lastScanStarted": None, "incomplete": False, "inventoryCount": 0, "baselineAt": None,
            "firstScanDone": False, "units": {}, "snapshots": {}}


def load_store(ctx):
    text = _read(paths(ctx)["store"])
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    st = empty_store()
    if isinstance(data, dict) and data.get("schema") == SCHEMA:
        for k in st:
            if k in data and (st[k] is None or isinstance(data[k], type(st[k]))):
                st[k] = data[k]
    return st


def ensure_dir(ctx):
    d = ctx.watch_dir
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    (d / "inventory").mkdir(exist_ok=True, mode=0o700)


def save_store(ctx, api, st):
    ensure_dir(ctx)
    api.atomic_write(paths(ctx)["store"], json.dumps(st, indent=1, sort_keys=True) + "\n", mode=0o600)


def load_index(ctx):
    text = _read(paths(ctx)["inventory"])
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return {"schema": SCHEMA, "generatedAt": None, "items": []}
    return data


def all_items(st):
    for u in st["units"].values():
        for it in u.get("items", []):
            yield it


def all_notes(st):
    for u in st["units"].values():
        for n in u.get("notes", []):
            yield n


# ------------------------------------------------------------- the reviews

def toml_str(text):
    out = ['"']
    for ch in str(text):
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def render_reviews(reviews):
    lines = ["schema = 1", ""]
    for rid in sorted(reviews):
        r = reviews[rid]
        if not ID_RE.match(rid) or r.get("verdict") not in ("allowed", "false-positive"):
            continue
        lines.append(f"[items.{toml_str(rid)}]")
        lines.append(f"verdict = {toml_str(r['verdict'])}")
        lines.append(f"at = {int(r.get('at') or 0)}")
        for k in ("program", "signature", "note"):
            if isinstance(r.get(k), str) and r[k]:
                lines.append(f"{k} = {toml_str(r[k][:200])}")
        lines.append("")
    return "\n".join(lines)


def write_reviews(ctx, api, reviews):
    ensure_dir(ctx)
    api.atomic_write(paths(ctx)["reviews"], render_reviews(reviews), mode=0o600)


def snapshot_of(item):
    return {"unit": item.get("unit"), "signature": item["signature"], "program": item["program"],
            "strings": sorted(item.get("strings") or []), "version": item.get("version")}


def settle_reviews(ctx, api, st, now):
    """Keep reviews in step with a new scan. An item reviewed before keeps
    its review unless a later version of the program adds a finding the
    review did not see, and then it is flagged again. An item that is new
    only because the program's file moved, such as an AppImage renamed for
    a new version, takes over the review of the item it replaces, as long as
    it found nothing the review did not see."""
    reviews = api.load_reviews(ctx)
    snaps = st.setdefault("snapshots", {})
    changed = False
    reflagged = []
    current = list(all_items(st))
    for item in current:
        rid = item["id"]
        strings = set(item.get("strings") or [])
        if rid in reviews:
            snap = snaps.get(rid)
            if snap is None:
                snaps[rid] = snapshot_of(item)
            elif not strings <= set(snap.get("strings") or []):
                if item.get("version") != snap.get("version"):
                    del reviews[rid]
                    del snaps[rid]
                    reflagged.append(rid)
                    changed = True
                else:
                    snaps[rid] = snapshot_of(item)
            continue
        for oid, snap in list(snaps.items()):
            if oid in reviews and snap.get("unit") == item.get("unit") \
                    and snap.get("signature") == item["signature"] \
                    and strings <= set(snap.get("strings") or []):
                reviews[rid] = dict(reviews[oid], at=now,
                                    note=("Carried over from an earlier version. "
                                          + str(reviews[oid].get("note") or ""))[:200].strip())
                snaps[rid] = snapshot_of(item)
                changed = True
                break
    # Snapshots for items that have gone are kept only while their review
    # is, so that a program reinstalled later is recognised.
    for oid in list(snaps):
        if oid not in reviews:
            del snaps[oid]
    if changed:
        write_reviews(ctx, api, reviews)
    return reflagged


# ------------------------------------------------------------------ scanning

def read_spool(ctx):
    """({spool file name: [package names]}) for spool files not seen yet."""
    p = paths(ctx)
    seen = set((_read(p["seen"]) or "").split())
    out = {}
    try:
        names = sorted(os.listdir(p["spool"]))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".list") or n in seen:
            continue
        text = _read(p["spool"] / n, 1024 * 1024) or ""
        out[n] = [l.strip() for l in text.splitlines() if NAME_RE.match(l.strip())]
    return out


def mark_spool_seen(ctx, api, names):
    p = paths(ctx)
    try:
        present = set(os.listdir(p["spool"]))
    except OSError:
        present = set()
    seen = [n for n in (_read(p["seen"]) or "").split() if n in present]
    seen += [n for n in names if n not in seen]
    ensure_dir(ctx)
    api.atomic_write(p["seen"], "".join(n + "\n" for n in seen), mode=0o600)


def scan_units(ctx, units, sigs, deadline):
    """Read each unit's files. Returns ({unit key: matches}, notes on what
    could not be read, whether the time ran out)."""
    pattern, literals = build_pattern(sigs)
    results = {u.key: {} for u in units}
    timed_out = False
    if not grep_available():
        for u in units:
            if u.files or u.streams:
                u.notes.append(("watch-not-scanned", u.key, "GNU grep is not installed"))
        return results, True
    brotli = shutil.which("brotli", path=ctx.environ.get("PATH", "")) or \
        (shutil.which("brotli", path="/usr/bin:/bin"))
    owner = {}
    batch, size = [], 0

    def flush():
        nonlocal batch, size, timed_out
        if not batch:
            return
        got, err = grep_files(batch, pattern, deadline)
        if err:
            timed_out = True
        for path, found in got.items():
            key = owner.get(path)
            if key is not None:
                results[key].setdefault(path, set()).update(found)
        batch, size = [], 0

    for u in units:
        u.literals = literals
        for path, (fsize, _) in u.files.items():
            if time.monotonic() > deadline:
                timed_out = True
                break
            owner[path] = u.key
            batch.append(path)
            size += fsize
            if len(batch) >= BATCH_FILES or size >= BATCH_BYTES:
                flush()
        if timed_out:
            break
    flush()
    for u in units:
        if timed_out:
            break
        u.literals = literals
        for label, how, _, _ in u.streams:
            if time.monotonic() > deadline:
                timed_out = True
                break
            if how == "brotli" and brotli:
                got, err = grep_files([], pattern, deadline, source=[brotli, "-dc", "--", label], label=label)
                for path, found in got.items():
                    results[u.key].setdefault(path, set()).update(found)
                timed_out = timed_out or bool(err)
            else:
                u.notes.append(("watch-not-scanned", label, "brotli is not installed"))
        if getattr(u, "appimage", None) and not timed_out:
            for path, found in appimage_payload(ctx, u, deadline, pattern).items():
                results[u.key].setdefault(path, set()).update(found)
        for path in list(u.files):
            if path.endswith(".asar"):
                for nm in asar_modules(path):
                    u.names.setdefault(nm, ("npm", path))
    return results, timed_out


@contextlib.contextmanager
def scan_lock(ctx):
    ensure_dir(ctx)
    fd = os.open(paths(ctx)["lock"], os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def is_scanning(ctx):
    try:
        fd = os.open(paths(ctx)["lock"], os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def flagged_file_hashes(items):
    """SHA-256 of the files flagged items point at, read in chunks."""
    cache = {}
    for it in items:
        p = it.get("path")
        if not p or p in cache or not os.path.isfile(p) or os.path.islink(p):
            continue
        h = hashlib.sha256()
        try:
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            cache[p] = h.hexdigest()
        except OSError:
            continue
    return cache


def run_scan(ctx, api, kind, budget=SCAN_BUDGET):
    """Scan by kind: "pending", "changed" or "full". Returns a line of text
    saying what happened."""
    now = int(time.time())
    deadline = time.monotonic() + budget
    st = load_store(ctx)
    cfg = load_config(ctx)
    sigs = load_signatures(api)
    index = load_index(ctx)
    prev = {}
    for it in index["items"]:
        if isinstance(it, dict) and isinstance(it.get("unit"), str):
            prev.setdefault(it["unit"], []).append(it)
    st["lastScanStarted"] = now
    spool = {}
    if kind == "pending":
        spool = read_spool(ctx)
        wanted = {n for names in spool.values() for n in names}
        units = all_units(ctx, cfg, only_pacman=wanted) if wanted else []
        todo = units
    else:
        units = all_units(ctx, cfg)
        todo = units if kind == "full" else [u for u in units if unit_changed(u, prev.get(u.key))]
    results, timed_out = scan_units(ctx, todo, sigs, deadline)
    # What is found before the first whole scan has finished is the machine
    # as it already was. It is flagged and listed, and marked firstScan so
    # the status can say so rather than read as a fault.
    baseline = not st.get("firstScanDone")
    scanned_keys = set()
    for u in todo:
        if timed_out and not results.get(u.key) and (u.files or u.streams):
            continue            # left for the next scan
        items, notes = findings_of(u, results.get(u.key, {}), sigs)
        old = st["units"].get(u.key, {})
        first = {i["id"]: i.get("firstSeen") for i in old.get("items", [])}
        was_first = {i["id"] for i in old.get("items", []) if i.get("firstScan")}
        for i in items:
            i["firstSeen"] = first.get(i["id"]) or now
            i["lastSeen"] = now
            i["firstScan"] = baseline or i["id"] in was_first
        scanned_keys.add(u.key)
        if not items and not notes:
            st["units"].pop(u.key, None)
            continue
        st["units"][u.key] = {"program": u.program, "source": u.source, "version": u.version,
                              "package": u.package, "foreign": u.foreign, "items": items,
                              "notes": notes, "scannedAt": now,
                              "permissions": getattr(u, "permissions", None)}
    # Traces in the home folder are cheap to look for, so every scan but a
    # pending one looks again.
    if kind != "pending":
        art_keys = set()
        for u in artefact_scan(ctx, cfg):
            items, notes = findings_of(u, {}, sigs)
            old = st["units"].get(u.key, {})
            first = {i["id"]: i.get("firstSeen") for i in old.get("items", [])}
            was_first = {i["id"] for i in old.get("items", []) if i.get("firstScan")}
            for i in items:
                i["firstSeen"] = first.get(i["id"]) or now
                i["lastSeen"] = now
                i["firstScan"] = baseline or i["id"] in was_first
            st["units"][u.key] = {"program": u.program, "source": "local", "version": None,
                                  "package": None, "items": items, "notes": notes, "scannedAt": now}
            art_keys.add(u.key)
        for key in [k for k in st["units"] if k.startswith("artefact:") and k not in art_keys]:
            del st["units"][key]
        present = {u.key for u in units} | art_keys
        for key in list(st["units"]):
            if key not in present:
                del st["units"][key]
    present_units = {u.key for u in units}
    # The inventory: what was scanned now, and what was scanned before and
    # has not changed.
    found_sigs = {}
    for u in st["units"].values():
        for it in u.get("items", []):
            for ev in it.get("evidence", []):
                found_sigs.setdefault(ev["file"], set()).add(it["signature"])
    hashes = flagged_file_hashes(all_items(st))
    new_items = []
    kept = set()
    for u in todo:
        if u.key in scanned_keys:
            new_items += inventory_items(u, now, now, found_sigs)
            kept.add(u.key)
    for key, items in prev.items():
        if key in kept:
            continue
        if kind == "pending" or key in present_units:
            new_items += items
    for it in new_items:
        it["sha256"] = hashes.get(it["path"])
    ensure_dir(ctx)
    api.atomic_write(paths(ctx)["inventory"],
                     json.dumps({"schema": SCHEMA, "generatedAt": now, "items": new_items}) + "\n",
                     mode=0o600)
    st["inventoryCount"] = len(new_items)
    st["lastScan"] = int(time.time())
    st["lastScanKind"] = kind
    st["lastScanError"] = ""
    st["incomplete"] = bool(timed_out)
    # The first scan is done once one has read everything: a pending scan
    # reads only a few packages, and a scan cut short leaves the rest.
    first_run = baseline and kind != "pending" and not timed_out
    if first_run:
        st["firstScanDone"] = True
    reflagged = settle_reviews(ctx, api, st, now)
    save_store(ctx, api, st)
    if spool:
        mark_spool_seen(ctx, api, list(spool))
    reviews = api.load_reviews(ctx)
    flagged_now = [i for i in all_items(st)]
    unreviewed = [i for i in flagged_now if i["id"] not in reviews]
    line = (f"Scanned {len(scanned_keys)} of {len(units)} items ({kind}): "
            f"{len(flagged_now)} flagged, {len(unreviewed)} not reviewed")
    if reflagged:
        line += f", {len(reflagged)} flagged again after an update"
    if timed_out:
        line += ". The time limit was reached; the next scan carries on"
    line += "."
    if first_run and unreviewed and st.get("baselineAt") is None:
        line += ("\nThis was the first scan. To accept everything it found as it is, run:"
                 "\n  black-ops watch baseline --yes")
    return line


# ------------------------------------------------------------------ the row

UNIT_NAMES = ("black-ops-watch.path", "black-ops-watch.service",
              "black-ops-watch-user.path", "black-ops-watch-user.service",
              "black-ops-watch-daily.timer", "black-ops-watch-daily.service",
              "black-ops-watch-weekly.timer", "black-ops-watch-weekly.service")
TRIGGERS = {"black-ops-watch.path": "paths.target", "black-ops-watch-user.path": "paths.target",
            "black-ops-watch-daily.timer": "timers.target",
            "black-ops-watch-weekly.timer": "timers.target"}


def unit_quote(path):
    s = str(path).replace("%", "%%")
    if re.search(r"[\s\"'\\]", s):
        s = '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def user_watch_paths(ctx, cfg):
    """The user folders the user .path unit watches. PathChanged= is not
    recursive, so these are the folders where an install adds an entry."""
    h = ctx.home
    out = [ctx.data_home / "flatpak/app", h / "Applications", h / ".local/bin",
           ctx.data_home / "mise/installs", h / ".cargo/bin"]
    out += [r for r in npm_roots(ctx) if not (r.name == "node" and r.parent.name == "installs")]
    out += sorted((h / ".local/lib").glob("python3*/site-packages"))
    for venv in find_venvs(ctx, cfg):
        out += sorted(venv.glob("lib/python3*/site-packages"))
    seen, clean = set(), []
    for p in out:
        s = str(p)
        if s in seen or "\n" in s or re.search(r"\s", s):
            continue
        seen.add(s)
        clean.append(s)
    return clean


def render_units(ctx, api, cfg=None, user_paths=None):
    """{unit file name: contents}. ExecStart names this plugin's
    bin/black-ops, resolved when the row is switched on."""
    exe = unit_quote(Path(api.LIB_DIR).parent / "bin" / "black-ops")
    spool = paths(ctx)["spool"]
    limits = "Nice=19\nIOSchedulingClass=idle\n"

    def service(desc, flag):
        return (f"[Unit]\nDescription=Black Ops software watch: {desc}\n\n"
                f"[Service]\nType=oneshot\nExecStart={exe} watch scan --{flag} --quiet\n{limits}")

    def timer(desc, cal, delay, svc):
        return (f"[Unit]\nDescription=Black Ops software watch: {desc}\n\n"
                f"[Timer]\nOnCalendar={cal}\nPersistent=true\nRandomizedDelaySec={delay}\nUnit={svc}\n\n"
                f"[Install]\nWantedBy=timers.target\n")

    if user_paths is None:
        user_paths = user_watch_paths(ctx, cfg or load_config(ctx))
    return {
        "black-ops-watch.path": (
            "[Unit]\nDescription=Black Ops software watch: packages pacman has just installed or upgraded\n\n"
            f"[Path]\nPathChanged={unit_quote(spool)}\nUnit=black-ops-watch.service\n\n"
            "[Install]\nWantedBy=paths.target\n"),
        "black-ops-watch.service": service("scan the packages pacman has just changed", "pending"),
        "black-ops-watch-user.path": (
            "[Unit]\nDescription=Black Ops software watch: software installed in your own folders\n\n"
            "[Path]\n" + "".join(f"PathChanged={unit_quote(p)}\n" for p in user_paths)
            + "Unit=black-ops-watch-user.service\n\n[Install]\nWantedBy=paths.target\n"),
        "black-ops-watch-user.service": service("scan what has changed in your own folders", "changed"),
        "black-ops-watch-daily.timer": timer("daily scan of what has changed", "daily", "1h",
                                             "black-ops-watch-daily.service"),
        "black-ops-watch-daily.service": service("scan what has changed", "changed"),
        "black-ops-watch-weekly.timer": timer("weekly scan of everything", "weekly", "2h",
                                              "black-ops-watch-weekly.service"),
        "black-ops-watch-weekly.service": service("scan everything", "full"),
    }


def units_state(ctx, api):
    """("in" | "partial" | "out", what differs)."""
    # The user .path unit is not compared, so the folders it lists need not
    # be searched for on every status.
    want = render_units(ctx, api, user_paths=[])
    present = differ = 0
    for name, text in want.items():
        path = ctx.user_units / name
        cur = _read(path)
        if cur is None:
            continue
        present += 1
        # The user .path unit lists the folders found when it was written;
        # a new virtual environment later does not make it wrong.
        if name != "black-ops-watch-user.path" and cur != text:
            differ += 1
    links = sum(1 for n, target in TRIGGERS.items()
                if os.path.islink(ctx.user_units / f"{target}.wants" / n))
    if present == 0 and links == 0:
        return "out", ""
    if present == len(want) and links == len(TRIGGERS) and differ == 0:
        return "in", ""
    if differ:
        return "partial", "Its units differ from what this version writes."
    return "partial", "Some of its units are missing or not enabled."


def hook_installed(ctx):
    p = paths(ctx)
    return p["hook"].is_file() and os.access(p["spool_prog"], os.X_OK)


def ago(ts, now=None):
    if not ts:
        return "never"
    d = max(0, int((now or time.time()) - ts))
    if d < 3600:
        return f"{d // 60} minutes ago" if d >= 120 else "just now"
    if d < 172800:
        return f"{d // 3600} hours ago"
    return f"{d // 86400} days ago"


def make_row(api):
    class WatchRow(api.Row):
        id = "watch"
        label = "Software watch"
        optional = True
        privileged = False
        about = ("Looks through installed software for telemetry, crash reporting and analytics "
                 "after each install or update, and once a day. It reads files and sends nothing.")

        def check(self, ctx, rec=None):
            state, why = units_state(ctx, api)
            if state == "out":
                return api.result("out", "not watching", "")
            if state == "partial":
                return api.result("partial", "not fully set up", "", work=True, why=why)
            st = load_store(ctx)
            n = sum(1 for _ in all_items(st))
            detail = f"Last scan {ago(st['lastScan'])}. {n} flagged."
            attention = ""
            since = st.get("lastScan") or (rec or {}).get("at")
            if st.get("lastScanError"):
                attention = f"The last scan failed: {st['lastScanError'][:120]}"
            elif since and time.time() - since > STALE_AFTER:
                attention = "No scan has finished for eight days."
            elif not hook_installed(ctx):
                attention = ("The pacman hook is not installed, so packages are scanned by the daily "
                             "timer only. Run the installer to add it.")
            else:
                reviews = api.load_reviews(ctx)
                open_items = [i for i in all_items(st) if i["id"] not in reviews]
                if open_items and all(i.get("firstScan") for i in open_items):
                    # The first scan's findings are expected, not a fault;
                    # the headline says so and the row does not ask for more.
                    detail += (f" The first scan found {len(open_items)} to review, or to accept "
                               "with black-ops watch baseline --yes.")
                elif open_items:
                    attention = (f"{len(open_items)} flagged item"
                                 + (" is" if len(open_items) == 1 else "s are") + " not reviewed yet.")
            return api.result("in", "watching", detail, attention=attention)

        def apply(self, ctx, chk, rec):
            ctx.user_units.mkdir(parents=True, exist_ok=True)
            for name, text in render_units(ctx, api).items():
                api.atomic_write(ctx.user_units / name, text, mode=0o644)
            for name, target in TRIGGERS.items():
                d = ctx.user_units / f"{target}.wants"
                d.mkdir(parents=True, exist_ok=True)
                link = d / name
                if os.path.islink(link) or link.exists():
                    link.unlink()
                os.symlink(ctx.user_units / name, link)
            systemctl(ctx, api, "daemon-reload")
            systemctl(ctx, api, "start", *TRIGGERS)
            # The first scan runs in the background; it builds the baseline.
            systemctl(ctx, api, "start", "--no-block", "black-ops-watch-daily.service")

        def revert(self, ctx, rec):
            systemctl(ctx, api, "stop", *TRIGGERS, *[n for n in UNIT_NAMES if n.endswith(".service")],
                      check=False)
            for name, target in TRIGGERS.items():
                link = ctx.user_units / f"{target}.wants" / name
                if os.path.islink(link):
                    link.unlink()
            for name in UNIT_NAMES:
                with contextlib.suppress(FileNotFoundError):
                    (ctx.user_units / name).unlink()
            for target in set(TRIGGERS.values()):
                with contextlib.suppress(OSError):
                    (ctx.user_units / f"{target}.wants").rmdir()     # only when empty
            systemctl(ctx, api, "daemon-reload", check=False)

    return WatchRow()


def systemctl(ctx, api, *args, check=True):
    rc, _, err = ctx.run(["systemctl", "--user", *args], timeout=30)
    if rc != 0 and check:
        raise api.ActionError(f"systemctl could not {args[0]} the watch: {(err or '').strip()[:120]}")


# ------------------------------------------------------------- the reports

def row_on(ctx, api):
    try:
        st, _ = api.load_state(ctx)
        return bool(api.intended(st, api.BY_ID["watch"]))
    except (KeyError, AttributeError):
        return False


def pending_count(ctx):
    return len({n for names in read_spool(ctx).values() for n in names})


def report(ctx, api):
    st = load_store(ctx)
    reviews = api.load_reviews(ctx)
    items = list(all_items(st))
    return {
        "enabled": row_on(ctx, api),
        "hookInstalled": hook_installed(ctx),
        "lastScan": st.get("lastScan"),
        "lastScanKind": st.get("lastScanKind"),
        "lastScanError": st.get("lastScanError") or "",
        "scanning": is_scanning(ctx),
        "inventoryCount": int(st.get("inventoryCount") or 0),
        "pendingCount": pending_count(ctx),
        "flaggedCount": len(items),
        "unreviewedCount": sum(1 for i in items if i["id"] not in reviews),
        # Beyond the contract's fields: when everything was accepted as it
        # stood, and how many notes there are.
        "baselineAt": st.get("baselineAt"),
        "noteCount": sum(1 for _ in all_notes(st)),
    }


# The contract's fields for a flagged item, and the watch's own: version,
# ecosystem, match, optOut, evidence and firstScan.
PUBLIC = ("id", "kind", "severity", "program", "exe", "package", "path", "host", "signature",
          "vendor", "summary", "firstSeen", "lastSeen", "count", "version", "ecosystem", "match",
          "optOut", "evidence", "firstScan")


def flagged(ctx, api):
    st = load_store(ctx)
    return [dict({k: i.get(k) for k in PUBLIC}, firstScan=bool(i.get("firstScan"))) for i in all_items(st)]


# ------------------------------------------------------------------ the CLI

USAGE = """\
usage: black-ops watch status [--json]
       black-ops watch scan [--pending | --changed | --full] [--quiet]
       black-ops watch list [--all] [--notes] [--json]
       black-ops watch baseline [--yes]
       black-ops review ID allow|false-positive|clear [--note TEXT] [--status]
       black-ops review --all allow|false-positive [--source watch|listen|any] [--note TEXT] [--status]"""


def usage():
    print(USAGE, file=sys.stderr)
    return 2


def cli(ctx, api, argv):
    if not argv:
        return usage()
    if argv[0] == "review":
        return cli_review(ctx, api, argv[1:])
    if argv[0] != "watch" or len(argv) < 2:
        return usage()
    verb, rest = argv[1], argv[2:]
    if verb == "status":
        return cli_status(ctx, api, rest)
    if verb == "scan":
        return cli_scan(ctx, api, rest)
    if verb == "list":
        return cli_list(ctx, api, rest)
    if verb == "baseline":
        return cli_baseline(ctx, api, rest)
    return usage()


def cli_status(ctx, api, rest):
    if any(a != "--json" for a in rest):
        return usage()
    rep = report(ctx, api)
    if "--json" in rest:
        print(json.dumps(rep))
        return 0
    print(f"Software watch: {'on' if rep['enabled'] else 'off'}"
          f"{', scanning now' if rep['scanning'] else ''}")
    print(f"  last scan: {ago(rep['lastScan'])}" + (f" ({rep['lastScanKind']})" if rep["lastScanKind"] else ""))
    if rep["lastScanError"]:
        print(f"  last scan failed: {rep['lastScanError']}")
    print(f"  pacman hook: {'installed' if rep['hookInstalled'] else 'not installed'}")
    print(f"  inventory: {rep['inventoryCount']} items, {rep['pendingCount']} packages waiting")
    print(f"  flagged: {rep['flaggedCount']}, not reviewed: {rep['unreviewedCount']}, "
          f"notes: {rep['noteCount']}")
    return 0


def cli_scan(ctx, api, rest):
    kinds = [a for a in rest if a in ("--pending", "--changed", "--full")]
    other = [a for a in rest if a not in ("--pending", "--changed", "--full", "--quiet")]
    if len(kinds) > 1 or other:
        return usage()
    kind = (kinds[0] if kinds else "--changed")[2:]
    quiet = "--quiet" in rest
    with scan_lock(ctx) as got:
        if not got:
            if not quiet:
                print("A scan is already running.")
            return 0
        try:
            line = run_scan(ctx, api, kind)
        except Exception as exc:        # recorded, so the row can say so
            st = load_store(ctx)
            st["lastScanError"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            st["lastScanKind"] = kind
            with contextlib.suppress(Exception):
                save_store(ctx, api, st)
            print(f"black-ops watch: the scan failed: {st['lastScanError']}", file=sys.stderr)
            return 1
    # Bring the status and summary.json up to date for the bar and for
    # Security Scan.
    with contextlib.suppress(Exception):
        api.current_report(ctx)
    if not quiet:
        print(line)
    return 0


def cli_list(ctx, api, rest):
    if any(a not in ("--all", "--json", "--notes") for a in rest):
        return usage()
    st = load_store(ctx)
    reviews = api.load_reviews(ctx)
    items = []
    for i in all_items(st):
        r = reviews.get(i["id"])
        if r and "--all" not in rest:
            continue
        items.append(dict({k: i.get(k) for k in PUBLIC}, reviewed=r is not None,
                          verdict=r.get("verdict") if r else None))
    items.sort(key=lambda i: (i["reviewed"], i["program"].lower(), i["signature"]))
    notes = list(all_notes(st)) if "--notes" in rest else []
    if "--json" in rest:
        print(json.dumps({"items": items, "notes": notes} if "--notes" in rest else items))
        return 0
    if not items and not notes:
        print("Nothing flagged." if "--all" in rest else "Nothing flagged that is not reviewed.")
    for i in items:
        mark = f"[{i['verdict']}] " if i["reviewed"] else ""
        print(f"{i['id']}  {mark}{i['program']}: {i['summary']}")
        for ev in i["evidence"][:3]:
            print(f"    {ev['file']}: {ev['match']}")
        if i["optOut"]:
            print(f"    opt-out: {i['optOut']}")
    if notes:
        print("Notes, which change no colour:")
        for n in notes:
            print(f"  {n['program']}: {n['match']}  ({n['path']})")
    return 0


def cli_baseline(ctx, api, rest):
    if any(a != "--yes" for a in rest):
        return usage()
    st = load_store(ctx)
    if not st.get("lastScan"):
        print("No scan has finished yet, so there is nothing to accept.", file=sys.stderr)
        return 1
    reviews = api.load_reviews(ctx)
    todo = [i for i in all_items(st) if i["id"] not in reviews]
    if "--yes" not in rest:
        print(f"{len(todo)} flagged items are not reviewed. Run again with --yes to mark them all "
              "as allowed, as a baseline. Each is flagged again if a later version adds anything.")
        return 0
    now = int(time.time())
    for i in todo:
        reviews[i["id"]] = {"verdict": "allowed", "at": now, "program": i["program"],
                            "signature": i["signature"], "note": "Accepted with the baseline."}
        st["snapshots"][i["id"]] = snapshot_of(i)
    st["baselineAt"] = now
    write_reviews(ctx, api, reviews)
    save_store(ctx, api, st)
    with contextlib.suppress(Exception):
        api.current_report(ctx)
    print(f"Marked {len(todo)} items as allowed.")
    return 0


def cli_review(ctx, api, rest):
    status_out = "--status" in rest
    args = [a for a in rest if a != "--status"]
    if "--all" in args:
        return cli_review_all(ctx, api, [a for a in args if a != "--all"], status_out)
    note = ""
    if "--note" in args:
        i = args.index("--note")
        if i + 1 >= len(args):
            return usage()
        note = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2 or not ID_RE.match(args[0]) or args[1] not in ("allow", "false-positive", "clear"):
        return usage()
    rid, action = args
    if len(note) > 200 or any(ord(c) < 0x20 for c in note):
        print("black-ops review: a note is one line of up to 200 characters.", file=sys.stderr)
        return 2
    reviews = api.load_reviews(ctx)
    st = load_store(ctx)
    item = next((i for i in all_items(st) if i["id"] == rid), None)
    if item is None and action != "clear":
        # Listen mode's items are reviewed through this command as well.
        with contextlib.suppress(Exception):
            item = next((i for i in api.current_report(ctx)["flagged"] if i["id"] == rid), None)
    if action == "clear":
        if rid not in reviews:
            print(f"black-ops review: {rid} has no review.", file=sys.stderr)
            return 1
        del reviews[rid]
        st["snapshots"].pop(rid, None)
        text = "Review cleared."
    else:
        if item is None:
            print(f"black-ops review: no flagged item has the id {rid}.", file=sys.stderr)
            return 1
        verdict = "allowed" if action == "allow" else "false-positive"
        reviews[rid] = {"verdict": verdict, "at": int(time.time()), "program": item["program"],
                        "signature": item["signature"], "note": note}
        if item.get("kind") == "static" and "strings" in item:
            st["snapshots"][rid] = snapshot_of(item)
        text = f"Marked {item['program']} as {verdict.replace('-', ' ')}."
    write_reviews(ctx, api, reviews)
    save_store(ctx, api, st)
    # The report is always brought up to date, so summary.json, which
    # Security Scan reads, follows the review at once.
    rep = api.current_report(ctx)
    if status_out:
        print(json.dumps(rep))
    else:
        print(text)
    return 0


def cli_review_all(ctx, api, args, status_out):
    """Review every flagged item that is not reviewed yet, from the watch by
    default. Listen mode's items are included only when asked for, since a
    confirmed contact deserves a look of its own."""
    note, source = "", "watch"
    for flag in ("--note", "--source"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                return usage()
            if flag == "--note":
                note = args[i + 1]
            else:
                source = args[i + 1]
            del args[i:i + 2]
    if len(args) != 1 or args[0] not in ("allow", "false-positive") \
            or source not in ("watch", "listen", "any"):
        return usage()
    if len(note) > 200 or any(ord(c) < 0x20 for c in note):
        print("black-ops review: a note is one line of up to 200 characters.", file=sys.stderr)
        return 2
    verdict = "allowed" if args[0] == "allow" else "false-positive"
    reviews = api.load_reviews(ctx)
    st = load_store(ctx)
    todo = []
    if source in ("watch", "any"):
        todo += [i for i in all_items(st) if i["id"] not in reviews]
    if source in ("listen", "any"):
        with contextlib.suppress(Exception):
            todo += [i for i in api.current_report(ctx)["flagged"]
                     if i.get("source") == "listen" and i["id"] not in reviews]
    now = int(time.time())
    for i in todo:
        reviews[i["id"]] = {"verdict": verdict, "at": now, "program": i["program"],
                            "signature": i["signature"], "note": note}
        if "strings" in i:
            st["snapshots"][i["id"]] = snapshot_of(i)
    write_reviews(ctx, api, reviews)
    save_store(ctx, api, st)
    # The report is always brought up to date, so summary.json, which
    # Security Scan reads, follows the review at once.
    rep = api.current_report(ctx)
    if status_out:
        print(json.dumps(rep))
    else:
        print(f"Marked {len(todo)} items as {verdict.replace('-', ' ')}.")
    return 0
