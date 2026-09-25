"""bin/black-ops against a sandboxed machine: adoption, switching on and off,
the watchdog, and the file edits it makes as the user."""
import json
import os
import socket

from conftest import HAND_HOSTS, STOCK_HOSTS

DATADOG = "http-intake.logs.us5.datadoghq.com"
# The rows every machine in these tests has. The others have nothing to
# protect in the sandbox unless a test sets it up, and read as not applicable.
ROW_IDS = ["weather", "agents", "dns", "claude", "hosts"]
ALL_ROWS = ROW_IDS + ["bluetooth", "identity", "chromium", "connectivity", "avahi", "webapps",
                      "dev-telemetry", "nvim-checker", "opt-out-env", "update-badge", "herdr",
                      "localsend", "debuginfod", "crash-watch", "fwupd-p2p", "avahi-daemon",
                      "bt-privacy", "claude-usage", "watch"]
# Optional rows that are off, never not applicable, on any machine. Listen
# mode is not applicable until the installer has put its service in place.
# The Claude usage check is off rather than not applicable wherever the
# Agents widget is on the bar, as it is on these machines.
NEVER_NA = ("watch", "claude-usage")


def rows(rep):
    return {r["id"]: r for r in rep["rows"]}


def hand_hosts_without_datadog():
    return HAND_HOSTS.replace(f"0.0.0.0 {DATADOG}\n:: {DATADOG}\n", "")


# ---------------------------------------------------------------- adoption

def test_the_rows_are_the_stock_omarchy_ones(run, sandbox):
    sandbox.stock_machine()
    rep = run("status")
    # Listen mode adds its optional row at the end.
    assert [r["id"] for r in rep["rows"] if r["id"] != "listen"] == ALL_ROWS
    assert all(r["status"] == "na" for r in rep["rows"] if r["id"] not in ROW_IDS + list(NEVER_NA))
    assert all(r["status"] == "off" for r in rep["rows"] if r["id"] in NEVER_NA)


def test_status_reads_a_hand_made_machine_without_writing(sandbox, run):
    sandbox.hand_machine()
    before = sandbox.snapshot()
    rep = run("status")
    r = rows(rep)
    assert rep["master"] is False and rep["overall"] == "off"
    # Off never claims a stock machine when protections are in place by hand.
    assert rep["headline"] == "Off, not managing. 5 protections are in place by hand"
    for row_id in ROW_IDS:
        assert r[row_id]["inPlace"], row_id
    assert r["hosts"]["value"] == "blocked by hand"
    assert sandbox.snapshot() == before
    assert not sandbox.state_file.parent.exists()
    assert sandbox.helper_verbs() == []


def test_on_adopts_what_is_already_in_place(sandbox, run):
    sandbox.hand_machine()
    before = sandbox.snapshot()
    rep = run("on")
    # The only privileged call is the one that moves the hand-written hosts
    # lines into the marked block. Nothing already in place is applied again.
    assert sandbox.helper_verbs() == ["hosts-on"]
    assert rep["overall"] == "ok", rep
    how = {k: v["how"] for k, v in sandbox.state()["rows"].items()}
    assert how == {k: "adopted" for k in ROW_IDS}
    after = sandbox.snapshot()
    changed = {p for p in before if before[p] != after.get(p)}
    assert changed == {str(sandbox.hosts)}


def test_hand_written_lines_move_into_the_block(sandbox, run):
    sandbox.hand_machine()
    run("on")
    text = sandbox.hosts.read_text()
    # The Datadog pair moves into the block. The Microsoft and Sentry lines
    # are not Black Ops's, and stay where they were, with their comments.
    assert text.startswith(hand_hosts_without_datadog())
    body = text[len(hand_hosts_without_datadog()):]
    assert body == ("\n# BEGIN black-ops\n"
                    "# Managed by the Black Ops bar plugin. Switch it off there rather than editing here.\n"
                    f"0.0.0.0 {DATADOG}\n:: {DATADOG}\n# END black-ops\n")
    assert text.count(DATADOG) == 2
    assert rows(run("status"))["hosts"]["value"] == "blocked"


def test_on_is_idempotent(sandbox, run):
    sandbox.stock_machine()
    first = run("on")
    assert first["overall"] == "ok", first
    state = sandbox.state_file.read_bytes()
    before = sandbox.snapshot()
    sandbox.clear_calls()
    second = run("on")
    assert second["overall"] == "ok"
    assert sandbox.helper_verbs() == []
    assert sandbox.snapshot() == before
    assert sandbox.state_file.read_bytes() == state


