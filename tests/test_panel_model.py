"""The panel's Model.js against the status JSON fixtures in
tests/panel-fixtures, run under node by tests/panel_model.js. There is no
QML test harness, so what the panel draws is tested here through the
functions it draws from. Skipped when node is not installed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "panel-fixtures"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def model(name):
    out = subprocess.run([NODE, str(REPO / "tests" / "panel_model.js"), str(FIXTURES / f"{name}.json")],
                         capture_output=True, text=True, check=True, timeout=30)
    return json.loads(out.stdout)


def test_off_is_grey_with_no_red_or_amber_named():
    m = model("off")
    assert set(m["rowStatus"].values()) == {"off"}
    assert m["tooltip"] == "Black Ops: Off. The machine is as it ships"
    assert m["groups"] == [] and m["reviewAll"] == []


def test_green_names_nothing():
    m = model("on-green")
    assert m["rowStatus"]["watch"] == "ok" and m["rowStatus"]["listen"] == "ok"
    assert "Red:" not in m["tooltip"] and "Amber:" not in m["tooltip"]
    assert m["watchSummary"].startswith("Last scan @")
    assert "Kept in RAM for 72 hours" in m["listenSummary"]


def test_unreviewed_watch_items_make_the_watch_row_amber():
    m = model("watch-amber")
    assert m["rowStatus"]["watch"] == "warn"
    assert m["rowStatus"]["listen"] == "ok"
    assert "Amber: 3 software watch items to review" in m["tooltip"]
    # The reviewed item is not reviewed again by "Mark all reviewed".
    assert len(m["reviewAll"]) == 3


def test_watch_evidence_shows_what_the_item_carries():
    m = model("watch-amber")
    lines = [l for ev in m["watchEvidence"] for l in ev]
    assert "Package otherapp 2.4.1-1 (pacman)" in lines
    assert 'Matched "ingest.sentry.io", Sentry (sentry-ingest)' in lines
    assert "To opt out: Set SENTRY_DSN to an empty value in its environment." in lines
    assert "Installed through mise" in lines
    assert "File: /usr/bin/someapp" in lines


def test_mark_all_reviewed_asks_for_the_status_once_at_the_end():
    m = model("watch-baseline")
    cmds = m["reviewAll"]
    assert len(cmds) == 12
    assert all(c[0] == "review" and c[2] == "allow" for c in cmds)
    assert [c for c in cmds if "--status" in c] == [cmds[-1]]
    assert len({c[1] for c in cmds}) == 12


def test_a_missing_hook_is_amber_and_said():
    m = model("watch-hook-missing")
    assert m["rowStatus"]["watch"] == "warn"
    assert "Amber: Software watch needs attention" in m["tooltip"]
    assert "pacman hook is not installed" in m["watchSummary"]


def test_listen_without_bpftrace_is_grey_with_the_note():
    m = model("listen-na")
    assert m["rowStatus"]["listen"] == "na"
    assert "bpftrace" in m["listenOffNote"] and "cannot be switched on" in m["listenOffNote"]


def test_listen_off_is_grey_with_the_note():
    m = model("listen-off")
    assert m["rowStatus"]["listen"] == "off"
    assert "installer" in m["listenOffNote"] and "off by default" in m["listenOffNote"]


def test_listen_contacts_that_are_not_telemetry_are_amber():
    m = model("listen-amber")
    assert m["rowStatus"]["listen"] == "warn"
    assert [g["program"] for g in m["groups"]] == ["editor"]
    assert m["groups"][0]["colour"] == "amber" and len(m["groups"][0]["hosts"]) == 2
    assert "Amber: 1 program seen by listen mode to review" in m["tooltip"]


def test_a_leak_is_red_first_and_named():
    m = model("listen-red")
    assert m["rowStatus"]["listen"] == "leak"
    assert [g["colour"] for g in m["groups"]] == ["red", "amber", "grey"]
    red = m["groups"][0]
    assert red["program"] == "someapp"
    assert red["hosts"][0] == "http-intake.logs.us5.datadoghq.com"
    lines = m["tooltip"].split("\n")
    assert lines[1] == "Red: someapp to Datadog"
    assert lines[2].startswith("Amber: Claude Code telemetry host has slipped")
    # A reviewed leak is grey and is not named.
    assert "viewer" not in m["tooltip"]


def test_phase_one_states_are_named():
    m = model("phase1")
    assert "DNS fallback servers has slipped" in m["tooltip"]
    assert "Debug symbol downloads is not applied yet" in m["tooltip"]
    assert "root helper needs reinstalling" in m["tooltip"]
    assert m["rowStatus"]["nightloom/ollama-block"] == "ok"


def test_missing_extensions_leave_the_rest_working():
    m = model("extensions-missing")
    assert "watch" not in m["rowStatus"] and "listen" not in m["rowStatus"]
    # The error itself is shown in its place, not a second sentence.
    assert m["watchSummary"] == ""
    assert m["listenSummary"] == "Listen mode is not part of this build."
    assert m["extensionErrors"] == "Software watch: watch could not be loaded: SyntaxError"
