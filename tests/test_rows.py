"""The rows added in 0.3.0, the colour rule, the Omarchy version check, rows.d
and the hooks for the extensions, against the sandbox.

The stub commands here keep their state in small files in the sandbox, so a
change one of them makes can be read back by the next call, as with the real
bluetoothctl, systemctl, gh, mise and fwupdmgr."""
import json
import os
import sys

import pytest

from conftest import STOCK_HOSTS

PY = sys.executable

STUB_BLUETOOTHCTL = """#!{py}
import json, os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
path = os.path.join(root, "bt.json")
st = json.load(open(path))
args = [a for a in sys.argv[1:]]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("bluetoothctl " + " ".join(args) + "\\n")
if args[:1] == ["--timeout"]:
    args = args[2:]
if args == ["show"]:
    print("Controller 00:00:00:00:00:00 (public)")
    print("\\tName: " + st["name"])
    print("\\tAlias: " + st["alias"])
    print("\\tPairable: " + ("yes" if st["pairable"] else "no"))
elif args[:1] == ["pairable"]:
    st["pairable"] = args[1] == "on"
elif args[:1] == ["system-alias"]:
    st["alias"] = args[1]
elif args == ["reset-alias"]:
    st["alias"] = st["name"]
json.dump(st, open(path, "w"))
"""

STUB_SYSTEMCTL = """#!{py}
import json, os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
home = os.environ.get("HOME", "")
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("systemctl " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
units = os.path.join(home, ".config/systemd/user")
envf = os.path.join(root, "session-env")
def env():
    try:
        return [l for l in open(envf).read().splitlines() if l]
    except OSError:
        return []
if args[:2] == ["--user", "mask"]:
    os.makedirs(units, exist_ok=True)
    os.symlink("/dev/null", os.path.join(units, args[-1]))
elif args[:2] == ["--user", "unmask"]:
    p = os.path.join(units, args[-1])
    if os.path.islink(p):
        os.unlink(p)
elif args[:2] == ["--user", "show-environment"]:
    print("\\n".join(env()))
elif args[:2] == ["--user", "unset-environment"]:
    names = tuple(a + "=" for a in args[2:])
    open(envf, "w").write("\\n".join(l for l in env() if not l.startswith(names)) + "\\n")
elif args[:2] == ["--user", "set-environment"]:
    names = tuple(a.split("=", 1)[0] + "=" for a in args[2:])
    open(envf, "w").write("\\n".join([l for l in env() if not l.startswith(names)] + args[2:]) + "\\n")
elif args[:3] == ["is-active", "--quiet", "fwupd.service"]:
    sys.exit(0 if os.path.exists(os.path.join(root, "fwupd-active")) else 3)
elif args[:2] == ["--user", "is-active"]:
    sys.exit(3)
elif args[:1] == ["mask"]:
    for unit in args[2:]:
        os.symlink("/dev/null", os.path.join(root, "etc/systemd/system", unit))
elif args[:1] == ["unmask"]:
    for unit in args[1:]:
        p = os.path.join(root, "etc/systemd/system", unit)
        if os.path.islink(p):
            os.unlink(p)
elif args[:3] == ["is-active", "--quiet", "avahi-daemon.service"]:
    sys.exit(3 if os.path.islink(os.path.join(root, "etc/systemd/system", args[2])) else 0)
elif args == ["try-restart", "bluetooth.service"]:
    # BlueZ makes the adapter pairable again when it starts it.
    path = os.path.join(root, "bt.json")
    st = json.load(open(path))
    st["pairable"] = True
    json.dump(st, open(path, "w"))
sys.exit(0)
"""

STUB_BTMGMT = """#!{py}
import os
root = os.environ["BLACK_OPS_FAKE_ROOT"]
print("hci0:\\tPrimary controller")
print("\\tcurrent settings: " + open(os.path.join(root, "bt-settings")).read().strip())
"""

STUB_GH = """#!{py}
import os, re, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("gh " + " ".join(sys.argv[1:]) + "\\n")
path = os.path.join(os.environ["HOME"], ".config/gh/config.yml")
args = sys.argv[1:]
if args[:3] == ["config", "set", "telemetry"]:
    text = open(path).read() if os.path.exists(path) else "version: 1\\n"
    if re.search(r"^telemetry:", text, re.M):
        text = re.sub(r"^telemetry:.*$", "telemetry: " + args[3], text, flags=re.M)
    else:
        text += "telemetry: " + args[3] + "\\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(text)
"""

STUB_MISE = """#!{py}
import json, os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("mise " + " ".join(sys.argv[1:]) + "\\n")
path = os.path.join(root, "mise.json")
st = json.load(open(path)) if os.path.exists(path) else {{}}
args = sys.argv[1:]
if args[:2] == ["settings", "get"]:
    print(st.get(args[2], "true"))
elif args[:2] == ["settings", "set"]:
    st[args[2]] = args[3]
elif args[:2] == ["settings", "unset"]:
    st.pop(args[2], None)
json.dump(st, open(path, "w"))
"""

STUB_FWUPDMGR = """#!{py}
import json, os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
conf = os.path.join(root, "etc/fwupd/fwupd.conf")
text = open(conf).read() if os.path.exists(conf) else ""
flags = 1 if "\\nP2pPolicy=nothing" in text else 17
print(json.dumps({{"Remotes": [{{"Id": "lvfs", "Flags": flags}},
                             {{"Id": "lvfs-testing", "Flags": 16}}]}}))
"""

STUB_NMCLI = """#!{py}
import os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("nmcli " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:4] == ["-t", "-f", "UUID,TYPE", "connection"]:
    print("1a7a46a7-979b-4d14-b0b3-5c9615ee1ac5:802-11-wireless")
    print("c0d1e10b-9b38-4688-87b9-e5c0b957ed2f:loopback")
elif args[:1] == ["-g"]:
    try:
        print(open(os.path.join(root, "nm-profile")).read(), end="")
    except OSError:
        print("-1\\n-1\\n-1\\n")
"""

STUB_BUSCTL = """#!{py}
import os
root = os.environ["BLACK_OPS_FAKE_ROOT"]
print(open(os.path.join(root, "nm-runtime")).read().strip())
"""

STUB_TRUE = "#!/bin/sh\nexit 0\n"

NM_PRIVACY = "[connection]\nipv6.ip6-privacy=2\nwifi.cloned-mac-address=stable\n"

AVAHI_CONF = """\
[server]
use-ipv4=yes
use-ipv6=yes

[publish]
#disable-user-service-publishing=no
#add-service-cookie=no
#publish-addresses=yes
publish-hinfo=no
publish-workstation=no

[reflector]
"""