# ------------------------------------------------------------- on and off

def test_on_then_off_on_a_stock_machine(sandbox, run):
    sandbox.stock_machine()
    untouched = [sandbox.proton, sandbox.onnx / "device.id", sandbox.webui_db]
    untouched_before = [p.read_bytes() for p in untouched]
    claude_before = sandbox.claude.read_bytes()
    shell_before = sandbox.shell_json.read_bytes()
    rep = run("on")
    assert rep["overall"] == "ok", rep
    assert sorted(sandbox.helper_verbs()) == ["dns-on", "hosts-on"]
    assert f"0.0.0.0 {DATADOG}\n" in sandbox.hosts.read_text()
    assert "FallbackDNS=\n" in sandbox.dns_dropin.read_text()
    w = json.loads(sandbox.weather.read_text())
    assert (w["latitude"], w["longitude"], w["name"]) == (48.8568, 2.3071, "Somewhere")

    rep = run("off")
    assert rep["overall"] == "off", rep
    assert sandbox.hosts.read_text() == STOCK_HOSTS
    assert not sandbox.dns_dropin.exists()
    assert not sandbox.dns_dropin.parent.exists()
    assert sandbox.claude.read_bytes() == claude_before
    # Off sets every agent back to enabled, which is what an entry without
    # a providers object means, and leaves the rest of shell.json as it was.
    after = json.loads(sandbox.shell_json.read_text())
    entry = after["bar"]["layout"]["right"][1]
    assert entry.pop("providers") == {n: {"enabled": True} for n in ("claude", "codex", "fireworks")}
    assert after == json.loads(shell_before)
    # One-way: the precision does not come back, and the panel says so.
    w = json.loads(sandbox.weather.read_text())
    assert (w["latitude"], w["longitude"]) == (48.8568, 2.3071)
    assert "does not restore" in rows(rep)["weather"]["detail"]
    assert sandbox.state()["rows"] == {}
    # Apps Black Ops does not manage were never touched.
    assert [p.read_bytes() for p in untouched] == untouched_before


def test_off_after_adopting_leaves_only_what_is_not_black_opss(sandbox, run):
    sandbox.hand_machine()
    run("on")
    rep = run("off")
    assert rep["overall"] == "off", rep
    assert sandbox.hosts.read_text() == hand_hosts_without_datadog()
    assert "0.0.0.0 mobile.events.data.microsoft.com\n" in sandbox.hosts.read_text()
    assert not sandbox.dns_dropin.exists()
    assert sandbox.ollama_dropin.exists()
    assert sandbox.is_immutable(sandbox.onnx)
    env = json.loads(sandbox.claude.read_text()).get("env", {})
    assert "DISABLE_TELEMETRY" not in env and "DISABLE_ERROR_REPORTING" not in env
    providers = [e for e in json.loads(sandbox.shell_json.read_text())["bar"]["layout"]["right"]
                 if e["id"] == "omarchy.agents"][0]["providers"]
    assert all(p["enabled"] for p in providers.values())


def test_off_reverts_only_what_was_applied(sandbox, run):
    sandbox.stock_machine()
    run("on")
    run("row", "claude", "off")          # taken out while on
    assert "claude" not in sandbox.state()["rows"]
    assert "claude" in sandbox.state()["excluded"]

    # Afterwards the user makes a change of their own that happens to match.
    data = json.loads(sandbox.claude.read_text())
    data["env"]["DISABLE_TELEMETRY"] = "1"
    sandbox.claude.write_text(json.dumps(data, indent=2) + "\n")
    claude_mine = sandbox.claude.read_bytes()

    sandbox.clear_calls()
    run("off")
    assert sandbox.claude.read_bytes() == claude_mine
    assert sandbox.hosts.read_text() == STOCK_HOSTS


def test_a_row_can_be_switched_back_on(sandbox, run):
    sandbox.stock_machine()
    run("on")
    run("row", "claude", "off")
    assert "DISABLE_TELEMETRY" not in json.loads(sandbox.claude.read_text())["env"]
    rep = run("row", "claude", "on")
    assert json.loads(sandbox.claude.read_text())["env"]["DISABLE_TELEMETRY"] == "1"
    assert rows(rep)["claude"]["status"] == "ok"


