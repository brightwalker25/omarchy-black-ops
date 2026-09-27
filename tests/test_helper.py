"""The root helper, system/apply: what it accepts, what it refuses, and what
it writes. Run as the invoking user against the sandbox; nothing here needs
or uses root."""
import os
import subprocess
import sys

import pytest

from conftest import (HAND_HOSTS, HOSTS_01, HOSTS_01_OLLAMA, REPO, STOCK_HOSTS, lan_con,
                      lan_machine, lan_state)

# Verbs 0.1 had. The 0.2 helper refuses them, and the rule no longer names
# them, so after the installer has run once more they stop working.
REMOVED_VERBS = ("ollama-block-on", "ollama-block-off", "ollama-dropin-on",
                 "ollama-dropin-off", "onnx-lock", "onnx-unlock")
DATADOG = "http-intake.logs.us5.datadoghq.com"
NIGHTLOOM_LINES = """\
# onnxruntime telemetry and ComfyUI Sentry, blocked for Nightloom
0.0.0.0 mobile.events.data.microsoft.com
:: mobile.events.data.microsoft.com
0.0.0.0 o4507954455314432.ingest.us.sentry.io
:: o4507954455314432.ingest.us.sentry.io
"""
BLOCK_02 = f"""\
# BEGIN black-ops
# Managed by the Black Ops bar plugin. Switch it off there rather than editing here.
0.0.0.0 {DATADOG}
:: {DATADOG}
# END black-ops
"""


# ------------------------------------------------------------------ verbs

@pytest.mark.parametrize("verb", ["version", "hosts-on", "hosts-off", "dns-on", "dns-off"])
def test_every_verb_is_accepted(helper, verb):
    assert helper.parse_verb(["apply", verb]) == verb


@pytest.mark.parametrize("argv", [
    ["apply"],
    ["apply", ""],
    ["apply", "hosts-on", "hosts-off"],
    ["apply", "hosts-on", "/etc/passwd"],
    ["apply", "/etc/passwd"],
    ["apply", "HOSTS-ON"],
    ["apply", "hosts-on "],
    ["apply", "hosts-on;id"],
    ["apply", "hosts-on\n"],
    ["apply", "../hosts-on"],
    ["apply", "hosts"],
    ["apply", "shell"],
    ["apply", "--help"],
    ["apply", "version", "x"],
    ["apply", "lan-discovery-on", "eth0"],
    ["apply", "lan-discovery-off", "Home Wi-Fi"],
    ["apply", "lan-discovery-on", "224.0.0.0/24"],
    ["apply", "lan-discovery"],
] + [["apply", verb] for verb in REMOVED_VERBS])
def test_anything_else_is_refused(helper, argv):
    with pytest.raises(helper.HelperError):
        helper.parse_verb(argv)


def test_bad_verb_is_refused_before_anything_else(helper, monkeypatch):
    touched = []
    monkeypatch.setattr(helper, "require_root", lambda: touched.append("root"))
    monkeypatch.setattr(helper, "dispatch", lambda *a: touched.append("dispatch"))
    assert helper.main(["apply", "rm -rf /"], {"SUDO_UID": str(os.getuid())}) == 2
    assert touched == []


def test_refuses_without_root(helper):
    # The tests never run as root, so the real check must refuse.
    assert helper.main(["apply", "hosts-on"], {"SUDO_UID": str(os.getuid())}) == 1


def test_version_needs_nothing(helper, capsys, monkeypatch):
    touched = []
    monkeypatch.setattr(helper, "require_root", lambda: touched.append("root"))
    monkeypatch.setattr(helper, "dispatch", lambda *a: touched.append("dispatch"))
    assert helper.main(["apply", "version"], {}) == 0
    assert capsys.readouterr().out == f"version: {helper.HELPER_VERSION}\n"
    assert touched == []


def test_version_matches_the_plugin(helper, bo):
    import json
    manifest = json.loads((REPO / "manifest.json").read_text())
    assert helper.HELPER_VERSION == bo.VERSION == manifest["version"]


def test_refuses_when_run_as_a_script_without_root():
    r = subprocess.run([sys.executable, str(REPO / "system" / "apply"), "hosts-on"],
                       capture_output=True, text=True, env={"PATH": "/usr/bin"})
    assert r.returncode == 1
    assert "root" in r.stderr
    assert r.stdout == ""


# ------------------------------------------------------------ own install

def test_trusts_a_root_owned_system_file(helper):
    helper.check_trusted(os.path.realpath(sys.executable), uid=0)