UFW_LAN = """\
*filter
### RULES ###

### tuple ### allow any 53317 0.0.0.0/0 any 192.168.0.0/16 in comment=6c6f63616c73656e64204c414e
-A ufw-user-input -p tcp --dport 53317 -s 192.168.0.0/16 -j ACCEPT

### END RULES ###
"""
UFW_STOCK = """\
*filter
### RULES ###

### tuple ### allow udp 53317 0.0.0.0/0 any 0.0.0.0/0 in
-A ufw-user-input -p udp --dport 53317 -j ACCEPT

### tuple ### allow tcp 53317 0.0.0.0/0 any 0.0.0.0/0 in
-A ufw-user-input -p tcp --dport 53317 -j ACCEPT

### END RULES ###
"""

CODEX = """\
# my codex settings
model = "gpt-5"

[profiles.fast]
model = "gpt-5-mini"   # keep this
"""

GROK = """\
[ui]
yolo = false

[features]
# experimental bits
fancy = true
"""

FWUPD_CONF = "[fwupd]\n# use `man 5 fwupd.conf` for documentation\n"

WEBAPP = "[Desktop Entry]\nVersion=1.0\nName=YouTube\nExec=omarchy-launch-webapp https://youtube.com/\nTerminal=false\n"

NPMRC = "registry=https://registry.npmjs.org/\nfund=true\naudit=true\n"

# The part of Omarchy's ~/.config/nvim/lua/config/lazy.lua around the checker.
LAZY = """\
require("lazy").setup({
  spec = {
    { "LazyVim/LazyVim", import = "lazyvim.plugins" },
    { import = "plugins" },
  },
  defaults = {
    lazy = false,
    version = false, -- always use the latest commit
  },
  install = { colorscheme = { "tokyonight", "habamax" } },
  checker = {
    enabled = true, -- check for plugin updates periodically
    notify = false, -- notify on update
  }, -- automatically check for plugin updates
  performance = {
    rtp = {
      disabled_plugins = {
        "gzip",
        "tarPlugin",
      },
    },
  },
})
"""


def rows(rep):
    return {r["id"]: r for r in rep["rows"]}


@pytest.fixture
def box(sandbox):
    """The sandbox with the stubs these rows need."""
    for name, text in (("bluetoothctl", STUB_BLUETOOTHCTL), ("systemctl", STUB_SYSTEMCTL),
                       ("gh", STUB_GH), ("mise", STUB_MISE), ("fwupdmgr", STUB_FWUPDMGR),
                       ("nmcli", STUB_NMCLI), ("busctl", STUB_BUSCTL)):
        sandbox.stub(name, text.format(py=PY))
    for name in ("chromium", "ufw"):
        sandbox.stub(name, STUB_TRUE)
    (sandbox.root / "bt.json").write_text(json.dumps(
        {"pairable": True, "alias": "myhost", "name": "myhost"}))
    (sandbox.root / "nm-runtime").write_text("b true\n")
    sandbox.write(sandbox.hosts, STOCK_HOSTS)
    return sandbox


def bluetooth(box):
    (box.root / "sys/class/bluetooth/hci0").mkdir(parents=True)


def bt(box):
    return json.loads((box.root / "bt.json").read_text())


# ------------------------------------------------------------- Bluetooth

def test_bluetooth_on_and_off(box, run):
    bluetooth(box)
    rep = run("on")
    r = rows(rep)["bluetooth"]
    assert r["status"] == "ok", r
    assert bt(box) == {"pairable": False, "alias": "laptop", "name": "myhost"}
    assert (box.home / ".config/systemd/user/black-ops-bluetooth.service").is_file()
    assert rep["canPair"] is True
    rep = run("off")
    assert bt(box)["alias"] == "myhost"
    assert not (box.home / ".config/systemd/user/black-ops-bluetooth.service").exists()
    assert "bluetoothctl --timeout 10 reset-alias" in box.calls("bluetoothctl")


def test_bluetooth_pairable_again_after_a_restart_is_healed(box, run):
    bluetooth(box)
    run("on")
    st = bt(box)
    st["pairable"] = True
    (box.root / "bt.json").write_text(json.dumps(st))
    rep = run("status")
    assert rows(rep)["bluetooth"]["status"] == "warn"
    assert rep["slipped"] == ["bluetooth"]
    run("status", "--heal")
    assert bt(box)["pairable"] is False


def test_the_pair_window_opens_and_counts_down(box, run):
    bluetooth(box)
    run("on")
    rep = run("pair")
    assert bt(box)["pairable"] is True
    r = rows(rep)["bluetooth"]
    assert r["status"] == "ok" and r["value"].startswith("open for pairing")
    assert 0 < rep["pairSecondsLeft"] <= 60


# --------------------------------------------------------- NetworkManager

def test_identity_adds_what_99_privacy_leaves_out(box, run):
    conf = box.etc / "NetworkManager/conf.d"
    box.write(conf / "99-privacy.conf", NM_PRIVACY)
    rep = run("status")
    assert rows(rep)["identity"]["value"] == "2 of 5 set"
    rep = run("on")
    assert rows(rep)["identity"]["status"] == "ok", rows(rep)["identity"]
    assert "identity-on" in box.helper_verbs()
    assert "ipv4.dhcp-send-hostname=0" in (conf / "90-black-ops-identity.conf").read_text()
    run("off")
    assert not (conf / "90-black-ops-identity.conf").exists()
    assert (conf / "99-privacy.conf").read_text() == NM_PRIVACY


def test_a_profile_that_sends_the_host_name_itself_is_amber(box, run):
    box.write(box.etc / "NetworkManager/conf.d/99-privacy.conf", NM_PRIVACY)
    run("on")
    (box.root / "nm-profile").write_text("yes\n-1\n-1\n\n")
    r = rows(run("status"))["identity"]
    assert r["status"] == "warn" and r["colour"] == "amber"
    assert "1 connection profile sets" in r["why"]
    # The profile's name is never shown.
    assert "1a7a46a7" not in json.dumps(r)


def test_connectivity_check_off_over_dbus_is_adopted(box, run):
    (box.etc / "NetworkManager").mkdir(parents=True)
    box.write(box.root / "usr/lib/NetworkManager/conf.d/20-connectivity.conf",
              "[connectivity]\nuri=http://ping.archlinux.org/nm-check.txt\n")
    (box.root / "nm-runtime").write_text("b false\n")
    rep = run("on")
    r = rows(rep)["connectivity"]
    assert r["status"] == "ok" and r["value"] == "off, set over D-Bus"
    assert "connectivity-on" not in box.helper_verbs()
    assert box.state()["rows"]["connectivity"]["how"] == "adopted"


# ----------------------------------------------------------- Chromium, Avahi