def test_rows_cannot_be_switched_on_while_off(sandbox, run):
    sandbox.stock_machine()
    rep = run("row", "claude", "on")
    assert "first" in rep["error"]
    assert "DISABLE_TELEMETRY" not in json.loads(sandbox.claude.read_text())["env"]


def test_removed_rows_are_no_longer_switchable(sandbox, run):
    sandbox.stock_machine()
    run("on")
    for row_id in ("onnx", "ollama-offline", "ollama-block", "openwebui", "proton"):
        assert run("row", row_id, "on")["error"] == f"no such row: {row_id}"


# --------------------------------------------------------------- watchdog

def test_a_slip_turns_the_report_amber_and_notifies_once(sandbox, run):
    sandbox.stock_machine()
    run("on")
    sandbox.dns_dropin.unlink()          # an update removes the drop-in
    rep = run("status", "--notify")
    assert rep["overall"] == "warn"
    assert rep["slipped"] == ["dns"]
    assert rows(rep)["dns"]["status"] == "warn"
    notes = sandbox.calls("notify-send")
    assert len(notes) == 1 and "DNS fallback servers has slipped" in notes[0]
    run("status", "--notify")
    assert len(sandbox.calls("notify-send")) == 1
    run("on")                            # put back
    assert run("status", "--notify")["overall"] == "ok"
    sandbox.dns_dropin.unlink()
    run("status", "--notify")
    assert len(sandbox.calls("notify-send")) == 2


def test_no_notifications_while_off(sandbox, run):
    sandbox.stock_machine()
    rep = run("status", "--notify")
    assert rep["overall"] == "off"
    assert sandbox.calls("notify-send") == []


