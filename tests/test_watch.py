"""The software watch, lib/black_ops_watch.py, against a sandboxed machine.

Every package, program and trace here is a fixture made in the sandbox:
pacman's database, the files packages own, a flatpak, an AppImage, pip and
npm installs, mise tools and what programs leave in the home folder. The
scan reads them with the real GNU grep, as it does on a real machine.
"""
import hashlib
import io
import json
import os
import shutil
import socket
import stat
import struct
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from conftest import REPO

pytestmark = pytest.mark.skipif(not os.access("/usr/bin/grep", os.X_OK),
                                reason="the scan needs GNU grep at /usr/bin/grep")

SPOOL_PROG = REPO / "system" / "watch-spool"
HOOK = REPO / "system" / "90-omarchy-black-ops-watch.hook"
ELF_APPIMAGE = b"\x7fELF\x02\x01\x01\x00AI\x02" + b"\x00" * 53


class Box:
    """The shared sandbox, with the watch's own paths added."""

    def __init__(self, sandbox, bo):
        self.s = sandbox
        self.bo = bo
        self.root = sandbox.root
        self.home = sandbox.home
        self.fs = self.root / "fsroot"
        self.var = self.root / "var"
        self.env = dict(sandbox.env, BLACK_OPS_VAR=str(self.var), BLACK_OPS_ROOT=str(self.fs))
        (self.root / "pacman").mkdir(exist_ok=True)
        self.state = self.home / ".local/state/black-ops"
        self.units = self.home / ".config/systemd/user"

    @property
    def w(self):
        return self.bo.EXT["watch"]

    @property
    def ctx(self):
        return self.bo.Context(self.env)

    def write(self, path, data, mode=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        if mode is not None:
            path.chmod(mode)
        return path

    def pkg(self, name, version, files, dirs=()):
        """A pacman package: its database entry and the files it owns."""
        for old in (self.root / "pacman").glob(f"{name}-*"):
            shutil.rmtree(old)
        d = self.root / "pacman" / f"{name}-{version}"
        self.write(d / "desc", f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n")
        listing = list(dirs) + sorted(files)
        self.write(d / "files", "%FILES%\n" + "".join(l + "\n" for l in listing) + "\n")
        for rel, data in files.items():
            self.write(self.fs / rel, data)
        for rel in dirs:
            (self.fs / rel).mkdir(parents=True, exist_ok=True)

    def sync_db(self, names):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for n in names:
                info = tarfile.TarInfo(f"{n}-1.0-1")
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
        self.write(self.root / "sync" / "core.db", buf.getvalue())

    def main(self, capsys, *argv, code=0):
        capsys.readouterr()
        assert self.bo.main(list(argv), self.env) == code
        return capsys.readouterr().out

    def status(self, capsys, *argv):
        return json.loads(self.main(capsys, *(argv or ("status",))))

    def listed(self, capsys, *flags):
        return json.loads(self.main(capsys, "watch", "list", "--json", *flags))

    def scan(self, capsys, kind="--full"):
        return self.main(capsys, "watch", "scan", kind)

    def install_hook(self):
        self.write(self.s.etc / "pacman.d/hooks/90-omarchy-black-ops-watch.hook", HOOK.read_bytes())
        self.write(self.s.helper.parent / "watch-spool", SPOOL_PROG.read_bytes(), mode=0o755)


@pytest.fixture
def box(sandbox, bo):
    return Box(sandbox, bo)


def asar(header, body=b""):
    """An Electron archive: a pickled JSON header, then the file bodies."""
    h = json.dumps(header).encode()
    return struct.pack("<4I", 4, len(h) + 8, len(h) + 4, len(h)) + h + body


def pairs(items):
    return {(i["program"], i["signature"]) for i in items}


def machine(box):
    """Software carrying every kind of signal, and some that must not be."""
    box.sync_db(["someapp", "engine", "webby", "firefoxish", "python-foo"])
    box.pkg("someapp", "1.0-1", {
        "usr/bin/someapp": b"\x00http-intake.logs.us5.datadoghq.com\x00SOMEAPP_TELEMETRY\x00"
                           b"DOTNET_CLI_TELEMETRY_OPTOUT\x00SOMEAPP_DISABLE_UPDATE\x00",
        "usr/share/doc/someapp/README": b"api.mixpanel.com is mentioned in the docs only",
    })
    box.pkg("crashy", "2.0-1", {"usr/lib/crashy/app.js":
                                b'const dsn = "https://abc@o123456.ingest.us.sentry.io/42";\n'})
    # A browser engine's binary carries Google Analytics in block lists.
    box.pkg("engine", "1-1", {"usr/lib/libengine.so": b"\x00https://www.google-analytics.com/\x00"})
    box.pkg("webby", "1-1", {"usr/lib/webby/index.js": b'fetch("https://www.google-analytics.com/collect")'})
    box.pkg("firefoxish", "1-1", {
        "usr/bin/firefoxish": b"\x00FIREFOXISH_DISABLE_TELEMETRY\x00",
        "usr/lib/firefoxish/omni.js": b'"https://www.google-analytics.com/x"',
        "usr/share/applications/firefoxish.desktop": b"[Desktop Entry]\nCategories=Network;WebBrowser;\n",
    })
    box.pkg("electronapp", "3-1", {"usr/lib/electronapp/resources/app.asar": asar(
        {"files": {"node_modules": {"files": {"@sentry": {"files": {"electron": {"files": {}}}},
                                              "left-pad": {"files": {}}}},
                   "main.js": {"size": 10, "offset": "0"}}},
        b"crashReporter.start({uploadToServer: true}); feed('latest-linux.yml')")})
    box.pkg("vendored", "1-1", {"usr/bin/vendored":
                                b"\x00https://telemetry.vendored-app.com/v1\x00telemetry.sdk.version\x00"})
    box.pkg("python-foo", "1-1", {"usr/lib/python3.14/site-packages/sentry_sdk/__init__.py": b"x = 1\n"},
            dirs=["usr/lib/python3.14/site-packages/sentry_sdk-2.0.0.dist-info/"])
    # A virtual environment under ~/AI, found by its pyvenv.cfg.
    venv = box.home / "AI/tool/.venv"
    box.write(venv / "pyvenv.cfg", "home = /usr/bin\n")
    sp = venv / "lib/python3.12/site-packages"
    (sp / "gradio-4.0.0.dist-info").mkdir(parents=True)
    (sp / "gradio").mkdir()
    (sp / "numpy-2.0.0.dist-info").mkdir()
    # A global npm package with a library and a string of its own.
    nm = box.home / ".npm-global/lib/node_modules/cooltool"
    box.write(nm / "package.json", '{"name": "cooltool", "version": "1.2.3"}')
    box.write(nm / "cli.js", 'post("https://api.mixpanel.com/track")')
    box.write(nm / "node_modules/posthog-node/package.json", '{"name": "posthog-node"}')
    # An AppImage, whose payload needs unsquashfs, which the sandbox lacks.
    box.write(box.home / "Applications/Thing-1.2.3-x86_64.AppImage", ELF_APPIMAGE + b"payload")
    # A flatpak with the network and the whole file system.
    fp = box.var / "lib/flatpak/app/org.example.App/current/active"
    box.write(fp / "metadata", "[Application]\nname=org.example.App\n\n[Context]\n"
                               "shared=network;ipc;\nfilesystems=host;\n")
    box.write(fp / "files/bin/app", b"\x00nothing to see\x00")
    # Traces programs leave behind.
    box.write(box.home / ".zenish/abc.default/datareporting/glean/pending_pings/1234", "{}")
    box.write(box.home / ".config/Chromish/Consent To Send Stats", "0123-client-id")
    box.write(box.home / ".config/Chromish/installation_id", "x")


# ------------------------------------------------------------ hook and spool

def test_the_hook_file_is_the_contracts():
    contract = (REPO / "docs/contract.md").read_text()
    block = contract.split("/etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook`:\n\n```\n", 1)[1]
    assert HOOK.read_text() == block.split("```", 1)[0]


def spool_dir(box):
    return box.var / "lib/omarchy-black-ops/pending"


def run_spool(box, text, var=None):
    env = {"PATH": "/usr/bin:/bin", "BLACK_OPS_VAR": str(var or box.var)}
    return subprocess.run(["sh", str(SPOOL_PROG)], input=text, capture_output=True, text=True, env=env)


def test_the_spool_writer_keeps_package_names_only(box):
    r = run_spool(box, "firefox\nlib32-glibc\npython-sentry_sdk\nbad name\n$(id)\n\n../etc\n")
    assert r.returncode == 0, r.stderr
    files = list(spool_dir(box).glob("*.list"))
    assert len(files) == 1
    assert files[0].read_text() == "firefox\nlib32-glibc\npython-sentry_sdk\n"
    assert oct(files[0].stat().st_mode & 0o777) == "0o644"
    assert oct(spool_dir(box).stat().st_mode & 0o777) == "0o755"
    assert not list(spool_dir(box).glob(".*"))


def test_the_spool_writer_drops_old_files_and_writes_nothing_for_nothing(box):
    old = box.write(spool_dir(box) / "1000-1.list", "old\n")
    week = box.write(spool_dir(box) / "2000-1.list", "recent\n")
    os.utime(old, (time.time() - 31 * 86400,) * 2)
    os.utime(week, (time.time() - 7 * 86400,) * 2)
    assert run_spool(box, "").returncode == 0
    assert sorted(p.name for p in spool_dir(box).iterdir()) == ["2000-1.list"]


def test_the_spool_writer_never_fails_the_transaction(box):
    blocker = box.write(box.root / "not-a-folder", "x")
    r = run_spool(box, "firefox\n", var=blocker)
    assert r.returncode == 0
    assert "could not note" in r.stderr


def test_the_installer_puts_the_hook_in_place_inside_its_markers():
    text = (REPO / "bin/black-ops-install").read_text()
    section = text.split("# ---- watch", 1)[1].split("# ---- end watch", 1)[0]
    assert '"$SRC/system/watch-spool" "$LIBDIR/.watch-spool.new"' in section
    assert 'mv -f "$LIBDIR/.watch-spool.new" "$LIBDIR/watch-spool"' in section
    assert "/etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook" in section
    assert "-m 755 /var/lib/omarchy-black-ops /var/lib/omarchy-black-ops/pending" in section
    # Every step goes through run(), so a dry run changes nothing.
    steps = [l for l in section.splitlines() if l.startswith(("install", "mv", "cp", "rm"))]
    assert steps == []


# ------------------------------------------------------------- the row

EXE = REPO / "bin" / "black-ops"


def expected_units(box):
    spool = spool_dir(box)
    svc = lambda desc, flag: (f"[Unit]\nDescription=Black Ops software watch: {desc}\n\n[Service]\n"
                              f"Type=oneshot\nExecStart={EXE} watch scan --{flag} --quiet\n"
                              "Nice=19\nIOSchedulingClass=idle\n")
    return {
        "black-ops-watch.path":
            "[Unit]\nDescription=Black Ops software watch: packages pacman has just installed or upgraded\n\n"
            f"[Path]\nPathChanged={spool}\nUnit=black-ops-watch.service\n\n[Install]\nWantedBy=paths.target\n",
        "black-ops-watch.service": svc("scan the packages pacman has just changed", "pending"),
        "black-ops-watch-daily.timer":
            "[Unit]\nDescription=Black Ops software watch: daily scan of what has changed\n\n"
            "[Timer]\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=1h\n"
            "Unit=black-ops-watch-daily.service\n\n[Install]\nWantedBy=timers.target\n",
        "black-ops-watch-daily.service": svc("scan what has changed", "changed"),
        "black-ops-watch-weekly.timer":
            "[Unit]\nDescription=Black Ops software watch: weekly scan of everything\n\n"
            "[Timer]\nOnCalendar=weekly\nPersistent=true\nRandomizedDelaySec=2h\n"
            "Unit=black-ops-watch-weekly.service\n\n[Install]\nWantedBy=timers.target\n",
        "black-ops-watch-weekly.service": svc("scan everything", "full"),
        "black-ops-watch-user.service": svc("scan what has changed in your own folders", "changed"),
    }


def rows(rep):
    return {r["id"]: r for r in rep["rows"]}


def test_the_row_writes_its_units_and_removes_them_again(box, capsys):
    box.s.stock_machine()
    rep = box.status(capsys, "on")
    w = rows(rep)["watch"]
    assert w["status"] == "off" and w["optional"] and not w["privileged"] and w["switchable"]
    box.s.clear_calls()
    rep = box.status(capsys, "row", "watch", "on")
    for name, text in expected_units(box).items():
        assert (box.units / name).read_text() == text, name
        assert oct((box.units / name).stat().st_mode & 0o777) == "0o644"
    user_path = (box.units / "black-ops-watch-user.path").read_text()
    assert f"PathChanged={box.home}/.local/bin\n" in user_path
    assert f"PathChanged={box.home}/.npm-global/lib/node_modules\n" in user_path
    for name, target in (("black-ops-watch.path", "paths"), ("black-ops-watch-user.path", "paths"),
                         ("black-ops-watch-daily.timer", "timers"),
                         ("black-ops-watch-weekly.timer", "timers")):
        assert os.path.islink(box.units / f"{target}.target.wants" / name)
    calls = box.s.calls("systemctl")
    assert "systemctl --user daemon-reload" in calls
    assert any(c.startswith("systemctl --user start black-ops-watch.path") for c in calls)
    assert "systemctl --user start --no-block black-ops-watch-daily.service" in calls
    # On, but without the pacman hook: amber, with a reason.
    w = rows(rep)["watch"]
    assert w["status"] == "warn" and w["colour"] == "amber" and "pacman hook" in w["why"] + w["detail"] \
        or "pacman hook" in json.dumps(w)
    box.install_hook()
    w = rows(box.status(capsys))["watch"]
    assert w["status"] == "ok" and w["colour"] == "green"
    assert box.status(capsys)["watch"]["hookInstalled"] is True
    rep = box.status(capsys, "row", "watch", "off")
    assert rows(rep)["watch"]["status"] == "off" and rows(rep)["watch"]["colour"] == "grey"
    for name in list(expected_units(box)) + ["black-ops-watch-user.path"]:
        assert not (box.units / name).exists()
    assert not (box.units / "paths.target.wants").exists()
    assert not (box.units / "timers.target.wants").exists()


def test_a_unit_changed_by_hand_reads_as_slipped(box, capsys):
    box.s.stock_machine()
    box.status(capsys, "on")
    box.status(capsys, "row", "watch", "on")
    (box.units / "black-ops-watch-daily.timer").write_text("[Timer]\nOnCalendar=yearly\n")
    rep = box.status(capsys)
    assert "watch" in rep["slipped"]


# ---------------------------------------------------------- the inventory

def test_pacman_packages_are_read_with_foreign_ones_marked(box):
    machine(box)
    units = {u.key: u for u in box.w.pacman_units(box.ctx)}
    some = units["pacman:someapp"]
    assert some.version == "1.0-1" and some.exe == "/usr/bin/someapp" and not some.foreign
    assert list(some.files) == [str(box.fs / "usr/bin/someapp")]        # the README is skipped
    assert units["pacman:crashy"].foreign and units["pacman:electronapp"].foreign
    assert units["pacman:firefoxish"].browser
    foo = units["pacman:python-foo"]
    assert foo.names["sentry_sdk"] == ("pip", str(box.fs / "usr/lib/python3.14/site-packages/sentry_sdk"))


def test_pip_npm_flatpak_appimage_and_mise_are_inventoried(box):
    machine(box)
    mise = box.home / ".local/share/mise/installs/vend"
    box.write(mise / "1.0/bin/vend", b"old")
    box.write(mise / "2.0/bin/vend", b"new")
    os.symlink(mise / "2.0", mise / "latest")
    ctx = box.ctx
    cfg = box.w.load_config(ctx)
    units = {u.key: u for u in box.w.all_units(ctx, cfg)}
    pip = units[f"pip:{box.home}/AI/tool/.venv/lib/python3.12/site-packages"]
    assert pip.program == "tool venv" and set(pip.names) == {"gradio", "numpy"}
    npm = units[f"npm:{box.home}/.npm-global/lib/node_modules/cooltool"]
    assert npm.version == "1.2.3" and "posthog-node" in npm.names
    fp = units["flatpak:system:org.example.App"]
    assert fp.notes and fp.notes[0][0] == "watch-exposure"
    app = units["appimage:thing"]
    assert app.program == "Thing" and app.source == "appimage"
    vend = units["mise:vend"]
    assert vend.version == "2.0" and list(vend.files) == [str(mise / "2.0/bin/vend")]
    # A different set of folders to search, from the configuration file.
    box.write(box.home / ".config/omarchy-black-ops/watch.toml", 'venv_roots = ["~/elsewhere"]\n')
    cfg = box.w.load_config(box.ctx)
    assert not any(k.startswith("pip:") and "AI/tool" in k for k in
                   (u.key for u in box.w.pip_units(box.ctx, cfg)))


def test_the_inventory_follows_the_contract(box, capsys):
    machine(box)
    box.scan(capsys)
    index = json.loads((box.state / "inventory/index.json").read_text())
    assert index["schema"] == 1 and isinstance(index["generatedAt"], int)
    sources = {i["source"] for i in index["items"]}
    assert {"pacman", "npm", "flatpak", "appimage", "pip"} <= sources
    some = next(i for i in index["items"] if i["path"] == str(box.fs / "usr/bin/someapp"))
    assert some["package"] == "someapp" and some["version"] == "1.0-1" and some["size"] > 0
    assert some["signatures"] == ["datadog-intake", "watch-kill-switch"]
    assert some["sha256"] == hashlib.sha256((box.fs / "usr/bin/someapp").read_bytes()).hexdigest()
    for f in ("inventory/index.json", "watch.json"):
        assert oct((box.state / f).stat().st_mode & 0o777) == "0o600"
    assert oct(box.state.stat().st_mode & 0o777) == "0o700"


def test_only_what_changed_is_scanned_again(box, capsys):
    machine(box)
    first = box.scan(capsys)
    assert "Scanned" in first and "first scan" in first
    assert box.scan(capsys, "--changed").startswith("Scanned 0 of")
    box.write(box.fs / "usr/lib/webby/index.js", b'fetch("https://www.google-analytics.com/c"); //more')
    assert box.scan(capsys, "--changed").startswith("Scanned 1 of")
    # A new version of a package is scanned again even with the same files.
    box.pkg("crashy", "2.1-1", {"usr/lib/crashy/app.js":
                                b'const dsn = "https://abc@o123456.ingest.us.sentry.io/42";\n'})
    assert box.scan(capsys, "--changed").startswith("Scanned 1 of")
    assert box.scan(capsys, "--full").startswith("Scanned")
    assert "Scanned 0 of" not in box.scan(capsys, "--full")


def test_a_pending_scan_reads_the_spool_once(box, capsys):
    machine(box)
    run_spool(box, "someapp\nnot-installed\n")
    assert box.status(capsys, "watch", "status", "--json")["pendingCount"] == 2
    out = box.scan(capsys, "--pending")
    assert out.startswith("Scanned 1 of 1")
    seen = (box.state / "inventory/spool-seen.txt").read_text().split()
    assert seen == [p.name for p in spool_dir(box).glob("*.list")]
    assert box.scan(capsys, "--pending").startswith("Scanned 0 of 0")
    assert box.status(capsys, "watch", "status", "--json")["pendingCount"] == 0


# ------------------------------------------------------------ the signals

def test_each_signal_is_found_and_the_noise_is_not(box, capsys):
    machine(box)
    box.scan(capsys)
    items = box.listed(capsys)
    assert pairs(items) == {
        ("someapp", "datadog-intake"),            # a signature string
        ("someapp", "watch-kill-switch"),         # SOMEAPP_TELEMETRY, the program's own switch
        ("crashy", "sentry-ingest"),              # a Sentry key
        ("webby", "google-analytics"),            # in the app's own code
        ("electronapp", "sentry-ingest"),         # @sentry/electron inside app.asar
        ("electronapp", "watch-electron-crash"),  # uploadToServer: true
        ("vendored", "watch-own-endpoint"),       # telemetry.<vendor>, not telemetry.sdk.version
        ("python-foo", "sentry-ingest"),          # a dist-info folder
        ("tool venv", "watch-sdk-gradio"),        # a pip library in a venv
        ("cooltool", "posthog"),                  # an npm library
        ("cooltool", "mixpanel"),                 # a string in an npm package
        ("zenish", "watch-runtime"),              # Glean pings waiting to be sent
        ("Chromish", "watch-runtime"),            # a consent file with a client id
    }
    by = {(i["program"], i["signature"]): i for i in items}
    dsn = by[("crashy", "sentry-ingest")]
    assert dsn["match"] == "o123456.ingest.us.sentry.io"
    assert dsn["summary"] == "Has a Sentry crash report key built in."
    some = by[("someapp", "datadog-intake")]
    assert some["optOut"] == "SOMEAPP_TELEMETRY" and some["exe"] == "/usr/bin/someapp"
    assert some["package"] == "someapp" and some["version"] == "1.0-1" and some["ecosystem"] == "pacman"
    assert some["evidence"] == [{"file": str(box.fs / "usr/bin/someapp"), "match": "http-intake.logs."}]
    assert by[("tool venv", "watch-sdk-gradio")]["optOut"] == "GRADIO_ANALYTICS_ENABLED=False"
    assert by[("vendored", "watch-own-endpoint")]["match"] == "telemetry.vendored-app.com"
    for i in items:
        assert i["kind"] == "static" and i["severity"] == "warn" and i["host"] is None
        assert len(i["summary"]) < 120
        assert "datadoghq" not in i["summary"] and ".com" not in i["summary"]
    notes = box.listed(capsys, "--notes")["notes"]
    got = {(n["program"], n["signature"], n["match"]) for n in notes}
    assert ("someapp", "watch-kill-switch", "DOTNET_CLI_TELEMETRY_OPTOUT") in got
    assert ("someapp", "watch-update-check", "SOMEAPP_DISABLE_UPDATE") in got
    assert ("electronapp", "watch-update-check", "latest-linux.yml") in got
    assert ("org.example.App", "watch-exposure", "shared=network with filesystems=host") in got
    assert ("Thing", "watch-not-scanned", "AppImage payload not read: unsquashfs is not installed") in got
    assert ("Chromish", "watch-install-id", "installation_id") in got


BLOCKER = b'''#!/usr/bin/env python3
TELEMETRY_HOST = "mobile.events.data.microsoft.com"
SENTRY_HOST = "o4507954455314432.ingest.us.sentry.io"
BLOCKED_HOSTS = [TELEMETRY_HOST, SENTRY_HOST]
LINES = [f"{a} {h}" for h in BLOCKED_HOSTS for a in ("0.0.0.0", "::")]
HOSTS_FILE = Path("/etc/hosts")
'''


def test_a_script_that_blocks_telemetry_hosts_is_a_note(box, capsys):
    box.pkg("blocker", "1-1", {
        "usr/bin/blocker": BLOCKER,
        "usr/bin/block-sh": b"#!/bin/sh\necho '0.0.0.0 api.segment.io' >> /etc/hosts\n"
                            b"echo ':: api.segment.io' >> /etc/hosts\n",
    })
    box.scan(capsys)
    assert box.listed(capsys) == []
    notes = {(n["path"].rsplit("/", 1)[1], n["signature"], n["match"])
             for n in box.listed(capsys, "--notes")["notes"]}
    assert notes == {("blocker", "watch-block-list", "events.data.microsoft.com"),
                     ("blocker", "watch-block-list", "o4507954455314432.ingest.us.sentry.io"),
                     ("block-sh", "watch-block-list", "api.segment.io")}
    assert box.status(capsys, "watch", "status", "--json")["noteCount"] == 3


def test_a_block_list_does_not_hide_a_client(box, capsys):
    # The same script, but it also sends to the host.
    box.pkg("sends", "1-1", {"usr/bin/sends":
                             BLOCKER + b'post("https://abc@o4507954455314432.ingest.us.sentry.io/1")\n'})
    # A hosts line, but the host is also used on another line.
    box.pkg("mixed", "1-1", {"usr/bin/mixed":
                             b"#!/bin/sh\n# 0.0.0.0 api.segment.io\ncurl -d x api.segment.io/v1/track\n"})
    # A block list with no /etc/hosts and no null address.
    box.pkg("nolist", "1-1", {"usr/bin/nolist": b'BLOCKLIST = ["x"]\nHOST = "api.segment.io"\n'})
    # A binary is never let off.
    box.pkg("binary", "1-1", {"usr/bin/binary": b"\x00" + BLOCKER})
    box.scan(capsys)
    got = {(i["path"].rsplit("/", 1)[1], i["signature"]) for i in box.listed(capsys)}
    assert got == {("sends", "sentry-ingest"), ("mixed", "segment"), ("nolist", "segment"),
                   ("binary", "microsoft-1ds"), ("binary", "sentry-ingest")}
    # Only the host the client does not send to is let off, as a note.
    notes = {(n["path"].rsplit("/", 1)[1], n["match"]) for n in box.listed(capsys, "--notes")["notes"]
             if n["signature"] == "watch-block-list"}
    assert notes == {("sends", "events.data.microsoft.com")}


@pytest.mark.skipif(shutil.which("brotli") is None, reason="brotli is not installed")
def test_a_brotli_file_is_read_through_a_pipe(box, capsys):
    raw = b"\x00GROKISH_TELEMETRY_ENABLED\x00https://o99.ingest.us.sentry.io/1\x00"
    packed = subprocess.run(["brotli", "-c"], input=raw, capture_output=True, check=True).stdout
    box.pkg("grokish", "1-1", {"usr/lib/grokish/bin/grokish.br": packed})
    box.env["PATH"] = box.env["PATH"] + ":/usr/bin"
    box.scan(capsys)
    assert pairs(box.listed(capsys)) == {("grokish", "sentry-ingest"), ("grokish", "watch-kill-switch")}


def test_a_scan_never_runs_what_it_scans_and_opens_no_socket(box, capsys, monkeypatch):
    machine(box)
    marker = box.root / "ran"
    box.pkg("trap", "1-1", {"usr/bin/trap": f"#!/bin/sh\ntouch {marker}\n# api.segment.io\n".encode()})
    (box.fs / "usr/bin/trap").chmod(0o755)

    def refuse(*a, **k):
        raise AssertionError("the watch must not open a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    box.scan(capsys)
    assert not marker.exists()
    assert ("trap", "segment") in pairs(box.listed(capsys))


def test_item_ids_follow_the_contract(box, capsys):
    machine(box)
    box.scan(capsys)
    for i in box.listed(capsys):
        want = hashlib.sha256("\0".join(["watch", "static", i["path"], i["signature"]]).encode()).hexdigest()
        assert i["id"] == want[:16]


# ------------------------------------------------- the status and the colours

def switched_on(box, capsys):
    box.s.stock_machine()
    box.status(capsys, "on")
    box.status(capsys, "row", "watch", "on")
    box.install_hook()


def test_a_static_finding_is_amber_and_never_red(box, capsys):
    machine(box)
    switched_on(box, capsys)
    box.scan(capsys)
    # Something new after the first scan is a fault the row asks about.
    box.pkg("latecomer", "1-1", {"usr/bin/latecomer": b"\x00api.segment.io\x00"})
    box.scan(capsys, "--full")
    rep = box.status(capsys)
    assert rep["flagged"] and all(i["source"] == "watch" for i in rep["flagged"])
    assert {i["colour"] for i in rep["flagged"]} == {"amber"}
    assert rep["overall"] == "warn" and rep["colour"] == "amber" and rep["leaks"] == []
    w = rows(rep)["watch"]
    assert w["status"] == "warn" and "not reviewed" in w["detail"] + w["why"] + json.dumps(w)
    assert set(rep["watch"]) >= {"available", "enabled", "hookInstalled", "lastScan", "lastScanKind",
                                 "lastScanError", "scanning", "inventoryCount", "pendingCount",
                                 "flaggedCount", "unreviewedCount"}
    assert rep["watch"]["enabled"] and rep["watch"]["lastScanKind"] == "full"
    assert rep["watch"]["flaggedCount"] == rep["watch"]["unreviewedCount"] == len(rep["flagged"])
    summary = json.loads((box.state / "summary.json").read_text())
    assert summary["watch"]["flagged"] == summary["watch"]["unreviewed"] == len(rep["flagged"])
    text = (box.state / "summary.json").read_text()
    for secret in ("someapp", "datadog", "sentry", str(box.home)):
        assert secret not in text


def test_the_first_scan_reads_as_expected_rather_than_a_fault(box, capsys):
    machine(box)
    switched_on(box, capsys)
    box.scan(capsys)
    rep = box.status(capsys)
    n = len(rep["flagged"])
    assert n > 1 and all(i["firstScan"] and i["colour"] == "amber" for i in rep["flagged"])
    assert rep["overall"] == "warn" and "watch" not in rep["attention"]
    assert rep["headline"] == f"On, the first scan found {n} items to review"
    w = rows(rep)["watch"]
    assert w["status"] == "ok" and f"The first scan found {n} to review" in w["detail"]
    # Scanned again, the same items keep the mark.
    box.scan(capsys, "--full")
    assert box.status(capsys)["headline"] == f"On, the first scan found {n} items to review"
    # One new item after it turns the status back into a fault.
    box.pkg("latecomer", "1-1", {"usr/bin/latecomer": b"\x00api.segment.io\x00"})
    box.scan(capsys, "--changed")
    rep = box.status(capsys)
    late = [i for i in rep["flagged"] if i["program"] == "latecomer"]
    assert len(late) == 1 and not late[0]["firstScan"]
    assert "watch" in rep["attention"] and "first scan" not in rep["headline"]


def test_a_scan_cut_short_or_pending_is_not_the_whole_first_scan(box, capsys):
    box.pkg("someapp", "1.0-1", {"usr/bin/someapp": b"\x00api.segment.io\x00"})
    run_spool(box, "someapp\n")
    box.scan(capsys, "--pending")
    box.pkg("other", "1-1", {"usr/bin/other": b"\x00api.segment.io\x00"})
    box.scan(capsys, "--changed")
    assert all(i["firstScan"] for i in box.bo.EXT["watch"].flagged(box.ctx, box.bo.API))
    box.pkg("third", "1-1", {"usr/bin/third": b"\x00api.segment.io\x00"})
    box.scan(capsys, "--changed")
    got = {i["program"]: i["firstScan"] for i in box.bo.EXT["watch"].flagged(box.ctx, box.bo.API)}
    assert got == {"someapp": True, "other": True, "third": False}


def test_flagged_items_are_hidden_while_the_row_is_off(box, capsys):
    machine(box)
    box.s.stock_machine()
    box.status(capsys, "on")
    box.scan(capsys)
    rep = box.status(capsys)
    assert rep["flagged"] == [] and rep["overall"] == "ok"


# ---------------------------------------------------------------- reviews

def test_the_review_store_round_trip(box, capsys):
    machine(box)
    switched_on(box, capsys)
    box.scan(capsys)
    item = next(i for i in box.listed(capsys) if i["program"] == "someapp"
                and i["signature"] == "datadog-intake")
    out = box.main(capsys, "review", item["id"], "allow", "--note", 'uses "quotes" \\ and more')
    assert out.strip() == "Marked someapp as allowed."
    store = box.state / "reviewed.toml"
    assert oct(store.stat().st_mode & 0o777) == "0o600"
    import tomllib
    data = tomllib.loads(store.read_text())
    entry = data["items"][item["id"]]
    assert data["schema"] == 1 and entry["verdict"] == "allowed"
    assert entry["program"] == "someapp" and entry["signature"] == "datadog-intake"
    assert entry["note"] == 'uses "quotes" \\ and more'
    rep = box.status(capsys)
    got = next(i for i in rep["flagged"] if i["id"] == item["id"])
    assert got["colour"] == "grey" and got["verdict"] == "allowed" and not got["active"]
    rep = json.loads(box.main(capsys, "review", item["id"], "false-positive", "--status"))
    assert next(i for i in rep["flagged"] if i["id"] == item["id"])["verdict"] == "false-positive"
    box.main(capsys, "review", item["id"], "clear")
    assert item["id"] not in tomllib.loads(store.read_text()).get("items", {})
    assert item["id"] in {i["id"] for i in box.listed(capsys)}


def test_review_refuses_what_it_cannot_do(box, capsys):
    machine(box)
    box.scan(capsys)
    assert box.bo.main(["review", "nothex", "allow"], box.env) == 2
    assert box.bo.main(["review", "0123456789abcdef", "allow"], box.env) == 1
    assert box.bo.main(["review", "0123456789abcdef", "maybe"], box.env) == 2
    assert box.bo.main(["watch", "scan", "--full", "--changed"], box.env) == 2


def test_a_bulk_review_and_the_baseline(box, capsys):
    machine(box)
    switched_on(box, capsys)
    box.scan(capsys)
    n = len(box.listed(capsys))
    assert "--yes" in box.main(capsys, "watch", "baseline")
    assert len(box.listed(capsys)) == n                 # nothing changed without --yes
    rep = json.loads(box.main(capsys, "review", "--all", "allow", "--status"))
    assert all(i["colour"] == "grey" for i in rep["flagged"])
    assert rep["overall"] == "ok" and rows(rep)["watch"]["status"] == "ok"
    assert box.listed(capsys) == [] and len(box.listed(capsys, "--all")) == n
    box.main(capsys, "review", "--all", "false-positive")   # nothing left to review
    assert box.main(capsys, "watch", "baseline", "--yes").strip() == "Marked 0 items as allowed."


def test_the_baseline_accepts_everything_found(box, capsys):
    machine(box)
    box.scan(capsys)
    n = len(box.listed(capsys))
    assert box.main(capsys, "watch", "baseline", "--yes").strip() == f"Marked {n} items as allowed."
    assert box.listed(capsys) == []
    assert box.status(capsys, "watch", "status", "--json")["baselineAt"]


def test_a_later_version_that_adds_a_finding_is_flagged_again(box, capsys):
    box.pkg("someapp", "1.0-1", {"usr/bin/someapp": b"\x00http-intake.logs.x\x00"})
    box.scan(capsys)
    item = box.listed(capsys)[0]
    box.main(capsys, "review", item["id"], "allow")
    # The same version scanned again stays reviewed.
    box.scan(capsys)
    assert box.listed(capsys) == []
    # A later version with nothing new stays reviewed.
    box.pkg("someapp", "1.1-1", {"usr/bin/someapp": b"\x00http-intake.logs.x\x00padding"})
    box.scan(capsys, "--changed")
    assert box.listed(capsys) == []
    # A later version with a new string for that signature is flagged again.
    box.pkg("someapp", "1.2-1", {"usr/bin/someapp": b"\x00http-intake.logs.x\x00browser-intake-datadoghq\x00"})
    out = box.scan(capsys, "--changed")
    assert "flagged again" in out
    assert [i["id"] for i in box.listed(capsys)] == [item["id"]]


def test_a_review_follows_a_program_whose_path_changes(box, capsys):
    base = box.home / ".local/share/mise/installs/vend"
    box.write(base / "1.0/bin/vend", b"\x00VEND_TELEMETRY\x00")
    box.scan(capsys)
    old = box.listed(capsys)[0]
    assert old["program"] == "vend" and old["signature"] == "watch-kill-switch"
    box.main(capsys, "review", old["id"], "allow")
    # Version 2 lives in another folder, so its item has a new id, and it
    # takes the review over because it found nothing new.
    box.write(base / "2.0/bin/vend", b"\x00VEND_TELEMETRY\x00")
    os.symlink(base / "2.0", base / "latest")
    box.scan(capsys, "--changed")
    assert box.listed(capsys) == []
    new = box.listed(capsys, "--all")[0]
    assert new["id"] != old["id"] and new["path"].endswith("2.0/bin/vend")
    # Version 3 adds a switch the review never saw.
    box.write(base / "3.0/bin/vend", b"\x00VEND_TELEMETRY\x00VEND_DISABLE_TELEMETRY\x00")
    (base / "latest").unlink()
    os.symlink(base / "3.0", base / "latest")
    box.scan(capsys, "--changed")
    assert [i["path"] for i in box.listed(capsys)] == [str(base / "3.0/bin/vend")]


def test_a_failed_scan_is_recorded_and_the_row_says_so(box, capsys, monkeypatch):
    machine(box)
    switched_on(box, capsys)

    def boom(*a, **k):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(box.w, "run_scan", boom)
    assert box.bo.main(["watch", "scan", "--changed", "--quiet"], box.env) == 1
    rep = box.status(capsys)
    assert rep["watch"]["lastScanError"].startswith("OSError")
    assert rows(rep)["watch"]["status"] == "warn"
    assert "watch" in rep["attention"]