def test_chromium_policy_sits_beside_omarchys_own(box, run):
    policies = box.etc / "chromium/policies/managed"
    box.write(policies / "color.json", '{"BrowserThemeColor": "#1e1e2e"}\n')
    rep = run("on")
    assert rows(rep)["chromium"]["status"] == "ok"
    ours = json.loads((policies / "black-ops.json").read_text())
    assert ours["SearchSuggestEnabled"] is False and ours["BlockThirdPartyCookies"] is True
    assert "SafeBrowsingProtectionLevel" not in ours
    run("off")
    assert sorted(os.listdir(policies)) == ["color.json"]


def test_avahi_publishing_goes_off_and_back_byte_for_byte(box, run):
    box.write(box.etc / "avahi/avahi-daemon.conf", AVAHI_CONF)
    rep = run("on")
    assert rows(rep)["avahi"]["status"] == "ok"
    text = (box.etc / "avahi/avahi-daemon.conf").read_text()
    assert "\ndisable-publishing=yes\n" in text
    run("off")
    assert (box.etc / "avahi/avahi-daemon.conf").read_text() == AVAHI_CONF


# ------------------------------------------------------------- LocalSend

def test_localsend_limited_to_the_lan_by_hand_is_left_alone(box, run):
    box.write(box.etc / "ufw/user.rules", UFW_LAN)
    box.write(box.etc / "ufw/user6.rules", "")
    r = rows(run("status"))["localsend"]
    assert r["status"] == "na" and r["value"] == "your own rule"


def test_localsend_stock_rule_is_optional(box, run):
    box.write(box.etc / "ufw/user.rules", UFW_STOCK)
    box.write(box.etc / "ufw/user6.rules", "")
    rep = run("on")
    assert rows(rep)["localsend"]["status"] == "off"
    assert "localsend-close" not in box.helper_verbs()
    rep = run("row", "localsend", "on")
    assert "localsend-close" in box.helper_verbs()


# -------------------------------------------------------------- web apps

def test_web_apps_get_a_profile_each_and_come_back(box, run):
    app = box.home / ".local/share/applications/YouTube.desktop"
    box.write(app, WEBAPP)
    rep = run("on")
    assert rows(rep)["webapps"]["status"] == "ok"
    text = app.read_text()
    assert "Exec=" + str(box.home / ".local/share/omarchy-black-ops/bin/black-ops-webapp") in text
    assert "X-Black-Ops-Exec=omarchy-launch-webapp https://youtube.com/" in text
    assert "keyboard shortcuts" in rows(rep)["webapps"]["detail"]
    run("off")
    assert app.read_text() == WEBAPP
    assert not (box.home / ".local/share/omarchy-black-ops").exists()


# -------------------------------------------------- developer tool telemetry

def dev_tools(box, codex=CODEX, grok=GROK):
    box.stub("npm", STUB_TRUE)
    if codex is not None:
        box.write(box.home / ".codex/config.toml", codex)
    if grok is not None:
        box.write(box.home / ".grok/config.toml", grok)


def test_dev_telemetry_edits_only_its_own_keys(box, run):
    dev_tools(box)
    rep = run("on")
    r = rows(rep)["dev-telemetry"]
    assert r["status"] == "ok", r
    assert r["value"] == "5 of 5 off"
    assert "update notifier" in r["detail"]
    codex = (box.home / ".codex/config.toml").read_text()
    assert codex == CODEX + "\n[analytics]\nenabled = false\n"
    grok = (box.home / ".grok/config.toml").read_text()
    assert grok == ("[ui]\nyolo = false\n\n[features]\n# experimental bits\nfancy = true\n"
                    "telemetry = false\n\n[telemetry]\ntrace_upload = false\n")
    assert "telemetry: disabled" in (box.home / ".config/gh/config.yml").read_text()
    assert json.loads((box.root / "mise.json").read_text())["use_versions_host"] == "false"
    rec = box.state()["rows"]["dev-telemetry"]
    assert set(rec["tools"]) == {"gh", "codex", "grok", "mise", "npm"}
    assert (box.home / ".npmrc").read_text() == "update-notifier=false\nfund=false\n"
    assert oct((box.home / ".npmrc").stat().st_mode & 0o777) == "0o600"
    run("off")
    assert (box.home / ".codex/config.toml").read_text() == CODEX
    assert (box.home / ".grok/config.toml").read_text() == GROK
    assert "telemetry: enabled" in (box.home / ".config/gh/config.yml").read_text()
    assert "use_versions_host" not in json.loads((box.root / "mise.json").read_text())
    assert not (box.home / ".npmrc").exists()


def test_dev_telemetry_set_by_hand_is_adopted_not_rewritten(box, run):
    codex = "[analytics]\nenabled = false\n"
    grok = "[features]\ntelemetry = false\n\n[telemetry]\ntrace_upload = false\n"
    dev_tools(box, codex, grok)
    box.write(box.home / ".config/gh/config.yml", "version: 1\ntelemetry: disabled\n")
    (box.root / "mise.json").write_text('{"use_versions_host": "false"}')
    box.write(box.home / ".npmrc", "fund = false\nupdate-notifier=false\n")
    box.clear_calls()
    rep = run("on")
    assert rows(rep)["dev-telemetry"]["status"] == "ok"
    assert box.state()["rows"]["dev-telemetry"]["how"] == "adopted"
    assert box.calls("gh ") == [] and [c for c in box.calls("mise ") if " set " in c] == []
    assert (box.home / ".codex/config.toml").read_text() == codex
    assert (box.home / ".npmrc").read_text() == "fund = false\nupdate-notifier=false\n"


def test_npmrc_keeps_its_other_lines_and_comes_back_byte_for_byte(box, run):
    dev_tools(box)
    box.write(box.home / ".npmrc", NPMRC)
    rep = run("on")
    assert rows(rep)["dev-telemetry"]["status"] == "ok"
    # fund is changed where it stands, the notifier is added, audit is kept.
    assert (box.home / ".npmrc").read_text() == (
        "registry=https://registry.npmjs.org/\nfund=false\naudit=true\nupdate-notifier=false\n")
    run("off")
    assert (box.home / ".npmrc").read_text() == NPMRC


def test_npm_not_installed_is_left_out(box, run):
    dev_tools(box)
    (box.bin / "npm").unlink()
    r = rows(run("on"))["dev-telemetry"]
    assert r["status"] == "ok" and r["value"] == "4 of 4 off"
    assert not (box.home / ".npmrc").exists()


# ------------------------------------------------ Neovim's update checker

def lazy_lua(box, text=LAZY):
    path = box.home / ".config/nvim/lua/config/lazy.lua"
    box.write(path, text)
    return path