def test_status_does_not_touch_the_network(sandbox, run, monkeypatch):
    sandbox.hand_machine()

    def refuse(*a, **k):
        raise AssertionError("black-ops tried to open a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    run("status")
    run("on")


def test_without_the_helper_the_privileged_rows_say_so(sandbox, run):
    sandbox.stock_machine()
    sandbox.helper.unlink()
    rep = run("on")
    r = rows(rep)
    assert sandbox.calls("sudo") == []
    assert rep["helperState"] == "missing"
    for row_id in ("hosts", "dns"):
        assert r[row_id]["status"] == "warn"
        assert "black-ops-install" in r[row_id]["error"]
    for row_id in ("weather", "agents", "claude"):
        assert r[row_id]["status"] == "ok", row_id


def test_a_bare_machine_is_skipped_cleanly(sandbox, run):
    """Stock Omarchy before any of these files exist: no weather location
    chosen yet, no Agents widget on the bar, Claude Code never started."""
    sandbox.write(sandbox.hosts, STOCK_HOSTS)
    rep = run("on")
    r = rows(rep)
    for row_id in ("weather", "agents", "claude", "hosts"):
        assert r[row_id]["status"] == "na", row_id
        assert r[row_id]["error"] == "", row_id
        assert r[row_id]["switchable"] is False, row_id
    assert r["dns"]["status"] == "ok"
    assert rep["overall"] == "ok", rep
    assert sandbox.helper_verbs() == ["dns-on"]
    assert sandbox.hosts.read_text() == STOCK_HOSTS
    assert not sandbox.weather.exists() and not sandbox.shell_json.exists()
    assert not sandbox.claude.parent.exists()
    assert set(sandbox.state()["rows"]) == {"dns"}
    rep = run("off")
    assert rep["overall"] == "off" and sandbox.state()["rows"] == {}


def test_the_agents_widget_not_on_the_bar_is_not_applicable(sandbox, run):
    sandbox.stock_machine()
    doc = json.loads(sandbox.shell_json.read_text())
    doc["bar"]["layout"]["right"] = [{"id": "omarchy.tray"}]
    sandbox.write(sandbox.shell_json, json.dumps(doc, indent=2) + "\n")
    before = sandbox.shell_json.read_bytes()
    rep = run("on")
    assert rows(rep)["agents"]["status"] == "na"
    assert rows(rep)["agents"]["error"] == ""
    assert sandbox.shell_json.read_bytes() == before


def test_a_weather_file_without_coordinates_is_not_applicable(sandbox, run):
    sandbox.stock_machine()
    sandbox.write(sandbox.weather, '{\n  "name": "Somewhere"\n}\n')
    rep = run("on")
    assert rows(rep)["weather"]["status"] == "na"
    assert sandbox.weather.read_text() == '{\n  "name": "Somewhere"\n}\n'


# ------------------------------------------------------------- JSON edits

def test_claude_settings_keep_every_other_key(sandbox, run):
    sandbox.write(sandbox.hosts, STOCK_HOSTS)
    original = json.dumps({
        "model": "opus",
        "modelSettings": {"claude-opus-5": {"effortLevel": "high"}},
        "env": {"FOO": "bar", "PATH_EXTRA": "/opt/thing"},
        "permissions": {"allow": ["Bash(ls:*)"], "deny": []},
        "note": "café, naïve",
        "number": 1.5,
    }, indent=2, ensure_ascii=False) + "\n"
    sandbox.write(sandbox.claude, original)
    run("on")
    data = json.loads(sandbox.claude.read_text())
    assert list(data) == ["model", "modelSettings", "env", "permissions", "note", "number"]
    assert data["env"] == {"FOO": "bar", "PATH_EXTRA": "/opt/thing",
                           "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"}
    assert data["note"] == "café, naïve" and "café" in sandbox.claude.read_text()
    run("off")
    assert sandbox.claude.read_text() == original


def test_claude_env_created_by_the_plugin_is_removed_again(sandbox, run):
    sandbox.write(sandbox.hosts, STOCK_HOSTS)
    original = '{\n  "model": "opus"\n}\n'
    sandbox.write(sandbox.claude, original)
    run("on")
    assert json.loads(sandbox.claude.read_text())["env"]["DISABLE_TELEMETRY"] == "1"
    run("off")
    assert sandbox.claude.read_text() == original


def test_agents_edit_keeps_the_rest_of_shell_json(sandbox, run):
    sandbox.stock_machine()
    before = json.loads(sandbox.shell_json.read_text())
    run("on")
    after = json.loads(sandbox.shell_json.read_text())
    entry = after["bar"]["layout"]["right"][1]
    assert entry["providers"] == {"claude": {"enabled": True}, "codex": {"enabled": False},
                                  "fireworks": {"enabled": False}}
    del entry["providers"]
    assert after == before
    # The shell was asked first; with no shell running, the file was edited
    # directly and the shell told to reload.
    assert sandbox.calls("omarchy-shell") == ["omarchy-shell shell reloadConfig"]


def test_agents_edit_goes_through_omarchy_bar_set_when_it_works(sandbox, run):
    sandbox.stock_machine()
    import sys
    sandbox.stub("omarchy", f"""#!{sys.executable}
import json, os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("omarchy " + " ".join(sys.argv[1:]) + "\\n")
path = os.path.join(os.environ["HOME"], ".config/omarchy/shell.json")
doc = json.load(open(path))
for e in doc["bar"]["layout"]["right"]:
    if e["id"] == sys.argv[3]:
        e[sys.argv[4]] = json.loads(sys.argv[5])
open(path, "w").write(json.dumps(doc, indent=2) + "\\n")
""")
    run("on")
    calls = sandbox.calls("omarchy ")
    assert len(calls) == 1 and calls[0].startswith("omarchy bar set omarchy.agents providers ")
    assert calls[0].endswith(" --json")
    assert sandbox.calls("omarchy-shell") == []


def test_weather_rounding_keeps_the_name(sandbox, run):
    sandbox.stock_machine()
    run("on")
    text = sandbox.weather.read_text()
    assert json.loads(text) == {"name": "Somewhere", "latitude": 48.8568, "longitude": 2.3071}
    assert list(json.loads(text)) == ["name", "latitude", "longitude"]


def test_state_file_holds_nothing_sensitive(sandbox, run):
    sandbox.stock_machine()
    run("on")
    text = sandbox.state_file.read_text()
    assert oct(sandbox.state_file.stat().st_mode & 0o777) == "0o600"
    assert oct(sandbox.state_file.parent.stat().st_mode & 0o777) == "0o700"
    for secret in ("48.85", "2.29", "Somewhere", "device.id", str(sandbox.home)):
        assert secret not in text


def test_constants_match_the_helper(bo, helper):
    for name in ("TELEMETRY_HOSTS", "SINKS", "BEGIN", "END"):
        assert getattr(bo, name) == getattr(helper, name), name


def test_dump_like_reproduces_files_it_did_not_change(bo):
    for text in ('{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}\n',
                 '{\n    "a": true\n}',
                 '{\n\t"a": "\\u00e9"\n}\n'):
        assert bo.dump_like(text, json.loads(text)) == text