def test_distrusts_a_file_it_does_not_expect_to_own(helper, tmp_path):
    f = tmp_path / "apply"
    f.write_text("")
    with pytest.raises(helper.HelperError, match="not owned by root"):
        helper.check_trusted(str(f), uid=0)


def test_distrusts_a_file_others_can_write(helper, tmp_path):
    f = tmp_path / "apply"
    f.write_text("")
    f.chmod(0o666)
    with pytest.raises(helper.HelperError, match="writable by others"):
        helper.check_trusted(str(f), uid=os.getuid())


def test_distrusts_a_folder_others_can_write(helper, tmp_path):
    d = tmp_path / "lib"
    d.mkdir()
    d.chmod(0o777)
    f = d / "apply"
    f.write_text("")
    f.chmod(0o755)
    with pytest.raises(helper.HelperError, match="writable by others"):
        helper.check_trusted(str(f), uid=os.getuid())


# ------------------------------------------------------------ hosts edits

def test_migrates_hand_written_lines_into_the_block(helper):
    out = helper.edit_hosts(HAND_HOSTS, True)
    outside, inner = helper.split_block(out)
    assert helper.block_hosts(inner) == {DATADOG}
    assert out.count(f" {DATADOG}\n") == 2
    # Lines for other hosts, written by hand, are not the block's and stay
    # exactly where they were.
    assert out == HAND_HOSTS.replace(f"0.0.0.0 {DATADOG}\n:: {DATADOG}\n", "") + "\n" + BLOCK_02


def test_hosts_on_is_idempotent(helper):
    for start in (STOCK_HOSTS, HAND_HOSTS, HOSTS_01, HOSTS_01_OLLAMA):
        once = helper.edit_hosts(start, True)
        assert helper.edit_hosts(once, True) == once, start


def test_hosts_off_leaves_the_stock_file(helper):
    assert helper.edit_hosts(helper.edit_hosts(STOCK_HOSTS, True), False) == STOCK_HOSTS
    assert helper.edit_hosts(STOCK_HOSTS, False) == STOCK_HOSTS


def test_hosts_on_rewrites_a_01_block_to_hold_only_datadog(helper):
    out = helper.edit_hosts(HOSTS_01, True)
    assert out == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES + "\n" + BLOCK_02
    _, inner = helper.split_block(out)
    assert helper.block_hosts(inner) == {DATADOG}


def test_ollama_lines_in_a_01_block_move_out_as_well(helper):
    out = helper.edit_hosts(HOSTS_01_OLLAMA, True)
    assert out == (STOCK_HOSTS + "\n" + NIGHTLOOM_LINES +
                   "# ollama.com, blocked for Nightloom\n0.0.0.0 ollama.com\n:: ollama.com\n"
                   "\n" + BLOCK_02)


@pytest.mark.parametrize("start", [HOSTS_01, HOSTS_01_OLLAMA])
def test_hosts_off_never_removes_the_microsoft_or_sentry_lines(helper, start):
    # Straight from a 0.1 block, and after 0.2 has rewritten it: either way
    # only the Datadog pair and the markers go.
    for text in (start, helper.edit_hosts(start, True)):
        out = helper.edit_hosts(text, False)
        assert "# BEGIN black-ops" not in out and "# END black-ops" not in out
        assert DATADOG not in out
        assert out.startswith(STOCK_HOSTS + "\n" + NIGHTLOOM_LINES)
        for host in ("mobile.events.data.microsoft.com", "o4507954455314432.ingest.us.sentry.io"):
            assert f"0.0.0.0 {host}\n" in out and f":: {host}\n" in out
        assert ("ollama.com" in out) == (start is HOSTS_01_OLLAMA)
        assert helper.edit_hosts(out, False) == out


def test_hosts_off_keeps_plain_microsoft_and_sentry_lines(helper):
    text = STOCK_HOSTS + "\n" + NIGHTLOOM_LINES
    assert helper.edit_hosts(text, False) == text
    assert helper.edit_hosts(helper.edit_hosts(text, True), False) == text


def test_lines_already_outside_the_block_are_not_repeated(helper):
    # Nightloom's setup appended its own plain lines after 0.1 had put the
    # same hosts in the block.
    text = HOSTS_01 + "0.0.0.0 mobile.events.data.microsoft.com\n:: mobile.events.data.microsoft.com\n"
    out = helper.edit_hosts(text, True)
    for host in ("mobile.events.data.microsoft.com", "o4507954455314432.ingest.us.sentry.io"):
        assert out.count(f"0.0.0.0 {host}\n") == 1 and out.count(f":: {host}\n") == 1