def test_nvim_checker_changes_only_the_enabled_value(box, run):
    path = lazy_lua(box)
    assert rows(run("status"))["nvim-checker"]["value"] == "checking for updates"
    rep = run("on")
    r = rows(rep)["nvim-checker"]
    assert r["status"] == "ok" and r["value"] == "off"
    assert path.read_text() == LAZY.replace(
        "enabled = true, -- check", "enabled = false, -- check")
    run("off")
    assert path.read_text() == LAZY


def test_nvim_checker_off_by_hand_is_adopted(box, run):
    text = LAZY.replace("enabled = true", "enabled = false")
    path = lazy_lua(box, text)
    run("on")
    assert box.state()["rows"]["nvim-checker"]["how"] == "adopted"
    run("off")
    assert path.read_text() == text


def test_nvim_checker_without_lazy_lua_is_not_applicable(box, run):
    r = rows(run("on"))["nvim-checker"]
    assert r["status"] == "na"
    assert not (box.home / ".config/nvim").exists()


@pytest.mark.parametrize("text", [
    LAZY.replace("enabled = true,", "enabled = vim.g.check_updates,"),
    LAZY.replace("  checker = {\n    enabled = true, -- check for plugin updates periodically\n"
                 "    notify = false, -- notify on update\n  }, -- automatically check for plugin updates\n", ""),
    LAZY.replace("notify = false,", "notify = false, enabled = true,"),
])
def test_a_restructured_lazy_lua_is_amber_and_left_alone(box, run, text):
    path = lazy_lua(box, text)
    rep = run("on")
    r = rows(rep)["nvim-checker"]
    assert r["status"] == "warn" and "left alone" in r["why"]
    assert path.read_text() == text
    run("off")
    assert path.read_text() == text


# ------------------------------------------------------ opt-out variables

def test_opt_out_variables_row(box, run):
    box.stub("uwsm", STUB_TRUE)
    rep = run("on")
    r = rows(rep)["opt-out-env"]
    assert r["status"] == "ok" and r["value"] == "set", r
    assert "next login" in r["detail"]
    dropin = box.home / ".config/uwsm/env.d/90-black-ops-opt-out"
    text = dropin.read_text()
    assert text.startswith("# Written by the Black Ops bar plugin")
    for line in ("export DO_NOT_TRACK=1\n", "export DENO_NO_UPDATE_CHECK=1\n",
                 "export AZURE_CORE_COLLECT_TELEMETRY=0\n", "export HINT_TELEMETRY=off\n"):
        assert line in text
    assert "DO_NOT_TRACK=1" in (box.root / "session-env").read_text()
    run("off")
    assert not dropin.exists() and not (box.home / ".config/uwsm").exists()
    assert "DO_NOT_TRACK" not in (box.root / "session-env").read_text()


def test_opt_out_variables_set_by_hand_are_adopted(box, run, bo):
    box.stub("uwsm", STUB_TRUE)
    session = "".join(f"{k}={v}\n" for k, v in bo.OPT_OUT_VARS)
    (box.root / "session-env").write_text(session)
    rep = run("on")
    assert rows(rep)["opt-out-env"]["value"] == "set by hand"
    assert box.state()["rows"]["opt-out-env"]["how"] == "adopted"
    assert not (box.home / ".config/uwsm").exists()
    run("off")
    assert (box.root / "session-env").read_text() == session


def test_opt_out_variables_need_uwsm(box, run):
    r = rows(run("on"))["opt-out-env"]
    assert r["status"] == "na"
    assert not (box.home / ".config/uwsm").exists()


def test_dev_telemetry_needs_nothing_installed_to_be_skipped(box, run):
    for name in ("gh", "mise"):
        (box.bin / name).unlink()
    r = rows(run("on"))["dev-telemetry"]
    assert r["status"] == "na"


def test_a_codex_config_that_is_not_toml_is_left_alone(box, run):
    dev_tools(box, codex="this is = = not toml\n", grok=None)
    rep = run("on")
    r = rows(rep)["dev-telemetry"]
    assert r["status"] == "warn"
    assert (box.home / ".codex/config.toml").read_text() == "this is = = not toml\n"


def test_toml_set_changes_an_existing_line_and_puts_it_back(bo):
    text = "[analytics]\nenabled = true  # on\nother = 1\n"
    new, info = bo.toml_set(text, "analytics", "enabled", "false")
    assert new == "[analytics]\nenabled = false\nother = 1\n"
    assert bo.toml_unset(new, "analytics", "enabled", "false", info) == text


def test_toml_set_refuses_a_key_it_cannot_place_cleanly(bo):
    with pytest.raises(bo.ActionError):
        bo.toml_set("analytics = { enabled = true }\n", "analytics", "enabled", "false")


# ----------------------------------------------------------- optional rows

def optional_machine(box):
    box.write(box.etc / "debuginfod/archlinux.urls", "https://debuginfod.archlinux.org\n")
    (box.root / "session-env").write_text("DEBUGINFOD_URLS=$'https://debuginfod.archlinux.org '\n")
    box.write(box.root / "usr/lib/systemd/user/omarchy-crash-watch.service", "[Service]\n")
    box.write(box.etc / "fwupd/fwupd.conf", FWUPD_CONF)
    (box.root / "fwupd-active").write_text("")


def test_the_main_switch_never_turns_optional_rows_on(box, run):
    optional_machine(box)
    rep = run("on")
    r = rows(rep)
    for row_id in ("debuginfod", "crash-watch", "fwupd-p2p", "update-badge", "claude-usage"):
        assert r[row_id]["intended"] is False, row_id
        assert r[row_id]["colour"] == "grey", row_id
    assert not (box.home / ".config/uwsm").exists()
    assert "fwupd-p2p-on" not in box.helper_verbs()
    assert (box.etc / "fwupd/fwupd.conf").read_text() == FWUPD_CONF


def test_debuginfod_row(box, run):
    optional_machine(box)
    run("on")
    rep = run("row", "debuginfod", "on")
    dropin = box.home / ".config/uwsm/env.d/90-black-ops-debuginfod"
    assert "export DEBUGINFOD_URLS=\n" in dropin.read_text()
    r = rows(rep)["debuginfod"]
    assert r["status"] == "ok" and r["value"] == "off"
    run("row", "debuginfod", "off")
    assert not dropin.exists() and not (box.home / ".config/uwsm").exists()
    assert "DEBUGINFOD_URLS=https://debuginfod.archlinux.org" in (box.root / "session-env").read_text()


def test_debuginfod_still_set_in_the_session_waits_for_a_login(box, run):
    optional_machine(box)
    run("on")
    run("row", "debuginfod", "on")
    (box.root / "session-env").write_text("DEBUGINFOD_URLS=https://debuginfod.archlinux.org\n")
    r = rows(run("status"))["debuginfod"]
    assert r["status"] == "warn" and "next login" in r["why"]


