"""Shared fixtures. Nothing here touches the real /etc, the real home folder
or a real service.

Every test runs against a sandbox made in pytest's temporary folder: a fake
/etc, a fake home, a fake /tmp, and a folder of stub commands that stand in
for sudo, systemctl, resolvectl, notify-send and the rest. The stub sudo
allows exactly the commands in the rule bin/black-ops-install prints, as the
real rule would, and runs the real root helper, system/apply, through
tests/fake_helper.py, which points every one of the helper's paths into the
sandbox before it runs.

Some fixtures describe files Black Ops no longer manages, such as the Ollama
drop-in and the onnxruntime folder. They are there so the tests can show that
an upgrade from 0.1 leaves them exactly as they were.
"""
import importlib.machinery
import re
import shutil
import subprocess
import importlib.util
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

if os.geteuid() == 0:
    pytest.exit("These tests must not run as root.", returncode=2)


def load_module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def flag_key(info):
    return f"{info.st_dev}:{info.st_ino}"


STOCK_HOSTS = """\
# Static table lookup for hostnames.
# See hosts(5) for details.
127.0.0.1        localhost
::1              localhost
"""

# A hosts file with telemetry blocks added by hand before the plugin existed,
# as on the machine it was first written for.
HAND_HOSTS = STOCK_HOSTS + """
# onnxruntime telemetry (1DS), blocked 2026-09-23 for Nightloom
0.0.0.0 mobile.events.data.microsoft.com
:: mobile.events.data.microsoft.com
# ComfyUI frontend Sentry and Claude Code Datadog telemetry, blocked 2026-09-23
0.0.0.0 o4507954455314432.ingest.us.sentry.io
:: o4507954455314432.ingest.us.sentry.io
0.0.0.0 http-intake.logs.us5.datadoghq.com
:: http-intake.logs.us5.datadoghq.com
"""

# /etc/hosts as Black Ops 0.1 left it when switched on: the three hosts it
# then managed, all inside its block. Taken from the machine it was written
# for, which is how 0.1 renders the block.
BLOCK_01 = """\
# BEGIN black-ops
# Managed by the Black Ops bar plugin. Switch it off there rather than editing here.
0.0.0.0 mobile.events.data.microsoft.com
:: mobile.events.data.microsoft.com
0.0.0.0 o4507954455314432.ingest.us.sentry.io
:: o4507954455314432.ingest.us.sentry.io
0.0.0.0 http-intake.logs.us5.datadoghq.com
:: http-intake.logs.us5.datadoghq.com
"""
HOSTS_01 = STOCK_HOSTS + "\n" + BLOCK_01 + "# END black-ops\n"
# The same with 0.1's optional ollama.com block switched on as well.
HOSTS_01_OLLAMA = (STOCK_HOSTS + "\n" + BLOCK_01 +
                   "0.0.0.0 ollama.com\n:: ollama.com\n# END black-ops\n")


def state_01(ollama_block=False):
    """state.json as Black Ops 0.1 wrote it, switched on with every row
    adopted except the VPN app's, which it applied."""
    rows = {k: {"how": "adopted", "at": 1790189124}
            for k in ("hosts", "onnx", "ollama-offline", "dns", "weather", "agents",
                      "claude", "openwebui")}
    rows["proton"] = {"how": "applied", "at": 1790189124}
    if ollama_block:
        rows["ollama-block"] = {"how": "applied", "at": 1790189200}
    return {"version": 1, "master": True, "rows": rows, "excluded": [],
            "optional": {"ollama-block": ollama_block}, "notified": [], "errors": {}}


HAND_OLLAMA_DROPIN = """\
[Service]
# Keep Ollama off ollama.com unless a model is pulled on purpose (2026-09-23).
Environment=OLLAMA_NO_CLOUD=1
"""

HAND_DNS_DROPIN = """\
[Resolve]
# No fallback to Google, Cloudflare or Quad9 if the VPN link drops (2026-09-23).
FallbackDNS=
"""

SESSION = b"1790000000123\n0123abcd-4567-89ab-cdef-0123456789ab\n"