def test_other_lines_inside_the_block_are_kept(helper):
    text = STOCK_HOSTS + "\n" + helper.BEGIN + "\n0.0.0.0 tracker.example\n:: tracker.example\n" + \
        "192.168.1.5 nas\n" + helper.END + "\n"
    out = helper.edit_hosts(text, False)
    assert out == STOCK_HOSTS + "\n0.0.0.0 tracker.example\n:: tracker.example\n192.168.1.5 nas\n"


def test_lines_that_are_not_exactly_ours_are_kept(helper):
    text = STOCK_HOSTS + f"0.0.0.0 {DATADOG} other.example  # mine\n"
    out = helper.edit_hosts(text, False)
    assert "other.example" in out


def test_a_damaged_block_is_refused(helper):
    with pytest.raises(helper.HelperError, match="damaged"):
        helper.edit_hosts(STOCK_HOSTS + helper.BEGIN + "\n0.0.0.0 x\n", True)


# ------------------------------------------------------ writing, in a sandbox

def call(sandbox, verb):
    env = dict(sandbox.env)
    return subprocess.run([str(sandbox.bin / "sudo"), "-n", str(sandbox.helper), verb],
                          capture_output=True, text=True, env=env)


def test_hosts_on_writes_and_flushes(sandbox):
    sandbox.write(sandbox.hosts, HAND_HOSTS)
    r = call(sandbox, "hosts-on")
    assert r.returncode == 0, r.stderr
    assert "# BEGIN black-ops" in sandbox.hosts.read_text()
    assert sandbox.calls("resolvectl") == ["resolvectl flush-caches"]
    sandbox.clear_calls()
    assert call(sandbox, "hosts-on").stdout.strip() == "hosts-on: unchanged"
    assert sandbox.calls("resolvectl") == []


def test_refuses_to_write_through_a_linked_hosts_file(sandbox):
    victim = sandbox.root / "victim"
    victim.write_text("keep me\n")
    sandbox.hosts.symlink_to(victim)
    r = call(sandbox, "hosts-on")
    assert r.returncode == 1
    assert victim.read_text() == "keep me\n"
    assert sandbox.hosts.is_symlink()


def test_refuses_a_linked_folder(sandbox):
    import shutil
    real = sandbox.root / "elsewhere"
    real.mkdir()
    shutil.rmtree(sandbox.etc / "systemd")
    (sandbox.etc / "systemd").symlink_to(real, target_is_directory=True)
    r = call(sandbox, "dns-on")
    assert r.returncode == 1
    assert list(real.iterdir()) == []


def test_dns_dropin_is_written_and_removed(sandbox):
    assert call(sandbox, "dns-on").returncode == 0
    assert "FallbackDNS=\n" in sandbox.dns_dropin.read_text()
    assert sandbox.calls("systemctl") == ["systemctl restart systemd-resolved.service"]
    assert call(sandbox, "dns-on").stdout.strip() == "dns-on: unchanged"
    sandbox.clear_calls()
    assert call(sandbox, "dns-off").returncode == 0
    assert not sandbox.dns_dropin.exists()
    assert not sandbox.dns_dropin.parent.exists()
    assert sandbox.calls("systemctl") == ["systemctl restart systemd-resolved.service"]


def test_version_through_sudo(sandbox):
    r = call(sandbox, "version")
    assert r.returncode == 0 and r.stdout == "version: 0.4.0\n"


@pytest.mark.parametrize("verb", REMOVED_VERBS)
def test_removed_verbs_stop_working_after_reinstalling(sandbox, helper, verb):
    sandbox.hand_machine()
    before = sandbox.snapshot()
    r = call(sandbox, verb)
    assert r.returncode != 0
    assert "password is required" in r.stderr     # the new rule does not name it
    assert sandbox.snapshot() == before
    # And the new helper refuses it on its own, whatever sudo allows.
    assert helper.main(["apply", verb], {}) == 2


# ------------------------------------------------------ LAN discovery verbs

WIRED = "11111111-2222-4333-8444-555555555555"
WIFI = "66666666-7777-4888-9999-aaaaaaaaaaaa"
ENDPOINT = "203.0.113.7/32 192.168.1.1"


def routes_of(sandbox, uuid):
    return next(c["routes"] for c in lan_state(sandbox)["connections"] if c["uuid"] == uuid)


def no_bounce(sandbox):
    for c in sandbox.calls("nmcli "):
        assert not any(w in c.split() for w in ("up", "down", "reapply")), c


@pytest.mark.parametrize("verb", ["lan-discovery-on", "lan-discovery-off"])
def test_lan_discovery_verbs_are_accepted(helper, verb):
    assert helper.parse_verb(["apply", verb]) == verb