def test_crash_watch_row_masks_and_unmasks(box, run):
    optional_machine(box)
    run("on")
    rep = run("row", "crash-watch", "on")
    link = box.home / ".config/systemd/user/omarchy-crash-watch.service"
    assert os.readlink(link) == "/dev/null"
    assert rows(rep)["crash-watch"]["status"] == "ok"
    run("row", "crash-watch", "off")
    assert not link.is_symlink()
    assert "systemctl --user start omarchy-crash-watch.service" in box.calls("systemctl")


def test_crash_watch_off_by_omarchys_toggle_is_adopted(box, run):
    optional_machine(box)
    box.write(box.home / ".local/state/omarchy/toggles/crash-capture-off", "")
    run("on")
    rep = run("row", "crash-watch", "on")
    r = rows(rep)["crash-watch"]
    assert r["status"] == "ok" and r["value"] == "off by Omarchy's toggle"
    assert not (box.home / ".config/systemd/user/omarchy-crash-watch.service").exists()


def test_fwupd_peer_sharing_row(box, run):
    optional_machine(box)
    run("on")
    assert rows(run("status"))["fwupd-p2p"]["value"] == "sharing metadata"
    rep = run("row", "fwupd-p2p", "on")
    assert "fwupd-p2p-on" in box.helper_verbs()
    text = (box.etc / "fwupd/fwupd.conf").read_text()
    assert "\nP2pPolicy=nothing\n" in text
    assert rows(rep)["fwupd-p2p"]["status"] == "ok"
    assert "systemctl try-restart fwupd.service" in box.calls("systemctl")
    run("row", "fwupd-p2p", "off")
    assert (box.etc / "fwupd/fwupd.conf").read_text() == FWUPD_CONF


def agents(box):
    doc = json.loads(box.shell_json.read_text())
    return [e for e in doc["bar"]["layout"]["right"] if e["id"] == "omarchy.agents"][0]["providers"]


def test_claude_usage_row_turns_claude_off_and_back(box, run):
    box.stock_machine()
    claude_before = box.claude.read_bytes()
    rep = run("on")
    assert agents(box)["claude"] == {"enabled": True}
    assert rows(rep)["claude-usage"]["intended"] is False
    rep = run("row", "claude-usage", "on")
    r = rows(rep)
    assert r["claude-usage"]["status"] == "ok" and r["claude-usage"]["value"] == "off"
    assert "no longer shows Claude usage" in r["claude-usage"]["detail"]
    assert agents(box) == {"claude": {"enabled": False}, "codex": {"enabled": False},
                           "fireworks": {"enabled": False}}
    # The Agents row does not count Claude being off against itself.
    assert r["agents"]["status"] == "ok", r["agents"]
    run("row", "claude-usage", "off")
    assert agents(box)["claude"] == {"enabled": True}
    assert rows(run("status"))["agents"]["status"] == "ok"
    # Only the bar's settings change; Claude Code's own are not touched.
    assert json.loads(box.claude.read_text())["model"] == "opus"
    run("off")
    assert box.claude.read_bytes() == claude_before


def test_the_agents_row_leaves_claude_to_the_usage_row(box, run):
    box.stock_machine()
    run("on")
    run("row", "claude-usage", "on")
    run("on")                              # everything engaged again
    assert agents(box)["claude"] == {"enabled": False}
    run("row", "agents", "off")
    assert agents(box) == {"claude": {"enabled": False}, "codex": {"enabled": True},
                           "fireworks": {"enabled": True}}
    run("row", "agents", "on")
    assert agents(box)["claude"] == {"enabled": False}
    run("off")
    assert all(p["enabled"] for p in agents(box).values())


def test_claude_off_by_hand_is_adopted_and_left_off(box, run):
    box.stock_machine()
    run("on")
    doc = json.loads(box.shell_json.read_text())
    doc["bar"]["layout"]["right"][1]["providers"]["claude"]["enabled"] = False
    box.write(box.shell_json, json.dumps(doc, indent=2) + "\n")
    run("row", "claude-usage", "on")
    assert box.state()["rows"]["claude-usage"]["how"] == "adopted"
    run("row", "claude-usage", "off")
    assert agents(box)["claude"] == {"enabled": False}


def test_fwupd_edit_comments_out_a_policy_and_puts_it_back(helper):
    text = "[fwupd]\nP2pPolicy=metadata,firmware\nIdleTimeout=7200\n"
    on = helper.fwupd_edit(text, True)
    assert "#black-ops-was: P2pPolicy=metadata,firmware" in on
    assert "\nP2pPolicy=nothing\n" in on
    assert helper.fwupd_edit(on, True) == on
    assert helper.fwupd_edit(on, False) == text
    added = helper.fwupd_edit("", True)
    assert "[fwupd]" in added and helper.fwupd_edit(added, False) == ""


def test_the_new_verbs_are_accepted(helper):
    for verb in ("fwupd-p2p-on", "fwupd-p2p-off", "identity-on", "localsend-close"):
        assert helper.parse_verb(["apply", verb]) == verb


# ------------------------------------------------------ added in 0.4.0

BT_MAIN_CONF = """\
[General]

# Default adapter name
#Name = BlueZ

# Defaults to "off"
#Privacy = off

# Specify the policy to the JUST-WORKS repairing initiated by peer
#JustWorksRepairing = never

[Policy]
#AutoEnable=true
"""


def old_chromium_policy(helper):
    """black-ops.json as 0.3.0 wrote it, before EnableMediaRouter."""
    helper.CHROMIUM_POLICIES = tuple(p for p in helper.CHROMIUM_POLICIES
                                     if p[0] != "EnableMediaRouter")
    return helper.chromium_policy()


def test_chromium_turns_off_cast_discovery(box, run):
    run("on")
    ours = json.loads((box.etc / "chromium/policies/managed/black-ops.json").read_text())
    assert ours["EnableMediaRouter"] is False
    assert rows(run("status"))["chromium"]["detail"].startswith("Casting from Chromium stops working")


def test_a_0_3_chromium_policy_is_not_applied_yet_rather_than_slipped(box, run, helper):
    run("on")
    policy = box.etc / "chromium/policies/managed/black-ops.json"
    policy.write_text(old_chromium_policy(helper))
    rep = run("status")
    assert rep["slipped"] == [] and rep["unapplied"] == ["chromium"]
    assert rows(rep)["chromium"]["colour"] == "amber"
    assert "Cast devices" in rows(rep)["chromium"]["why"]
    rep = run("on")
    assert rows(rep)["chromium"]["status"] == "ok"
    assert json.loads(policy.read_text())["EnableMediaRouter"] is False