# The rule, as the installer prints it, is kept in the sandbox's "sudoers"
# file with the real helper path; the stub allows a command only if the rule
# names it, with the sandbox's helper standing in for the real path.
STUB_SUDO = """\
#!{python}
import os, re, sys, subprocess
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("sudo " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:1] != ["-n"] or len(args) < 2:
    sys.exit("stub sudo: expected -n and a command")
rule = open(os.path.join(root, "sudoers")).read()
allowed = set(re.findall(r"^ +/usr/local/lib/omarchy-black-ops/apply ([a-z0-9-]+),? *\\\\?$", rule, re.M))
if args[1] != os.environ["BLACK_OPS_HELPER"] or len(args) != 3 or args[2] not in allowed:
    sys.exit("sudo: a password is required")
env = dict(os.environ)
env["SUDO_UID"] = str(os.getuid())
sys.exit(subprocess.call([{python!r}, {harness!r}] + args[2:], env=env))
"""

STUB_SYSTEMCTL = """\
#!{python}
import os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("systemctl " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["show", "ollama.service"]:
    if os.path.exists(os.path.join(root, "ollama-missing")):
        print("LoadState=not-found")
        print("Environment=")
        sys.exit(0)
    dropin = os.path.join(root, "etc/systemd/system/ollama.service.d/offline.conf")
    env = "HOME=/var/lib/ollama"
    try:
        if "OLLAMA_NO_CLOUD=1" in open(dropin).read():
            env += " OLLAMA_NO_CLOUD=1"
    except OSError:
        pass
    print("LoadState=loaded")
    print("Environment=" + env)
    sys.exit(0)
if args[:2] == ["--user", "is-active"]:
    try:
        state = open(os.path.join(root, "webui-state")).read().strip()
    except OSError:
        state = "inactive"
    print(state)
    sys.exit(0 if state == "active" else 3)
sys.exit(0)
"""

STUB_LOGGER = """\
#!{python}
import os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write({name!r} + " " + " ".join(sys.argv[1:]) + "\\n")
sys.exit(0)
"""