def test_lan_discovery_on_is_idempotent_and_leaves_other_routes(sandbox):
    lan_machine(sandbox, [lan_con(WIRED, "802-3-ethernet", "eth0", routes=[ENDPOINT]),
                          lan_con(WIFI, "802-11-wireless", "wlan0"),
                          lan_con("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff", "wireguard", "wg0",
                                  routes=["10.2.0.0/16"])])
    r = call(sandbox, "lan-discovery-on")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "lan-discovery-on: changed"
    assert routes_of(sandbox, WIRED) == [ENDPOINT, "224.0.0.0/24"]
    assert routes_of(sandbox, WIFI) == ["224.0.0.0/24"]
    assert routes_of(sandbox, "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff") == ["10.2.0.0/16"]
    assert sorted(lan_state(sandbox)["live"], key=lambda r: r["dev"]) == [
        {"dev": "eth0", "metric": "100"}, {"dev": "wlan0", "metric": "600"}]
    sandbox.clear_calls()
    r = call(sandbox, "lan-discovery-on")
    assert r.stdout.strip() == "lan-discovery-on: unchanged"
    assert not [c for c in sandbox.calls("nmcli ") if " modify " in c]
    assert not [c for c in sandbox.calls("ip ") if " replace " in c]
    no_bounce(sandbox)


def test_lan_discovery_on_never_replaces_another_devices_route(sandbox):
    lan_machine(sandbox, [lan_con(WIRED, "802-3-ethernet", "eth0"),
                          lan_con(WIFI, "802-11-wireless", "wlan0")],
                metrics={"eth0": "100", "wlan0": "100"})
    assert call(sandbox, "lan-discovery-on").returncode == 0
    live = sorted(lan_state(sandbox)["live"], key=lambda r: r["dev"])
    assert live == [{"dev": "eth0", "metric": "100"}, {"dev": "wlan0", "metric": "101"}]


def test_lan_discovery_off_removes_only_its_route(sandbox):
    lan_machine(sandbox, [
        lan_con(WIRED, "802-3-ethernet", "eth0", routes=[ENDPOINT, "224.0.0.0/24"]),
        # A saved Wi-Fi network that is not connected now.
        lan_con(WIFI, "802-11-wireless", "wlan0", active=False, routes=["224.0.0.0/24"]),
        # A route to the same network through a gateway is someone else's.
        lan_con("22222222-2222-4333-8444-555555555555", "802-3-ethernet", "eth1",
                routes=["224.0.0.0/24 192.168.1.1"])],
        live=[{"dev": "eth0", "metric": "100"}])
    r = call(sandbox, "lan-discovery-off")
    assert r.returncode == 0, r.stderr
    assert routes_of(sandbox, WIRED) == [ENDPOINT]
    assert routes_of(sandbox, WIFI) == []
    assert routes_of(sandbox, "22222222-2222-4333-8444-555555555555") == ["224.0.0.0/24 192.168.1.1"]
    assert lan_state(sandbox)["live"] == []
    assert call(sandbox, "lan-discovery-off").stdout.strip() == "lan-discovery-off: unchanged"
    no_bounce(sandbox)


@pytest.mark.parametrize("line", [
    "11111111-2222-4333-8444-555555555555:802-3-ethernet:-eth0",
    "11111111-2222-4333-8444-555555555555:802-3-ethernet:eth0 metric 1",
    "11111111-2222-4333-8444-555555555555:802-3-ethernet:eth0:extra",
    "--help:802-3-ethernet:eth0",
    "11111111-2222-4333-8444-555555555555:vpn:eth0",
])
def test_lan_discovery_checks_what_nmcli_reports(sandbox, line):
    con = lan_con(WIRED, "802-3-ethernet", "eth0")
    con["line"] = line
    lan_machine(sandbox, [con])
    r = call(sandbox, "lan-discovery-on")
    assert r.returncode == 1 and "no Ethernet or Wi-Fi connection is active" in r.stderr
    assert routes_of(sandbox, WIRED) == [] and lan_state(sandbox)["live"] == []
    assert not [c for c in sandbox.calls("nmcli ") if " modify " in c]
    assert sandbox.calls("ip ") == []


def test_lan_discovery_needs_networkmanager(sandbox):
    r = call(sandbox, "lan-discovery-on")
    assert r.returncode == 1 and "not installed" in r.stderr
    assert call(sandbox, "lan-discovery-off").stdout.strip() == "lan-discovery-off: unchanged"