def test_a_chromium_policy_changed_by_hand_has_still_slipped(box, run):
    run("on")
    policy = box.etc / "chromium/policies/managed/black-ops.json"
    data = json.loads(policy.read_text())
    data["SearchSuggestEnabled"] = True
    del data["EnableMediaRouter"]
    policy.write_text(json.dumps(data))
    rep = run("status")
    assert rep["slipped"] == ["chromium"] and rep["unapplied"] == []


def test_the_chromium_policies_agree(bo, helper):
    assert bo.CHROMIUM_POLICIES == helper.CHROMIUM_POLICIES


def test_bluetooth_address_goes_private_and_back_byte_for_byte(box, run):
    bluetooth(box)
    conf = box.etc / "bluetooth/main.conf"
    box.write(conf, BT_MAIN_CONF)
    assert rows(run("status"))["bt-privacy"]["value"] == "fixed address"
    run("on")
    rep = run("row", "bt-privacy", "on")
    r = rows(rep)["bt-privacy"]
    assert r["status"] == "ok", r
    assert "bt-privacy-on" in box.helper_verbs()
    text = conf.read_text()
    assert "#Privacy = off\n# black-ops: set by the Black Ops bar plugin" in text
    assert "\nPrivacy=device\n" in text
    # bluetoothd restarted, which made the adapter pairable, and the
    # pairing row's service put that right at once.
    assert "systemctl try-restart bluetooth.service" in box.calls("systemctl")
    assert "systemctl --user start black-ops-bluetooth.service" in box.calls("systemctl")
    assert bt(box)["pairable"] is False
    assert rows(rep)["bluetooth"]["status"] == "ok"
    run("off")
    assert conf.read_text() == BT_MAIN_CONF


def test_bluetooth_address_alone_leaves_pairing_to_bluez(box, run):
    bluetooth(box)
    box.write(box.etc / "bluetooth/main.conf", BT_MAIN_CONF)
    run("on")
    run("row", "bluetooth", "off")
    run("row", "bt-privacy", "off")
    box.clear_calls()
    run("row", "bt-privacy", "on")
    assert "systemctl --user start black-ops-bluetooth.service" not in box.calls("systemctl")


def test_bluetooth_address_set_by_hand_is_adopted(box, run):
    bluetooth(box)
    conf = BT_MAIN_CONF.replace("#Privacy = off", "Privacy = network")
    box.write(box.etc / "bluetooth/main.conf", conf)
    run("on")
    rep = run("row", "bt-privacy", "on")
    r = rows(rep)["bt-privacy"]
    assert r["status"] == "ok" and r["value"] == "private address, by hand"
    assert "bt-privacy-on" not in box.helper_verbs()
    assert box.state()["rows"]["bt-privacy"]["how"] == "adopted"


def test_bluetooth_address_not_yet_in_effect_is_amber(box, run):
    bluetooth(box)
    box.write(box.etc / "bluetooth/main.conf", BT_MAIN_CONF)
    box.stub("btmgmt", STUB_BTMGMT.format(py=PY))
    (box.root / "bt-settings").write_text("powered ssp br/edr le secure-conn ll-privacy\n")
    run("on")
    run("row", "bt-privacy", "on")
    r = rows(run("status"))["bt-privacy"]
    assert r["status"] == "warn" and "has not restarted" in r["why"]
    (box.root / "bt-settings").write_text("powered ssp br/edr le secure-conn privacy\n")
    assert rows(run("status"))["bt-privacy"]["status"] == "ok"


def test_bluetooth_address_is_optional(box, run):
    bluetooth(box)
    box.write(box.etc / "bluetooth/main.conf", BT_MAIN_CONF)
    assert rows(run("on"))["bt-privacy"]["status"] == "off"
    assert "bt-privacy-on" not in box.helper_verbs()


def test_bluetooth_address_needs_an_adapter(box, run):
    box.write(box.etc / "bluetooth/main.conf", BT_MAIN_CONF)
    assert rows(run("on"))["bt-privacy"]["status"] == "na"
    assert "bt-privacy-on" not in box.helper_verbs()


def test_bt_privacy_edit_comments_out_a_setting_and_puts_it_back(helper):
    stock = BT_MAIN_CONF.replace("#Privacy = off", "Privacy = off")
    on = helper.bt_privacy_edit(stock, True)
    assert "#black-ops-was: Privacy = off\n" in on and "\nPrivacy=device\n" in on
    assert helper.bt_privacy_edit(on, True) == on
    assert helper.bt_privacy_edit(on, False) == stock
    assert helper.bt_privacy_edit(helper.bt_privacy_edit(BT_MAIN_CONF, True), False) == BT_MAIN_CONF
    added = helper.bt_privacy_edit("[Policy]\nAutoEnable=true\n", True)
    assert "[General]\n" in added
    assert helper.bt_privacy_edit(added, False) == "[Policy]\nAutoEnable=true\n"


def avahi_installed(box):
    box.write(box.root / "usr/lib/systemd/system/avahi-daemon.service", "[Service]\n")
    box.write(box.etc / "avahi/avahi-daemon.conf", AVAHI_CONF)


def test_the_avahi_daemon_row_is_optional_and_masks_both_units(box, run):
    avahi_installed(box)
    units = box.etc / "systemd/system"
    rep = run("on")
    r = rows(rep)["avahi-daemon"]
    assert r["intended"] is False and r["colour"] == "grey" and r["value"] == "listening"
    assert "avahi-mask" not in box.helper_verbs()
    rep = run("row", "avahi-daemon", "on")
    assert "systemctl mask --now avahi-daemon.socket avahi-daemon.service" in box.calls("systemctl")
    for unit in ("avahi-daemon.socket", "avahi-daemon.service"):
        assert os.readlink(units / unit) == "/dev/null"
    assert rows(rep)["avahi-daemon"]["status"] == "ok"
    # The publishing row it overlaps with stays green.
    assert rows(rep)["avahi"]["status"] == "ok"
    assert rep["colour"] == "green"
    box.clear_calls()
    run("row", "avahi-daemon", "off")
    assert not (units / "avahi-daemon.service").is_symlink()
    assert "systemctl unmask avahi-daemon.socket avahi-daemon.service" in box.calls("systemctl")
    assert "systemctl start avahi-daemon.socket" in box.calls("systemctl")
    run("off")
    assert (box.etc / "avahi/avahi-daemon.conf").read_text() == AVAHI_CONF


def test_avahi_publishing_is_not_applicable_while_the_daemon_is_masked(box, run):
    avahi_installed(box)
    for unit in ("avahi-daemon.socket", "avahi-daemon.service"):
        os.symlink("/dev/null", box.etc / "systemd/system" / unit)
    rep = run("on")
    assert rows(rep)["avahi"]["status"] == "na"
    assert rep["unapplied"] == [] and rep["slipped"] == []
    assert rows(rep)["avahi-daemon"]["value"] == "stopped, by hand"
    rep = run("row", "avahi-daemon", "on")
    assert rows(rep)["avahi-daemon"]["status"] == "ok"
    assert "avahi-mask" not in box.helper_verbs()
    assert box.state()["rows"]["avahi-daemon"]["how"] == "adopted"


