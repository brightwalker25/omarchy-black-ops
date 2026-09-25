"""The status JSON fixtures the panel is tested against, checked against
docs/contract.md and against what bin/black-ops really prints, so that the
panel is never tested against a shape the core does not produce. Also checks
that every field the panel reads is one the contract defines.

This is the test section 15 of the contract asks of piece C."""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "panel-fixtures"
NAMES = sorted(p.stem for p in FIXTURES.glob("*.json"))

# Section 4.1, and the fields 0.2 already printed.
TOP = {"overall", "colour", "slipped", "unapplied", "attention", "leaks", "flagged", "watch",
       "listen", "omarchy", "rowsD", "generatedAt", "version", "master", "headline", "pending",
       "helperInstalled", "helperState", "helperNote", "rows", "canPair", "pairSecondsLeft"}
# Section 4.2.
ROW = {"id", "status", "colour", "label", "value", "detail", "why", "error", "intended",
       "inPlace", "optional", "privileged", "oneWay", "managed", "switchable", "registered",
       "source"}
# Section 4.3.
ITEM = {"id", "source", "kind", "severity", "program", "exe", "package", "path", "host",
        "signature", "vendor", "summary", "firstSeen", "lastSeen", "count", "reviewed",
        "verdict", "active", "colour"}
# Sections 5.5 and 6.5, with the "available" the core adds.
WATCH = {"enabled", "hookInstalled", "lastScan", "lastScanKind", "lastScanError", "scanning",
         "inventoryCount", "pendingCount", "flaggedCount", "unreviewedCount", "available"}
LISTEN = {"enabled", "serviceActive", "since", "retentionHours", "segments", "contactCount",
          "hostCount", "unknownCount", "leakCount", "available"}
# Fields the panel shows when an item carries them, which contract version 1
# does not define. They are reported to the coordinator as a gap.
PROPOSED = {"version", "ecosystem", "match", "optOut"}

OVERALL_COLOUR = {"ok": "green", "warn": "amber", "leak": "red", "off": "grey"}
STATUS_COLOUR = {"ok": "green", "warn": "amber", "leak": "red", "off": "grey", "na": "grey"}


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_every_state_has_a_fixture():
    assert set(NAMES) >= {"off", "on-green", "watch-amber", "watch-baseline", "watch-hook-missing",
                          "listen-na", "listen-off", "listen-amber", "listen-red", "phase1",
                          "extensions-missing"}


@pytest.mark.parametrize("name", NAMES)
def test_fixture_follows_the_contract(name):
    rep = load(name)
    assert set(rep) == TOP
    assert rep["colour"] == OVERALL_COLOUR[rep["overall"]]
    for r in rep["rows"]:
        assert set(r) == ROW, r["id"]
        assert r["colour"] == STATUS_COLOUR[r["status"]]
        assert not (r["registered"] and r["switchable"])
    for key, fields in (("watch", WATCH), ("listen", LISTEN)):
        obj = rep[key]
        if obj.get("available"):
            assert set(obj) == fields
        else:
            assert set(obj) == {"available", "error"}
    for it in rep["flagged"]:
        assert ITEM <= set(it) <= ITEM | PROPOSED
        assert re.fullmatch(r"[0-9a-f]{16}", it["id"])
        assert it["active"] is not it["reviewed"]
        want = ("red" if it["severity"] == "leak" else "amber") if it["active"] else "grey"
        assert it["colour"] == want
        # Red is kept for what listen mode saw happen.
        if it["severity"] == "leak":
            assert it["source"] == "listen" and it["kind"] == "contact" and it["host"]
    keys = [(not i["active"], i["severity"] != "leak", -i["lastSeen"]) for i in rep["flagged"]]
    assert keys == sorted(keys)
    # Red overall exactly when something active is red or a row leaked.
    red = any(i["colour"] == "red" for i in rep["flagged"]) or rep["leaks"]
    assert (rep["overall"] == "leak") == bool(red)
    if not rep["master"]:
        assert rep["flagged"] == []


def test_fixtures_hold_no_account_name():
    home = str(Path.home())
    for p in FIXTURES.iterdir():
        assert home not in p.read_text()


def fake_extensions(bo, items):
    """Watch and listen extensions that report contract-shaped objects."""
    def make(name):
        class R(bo.Row):
            id = name
            label = "Software watch" if name == "watch" else "Listen mode"
            optional = True

            def check(self, ctx, rec=None):
                return bo.result("in", "on", "")

            def apply(self, ctx, chk, rec):
                pass

            def revert(self, ctx, rec):
                pass

        class Ext:
            @staticmethod
            def flagged(ctx, api):
                # `source` is left in. The contract says the core sets it, but
                # the core's FLAG_FIELDS check drops an item that lacks it;
                # reported to the coordinator.
                return [{k: v for k, v in i.items()
                         if k not in ("reviewed", "verdict", "active", "colour")}
                        for i in items if i["source"] == name]

            @staticmethod
            def report(ctx, api):
                src = load("on-green")[name]
                return {k: v for k, v in src.items() if k != "available"}

        row = R()
        bo.ROWS.append(row)
        bo.BY_ID[name] = row
        bo.EXT[name] = Ext

    make("watch")
    make("listen")


def test_the_fixtures_have_the_shape_the_core_prints(bo, sandbox, run):
    """The core, given the fixture's items through fake extensions, prints a
    report with the same fields, and the same items in the same order with
    the same colours."""
    fixture = load("listen-red")
    fake_extensions(bo, fixture["flagged"])
    sandbox.stock_machine()
    run("on")
    run("row", "watch", "on")
    rep = run("row", "listen", "on")
    assert set(rep) == set(fixture)
    for r in rep["rows"]:
        assert set(r) == ROW
    assert set(rep["watch"]) == WATCH and set(rep["listen"]) == LISTEN
    got = [(i["id"], i["colour"], i["active"]) for i in rep["flagged"]]
    want = [(i["id"], i["colour"], i["active"]) for i in fixture["flagged"]
            if i["verdict"] is None]
    # The fixture's reviewed item has no review in the sandbox, so compare
    # the active ones only.
    assert [g for g in got if g[0] in {w[0] for w in want}] == want
    assert rep["overall"] == "leak"


def fields_read(text, names):
    found = set()
    for name in names:
        found |= set(re.findall(r"\b" + re.escape(name) + r"\.([A-Za-z_]\w*)", text))
    return found


def test_the_panel_reads_only_contract_fields():
    model = (REPO / "Model.js").read_text()
    panel = (REPO / "Panel.qml").read_text()
    # What the JSON may hold, the rows.d skip entries, the program groups
    # Model.listenGroups builds, and the JavaScript methods called on them.
    known = (TOP | ROW | ITEM | WATCH | LISTEN | PROPOSED | {"skipped", "file", "why"}
             | {"items", "program", "colour", "active", "firstSeen", "lastSeen", "count"}
             | {"push", "indexOf", "join", "length"})
    # The names the report, its rows and its items go by in Model.js and in
    # the panel's delegates.
    names = ("item", "it", "modelData", "row", "rep", "watch", "listen", "rowsD",
             "prow.item", "witem.item", "actions.item", "contact.modelData",
             "wdetail.watch", "ldetail.listen", "wdetail.row", "ldetail.row", "root.rep")
    read = fields_read(model, names) | fields_read(panel, names)
    assert sorted(read - known) == []