class Sandbox:
    def __init__(self, root):
        self.root = root
        self.home = root / "home"
        self.etc = root / "etc"
        self.tmp = root / "tmp"
        self.bin = root / "bin"
        self.proc = root / "proc"
        self.helper = root / "lib" / "apply"
        # /etc/systemd/system exists on any systemd machine; the drop-in
        # folders inside it are what the helper may have to create.
        for d in (self.home, self.etc / "systemd" / "system", self.tmp, self.bin,
                  self.proc, self.helper.parent):
            d.mkdir(parents=True, exist_ok=True)
        # Stands in for the installed helper: a copy of the one in the
        # repository, as the installer makes. bin/black-ops compares the two;
        # the stub sudo runs the real one from the repository.
        self.install_helper()
        py = sys.executable
        harness = str(REPO / "tests" / "fake_helper.py")
        self.stub("sudo", STUB_SUDO.format(python=py, harness=harness))
        self.stub("systemctl", STUB_SYSTEMCTL.format(python=py))
        for name in ("resolvectl", "notify-send", "omarchy-shell"):
            self.stub(name, STUB_LOGGER.format(python=py, name=name))
        (root / "flags.json").write_text("{}")
        (root / "calls.log").write_text("")
        self.install_rule()

    def install_helper(self, text=None):
        """Put a helper in place: the repository's, or other bytes standing
        for a copy from another version."""
        if text is None:
            shutil.copyfile(REPO / "system" / "apply", self.helper)
        else:
            self.helper.write_text(text)
        self.helper.chmod(0o755)

    def install_rule(self, text=None):
        """Put a sudoers rule in place: the one the installer prints now, or
        another, standing for the rule of another version."""
        if text is None:
            text = subprocess.run(["bash", str(REPO / "bin" / "black-ops-install"),
                                   "--print-sudoers", "alice"], capture_output=True,
                                  text=True, check=True, env={"PATH": "/usr/bin:/bin"}).stdout
        (self.root / "sudoers").write_text(text)

    def stub(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    @property
    def env(self):
        return {
            "HOME": str(self.home),
            "PATH": str(self.bin),
            "BLACK_OPS_ETC": str(self.etc),
            "BLACK_OPS_TMP": str(self.tmp),
            "BLACK_OPS_HELPER": str(self.helper),
            "BLACK_OPS_SUDO": str(self.bin / "sudo"),
            "BLACK_OPS_PROC": str(self.proc),
            "BLACK_OPS_SYS": str(self.root / "sys"),
            "BLACK_OPS_USR_LIB": str(self.root / "usr/lib"),
            "BLACK_OPS_RUN": str(self.root / "run"),
            "BLACK_OPS_PACMAN_DB": str(self.root / "pacman"),
            "BLACK_OPS_FAKE_ROOT": str(self.root),
        }

    # ------------------------------------------------------------ records

    def calls(self, prefix=""):
        lines = (self.root / "calls.log").read_text().splitlines()
        return [l for l in lines if l.startswith(prefix)]

    def helper_verbs(self):
        return [l.split()[-1] for l in self.calls("sudo ")]

    def clear_calls(self):
        (self.root / "calls.log").write_text("")

    def flags(self):
        return json.loads((self.root / "flags.json").read_text())

    def set_immutable(self, path, on=True):
        store = self.flags()
        key = flag_key(os.lstat(path))
        if on:
            store[key] = True
        else:
            store.pop(key, None)
        (self.root / "flags.json").write_text(json.dumps(store))

    def is_immutable(self, path):
        try:
            return flag_key(os.lstat(path)) in self.flags()
        except OSError:
            return None

    # ------------------------------------------------------------ paths

    @property
    def hosts(self):
        return self.etc / "hosts"

    @property
    def ollama_dropin(self):
        return self.etc / "systemd/system/ollama.service.d/offline.conf"

    @property
    def dns_dropin(self):
        return self.etc / "systemd/resolved.conf.d/no-fallback.conf"

    @property
    def onnx(self):
        return self.home / ".cache/Microsoft/DeveloperTools/.onnxruntime"

    @property
    def weather(self):
        return self.home / ".local/state/omarchy/settings/weather.json"

    @property
    def shell_json(self):
        return self.home / ".config/omarchy/shell.json"

    @property
    def claude(self):
        return self.home / ".claude/settings.json"

    @property
    def proton(self):
        return self.home / ".config/Proton/VPN/settings.json"

    @property
    def webui_db(self):
        return self.home / "AI/openwebui/data/webui.db"

    @property
    def state_file(self):
        return self.home / ".local/state/omarchy-black-ops/state.json"

    def state(self):
        return json.loads(self.state_file.read_text())

    # ------------------------------------------------------------ machines

    def write(self, path, text, mode=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        if mode is not None:
            path.chmod(mode)

    def make_webui(self, value):
        self.webui_db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.webui_db)
        con.execute('CREATE TABLE config ("key" TEXT NOT NULL, value JSON NOT NULL, '
                    'updated_at BIGINT, PRIMARY KEY ("key"))')
        rows = [("code_execution.enable", json.dumps(value)),
                ("code_interpreter.enable", json.dumps(value)),
                ("code_execution.engine", json.dumps("pyodide")),
                ("ui.default_locale", json.dumps("en-GB"))]
        con.executemany("INSERT INTO config VALUES (?, ?, 0)", rows)
        con.commit()
        con.close()

    def webui_values(self):
        con = sqlite3.connect(self.webui_db)
        rows = dict(con.execute("SELECT key, value FROM config").fetchall())
        con.close()
        return rows

    def shell_doc(self, providers=None):
        agents = {"id": "omarchy.agents"}
        if providers is not None:
            agents["providers"] = providers
        return {
            "version": 1,
            "idle": {"screensaver": 150, "lock": 300},
            "bar": {
                "position": "top",
                "layout": {
                    "left": [{"id": "omarchy.menu"}],
                    "center": [{"id": "omarchy.clock", "format": "dddd HH:mm"}],
                    "right": [{"id": "omarchy.tray"}, agents,
                              {"id": "omarchy.power", "showPercentage": False}],
                },
            },
            "plugins": [],
        }

    def stock_machine(self):
        """A machine as it ships, with the tools installed."""
        self.write(self.hosts, STOCK_HOSTS)
        self.onnx.mkdir(parents=True)
        (self.onnx / "device.id").write_text("an id that identifies the machine")
        (self.onnx / "queue").mkdir()
        (self.onnx / "queue" / "events.db").write_bytes(b"\x01" * 300)
        self.write(self.weather, json.dumps(
            {"name": "Somewhere", "latitude": 48.858370, "longitude": 2.294481}, indent=2) + "\n")
        self.write(self.shell_json, json.dumps(self.shell_doc(), indent=2) + "\n")
        self.write(self.claude, json.dumps(
            {"model": "opus", "theme": "dark", "env": {"FOO": "bar"}}, indent=2) + "\n")
        self.make_webui(True)
        self.write(self.proton, json.dumps(
            {"protocol": "wireguard", "killswitch": 1, "custom_dns": {"enabled": False, "ip_list": []},
             "ipv6": True, "anonymous_crash_reports": True, "features": {"netshield": 0}},
            indent=4))

    def hand_machine(self):
        """A machine with protections applied by hand, as the one this plugin
        was first written for was, including some for apps Black Ops does not
        manage, and with a VPN app's crash reports still on."""
        self.write(self.hosts, HAND_HOSTS)
        self.onnx.mkdir(parents=True)
        self.onnx.chmod(0o500)
        self.set_immutable(self.onnx)
        self.write(self.ollama_dropin, HAND_OLLAMA_DROPIN)
        self.write(self.dns_dropin, HAND_DNS_DROPIN)
        self.write(self.weather, json.dumps(
            {"name": "Somewhere", "latitude": 48.8568, "longitude": 2.3071}, indent=2) + "\n")
        self.write(self.shell_json, json.dumps(self.shell_doc(
            {"claude": {"enabled": True}, "codex": {"enabled": False},
             "fireworks": {"enabled": False}}), indent=2) + "\n")
        self.write(self.claude, json.dumps(
            {"model": "opus", "env": {"DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"},
             "theme": "dark"}, indent=2) + "\n")
        self.make_webui(False)
        self.write(self.proton, json.dumps(
            {"protocol": "wireguard", "killswitch": 1, "ipv6": True,
             "anonymous_crash_reports": True}, indent=4))

    def machine_01(self, ollama_block=False):
        """This machine as Black Ops 0.1 left it, switched on: its block in
        /etc/hosts and its state file, with the protections for apps it no
        longer manages in place."""
        self.hand_machine()
        self.write(self.hosts, HOSTS_01_OLLAMA if ollama_block else HOSTS_01)
        self.write(self.proton, json.dumps(
            {"protocol": "wireguard", "killswitch": 1, "ipv6": True,
             "anonymous_crash_reports": False}, indent=4))
        self.write(self.state_file, json.dumps(state_01(ollama_block), indent=2) + "\n")
        self.state_file.parent.chmod(0o700)
        self.state_file.chmod(0o600)

    def snapshot(self):
        """Every file in the fake machine, by path, with its bytes and mode."""
        out = {}
        for base in (self.etc, self.home, self.tmp):
            for dirpath, dirnames, filenames in os.walk(base):
                # Black Ops's own state, and the summary it writes for
                # other tools, are not part of the machine being changed.
                if "omarchy-black-ops" in dirpath or dirpath.endswith("/.local/state/black-ops"):
                    continue
                for name in filenames + dirnames:
                    p = Path(dirpath) / name
                    if str(p).endswith("/.local/state/black-ops"):
                        continue
                    info = os.lstat(p)
                    data = p.read_bytes() if stat.S_ISREG(info.st_mode) else None
                    out[str(p)] = (data, stat.S_IMODE(info.st_mode), self.is_immutable(p))
        return out


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox(tmp_path)


@pytest.fixture
def bo():
    """bin/black-ops, imported."""
    return load_module("black_ops", REPO / "bin" / "black-ops")


@pytest.fixture
def helper():
    return load_module("black_ops_apply", REPO / "system" / "apply")


@pytest.fixture
def run(bo, sandbox, capsys):
    """Run bin/black-ops in the sandbox and return the JSON it printed."""
    def _run(*argv):
        capsys.readouterr()
        assert bo.main(list(argv), sandbox.env) == 0
        return json.loads(capsys.readouterr().out)
    return _run