def test_one_masked_avahi_unit_is_not_enough(box, run):
    avahi_installed(box)
    os.symlink("/dev/null", box.etc / "systemd/system/avahi-daemon.service")
    run("on")
    run("row", "avahi-daemon", "on")
    assert "avahi-mask" in box.helper_verbs()
    assert rows(run("status"))["avahi-daemon"]["status"] == "ok"


def test_the_avahi_daemon_row_needs_avahi(box, run):
    rep = run("on")
    assert rows(rep)["avahi-daemon"]["status"] == "na"


def test_the_0_4_verbs_are_accepted_and_in_the_rule(helper):
    import subprocess
    from conftest import REPO
    rule = subprocess.run(["bash", str(REPO / "bin" / "black-ops-install"), "--print-sudoers",
                           "alice"], capture_output=True, text=True, check=True,
                          env={"PATH": "/usr/bin:/bin"}).stdout
    for verb in ("bt-privacy-on", "bt-privacy-off", "avahi-mask", "avahi-unmask"):
        assert helper.parse_verb(["apply", verb]) == verb
        assert f"/usr/local/lib/omarchy-black-ops/apply {verb}" in rule


def test_avahi_mask_refuses_without_avahi(helper, monkeypatch, tmp_path):
    monkeypatch.setattr(helper, "AVAHI_UNIT_FILE", str(tmp_path / "missing.service"))
    with pytest.raises(helper.HelperError, match="not installed"):
        helper.avahi_mask()


# ------------------------------------------------------ the colour rule

def test_there_is_no_red_for_a_protection(bo, box, run):
    assert set(bo.COLOURS.values()) == {"green", "amber", "red", "grey"}
    assert [k for k, v in bo.COLOURS.items() if v == "red"] == ["leak"]
    run("on")
    box.dns_dropin.unlink()
    rep = run("status")
    assert rep["colour"] == "amber" and rows(rep)["dns"]["colour"] == "amber"
    assert "red" not in json.dumps([r["colour"] for r in rep["rows"]])


def test_a_new_row_is_not_applied_yet_rather_than_slipped(box, run):
    run("on")
    st = box.state()
    st["rows"].pop("dns")
    box.write(box.state_file, json.dumps(st))
    box.dns_dropin.unlink()
    rep = run("status")
    assert rep["slipped"] == [] and rep["unapplied"] == ["dns"]
    assert rep["headline"] == "On, but DNS fallback servers is not applied yet"
    assert rows(rep)["dns"]["colour"] == "amber"




def fake_listen(bo, items):
    """A listen extension that reports `items`."""
    class Row(bo.Row):
        id = "listen"
        label = "Listen mode"
        optional = True
        privileged = False

        def check(self, ctx, rec=None):
            return bo.result("in", "listening", "")

        def apply(self, ctx, chk, rec):
            pass

        def revert(self, ctx, rec):
            pass

    class Ext:
        @staticmethod
        def flagged(ctx, api):
            return [dict(i) for i in items]

        @staticmethod
        def report(ctx, api):
            return {"enabled": True, "unknownCount": 3, "retentionHours": 72}

    row = Row()
    bo.ROWS.append(row)
    bo.BY_ID["listen"] = row
    bo.EXT["listen"] = Ext


LEAK = {"id": "0123456789abcdef", "source": "listen", "kind": "contact", "severity": "leak",
        "program": "someapp", "host": "http-intake.logs.us5.datadoghq.com",
        "signature": "datadog-intake", "summary": "Contacted a Datadog intake host.",
        "firstSeen": 1790000000, "lastSeen": 1790000500, "count": 4}


def test_a_confirmed_contact_is_red_and_wins(bo, box, run):
    fake_listen(bo, [LEAK])
    run("on")
    box.dns_dropin.unlink()          # an amber problem as well
    rep = run("row", "listen", "on")
    assert rep["overall"] == "leak" and rep["colour"] == "red"
    assert rep["headline"] == "On, but someapp contacted a telemetry host"
    item = rep["flagged"][0]
    assert item["colour"] == "red" and item["active"] and item["host"] == LEAK["host"]
    run("status", "--notify")
    notes = box.calls("notify-send")
    assert any("Black Ops, red: someapp contacted a telemetry host" in n for n in notes)
    assert not any(LEAK["host"] in n for n in notes)


def test_red_needs_listen_mode_and_a_host(bo, box, run):
    watch_leak = dict(LEAK, host=None, kind="static")
    fake_listen(bo, [watch_leak])
    run("on")
    rep = run("row", "listen", "on")
    assert rep["flagged"][0]["colour"] == "amber"
    assert rep["overall"] == "warn"


def test_a_reviewed_item_turns_grey(bo, box, run):
    fake_listen(bo, [LEAK])
    run("on")
    run("row", "listen", "on")
    box.write(box.home / ".local/state/black-ops/reviewed.toml",
              f'schema = 1\n\n[items."{LEAK["id"]}"]\nverdict = "allowed"\nat = 1790000600\n')
    rep = run("status")
    assert rep["flagged"][0]["colour"] == "grey" and rep["overall"] == "ok"


def test_listen_items_are_ignored_while_listen_is_off(bo, box, run):
    fake_listen(bo, [LEAK])
    rep = run("on")
    assert rep["flagged"] == [] and rep["overall"] == "ok"


def test_the_summary_holds_counts_and_no_names(bo, box, run):
    fake_listen(bo, [LEAK])
    run("on")
    run("row", "listen", "on")
    path = box.home / ".local/state/black-ops/summary.json"
    text = path.read_text()
    data = json.loads(text)
    assert data["schema"] == 1 and data["overall"] == "leak" and data["colour"] == "red"
    assert data["listen"] == {"enabled": True, "leaks": 1, "unknownHosts": 3, "retentionHours": 72}
    for secret in ("datadoghq", "someapp", "datadog-intake", str(box.home)):
        assert secret not in text
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_extensions_are_reported_as_unavailable_until_built(bo, run, box, monkeypatch):
    # As if neither module were there.
    monkeypatch.setitem(bo.EXT, "watch", None)
    monkeypatch.setitem(bo.EXT, "listen", None)
    rep = run("status")
    assert rep["watch"]["available"] is False and rep["listen"]["available"] is False


def test_watch_and_listen_commands_say_they_are_not_built(bo, box, capsys, monkeypatch):
    monkeypatch.setitem(bo.EXT, "watch", None)
    monkeypatch.setitem(bo.EXT, "listen", None)
    assert bo.main(["watch", "list"], box.env) == 2
    assert "not part of this version" in capsys.readouterr().err


# ------------------------------------------------------ the Omarchy version

def omarchy(box, version):
    d = box.root / "pacman" / f"omarchy-{version}"
    for old in (box.root / "pacman").glob("omarchy-*") if (box.root / "pacman").exists() else []:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    box.write(d / "desc", f"%NAME%\nomarchy\n\n%VERSION%\n{version}\n\n")


def test_the_omarchy_version_is_recorded_on_switching_on(box, run):
    omarchy(box, "4.0.4-1")
    rep = run("on")
    assert box.state()["omarchy"]["version"] == "4.0.4-1"
    assert rep["omarchy"] == {"version": "4.0.4-1", "recorded": "4.0.4-1", "changed": False}


def test_the_recorded_version_does_not_rewrite_the_state_on_every_check(box, run):
    omarchy(box, "4.0.4-1")
    run("on")
    before = box.state_file.read_bytes()
    run("status", "--notify")
    run("on")
    assert box.state_file.read_bytes() == before


def test_an_omarchy_update_is_checked_strictly(box, run):
    omarchy(box, "4.0.4-1")
    run("on")
    omarchy(box, "4.0.5-1")
    box.dns_dropin.unlink()          # the update brought a default back
    rep = run("status")
    assert rep["omarchy"]["changed"] is True
    assert rep["headline"].endswith("since the Omarchy update to 4.0.5-1")
    assert rows(rep)["dns"]["why"].startswith("Since Omarchy was updated to 4.0.5-1.")
    # Not the baseline until every row holds against it.
    assert box.state()["omarchy"]["version"] == "4.0.4-1"
    run("on")
    rep = run("status")
    assert rep["omarchy"]["changed"] is False and rep["overall"] == "ok"
    assert box.state()["omarchy"]["version"] == "4.0.5-1"


def test_an_update_with_everything_holding_is_recorded_at_once(box, run):
    omarchy(box, "4.0.4-1")
    run("on")
    omarchy(box, "4.0.5-1")
    rep = run("status")
    assert rep["headline"].endswith("after the Omarchy update to 4.0.5-1")
    assert box.state()["omarchy"]["version"] == "4.0.5-1"
    assert run("status")["omarchy"]["changed"] is False


# ------------------------------------------------------------------ rows.d

NIGHTLOOM = {
    "schema": 1,
    "stack": "nightloom",
    "rows": [
        {"id": "ollama-block", "label": "ollama.com block",
         "about": "Sinks ollama.com in /etc/hosts.",
         "applies": {"file": "~/AI", "exists": True},
         "check": {"hosts": ["ollama.com"]}},
        {"id": "no-cloud", "label": "Ollama cloud features",
         "check": {"file": "~/AI/ollama-offline.conf",
                   "contains": "Environment=OLLAMA_NO_CLOUD=1"}},
        {"id": "comfy", "label": "ComfyUI settings",
         "check": {"all": [{"json": "~/AI/comfy.json", "key": "a.b", "equals": False},
                           {"toml": "~/AI/c.toml", "key": "x.y", "equals": 1}]}},
    ],
}


def rows_d(box, name, doc, mode=0o644):
    d = box.home / ".config/omarchy-black-ops/rows.d"
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o755)
    p = d / name
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    p.chmod(mode)
    return p


def test_rows_d_rows_report_without_a_switch(box, run):
    rows_d(box, "nightloom.json", NIGHTLOOM)
    box.write(box.home / "AI/comfy.json", '{"a": {"b": false}}')
    box.write(box.home / "AI/c.toml", "[x]\ny = 1\n")
    box.write(box.hosts, STOCK_HOSTS + "0.0.0.0 ollama.com\n:: ollama.com\n")
    rep = run("on")
    r = rows(rep)
    assert r["nightloom/ollama-block"]["status"] == "ok"
    assert r["nightloom/ollama-block"]["registered"] is True
    assert r["nightloom/ollama-block"]["switchable"] is False
    assert r["nightloom/comfy"]["status"] == "ok"
    no_cloud = r["nightloom/no-cloud"]
    assert no_cloud["status"] == "warn" and no_cloud["colour"] == "amber"
    assert "Put it back in nightloom." in no_cloud["why"]
    assert run("row", "nightloom/no-cloud", "on")["error"].startswith("Rows other stacks")
    assert "nightloom/no-cloud" not in box.state()["rows"]


def test_rows_d_rows_are_grey_while_off(box, run):
    rows_d(box, "nightloom.json", NIGHTLOOM)
    rep = run("status")
    assert all(r["colour"] == "grey" for r in rep["rows"] if r["registered"])


@pytest.mark.parametrize("doc,why", [
    ("not json", "not valid JSON"),
    (dict(NIGHTLOOM, schema=2), "schema must be 1"),
    (dict(NIGHTLOOM, stack="other"), "matching the file name"),
    (dict(NIGHTLOOM, rows=[{"id": "x", "label": "X", "check": {"command": ["curl", "x"]}}]),
     "exactly one of"),
    (dict(NIGHTLOOM, rows=[{"id": "x", "label": "X", "check": {"file": "relative", "exists": True}}]),
     "must start with"),
    (dict(NIGHTLOOM, rows=[{"id": "x", "label": "X", "check": {"file": "~/../etc", "exists": True}}]),
     "may not contain"),
])
def test_rows_d_files_that_are_not_valid_are_skipped(box, run, doc, why):
    rows_d(box, "nightloom.json", doc)
    rep = run("status")
    assert not any(r["registered"] for r in rep["rows"])
    assert rep["rowsD"]["skipped"][0]["file"] == "nightloom.json"
    assert why in rep["rowsD"]["skipped"][0]["why"]


def test_rows_d_files_others_can_write_are_skipped(box, run):
    rows_d(box, "nightloom.json", NIGHTLOOM, mode=0o666)
    rep = run("status")
    assert not any(r["registered"] for r in rep["rows"])
    assert "writable by others" in rep["rowsD"]["skipped"][0]["why"]


def test_rows_d_cannot_take_a_black_ops_name(box, run):
    rows_d(box, "dns.json", dict(NIGHTLOOM, stack="dns"))
    assert "clashes" in run("status")["rowsD"]["skipped"][0]["why"]


def test_an_extension_command_can_print_the_status(bo, box, capsys):
    class Ext:
        @staticmethod
        def cli(ctx, api, argv):
            assert argv[:2] == ["review", "0123456789abcdef"]
            print(json.dumps(api.current_report(ctx)))
            return 0
    bo.EXT["watch"] = Ext
    assert bo.main(["review", "0123456789abcdef", "allow", "--status"], box.env) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["overall"] == "off"
    assert (box.home / ".local/state/black-ops/summary.json").is_file()
