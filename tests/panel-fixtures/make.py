#!/usr/bin/env python3
"""Writes the status JSON fixtures in this folder, one per state the panel
and the bar have to draw. Run it again after changing it; the JSON files
are committed so the tests and tests/panel-fixtures.sh need nothing else.

Every field follows docs/contract.md, contract version 1. The watch and
listen items are made up, and no name, host or path in them belongs to a
real account."""
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOW = 1790000000


def item_id(*parts):
    """Section 4.4 of the contract."""
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:16]


def row(id, label, status="ok", value="in place", intended=True, **kw):
    r = {
        "id": id, "label": label, "value": value, "detail": "", "why": "",
        "status": status,
        "colour": {"ok": "green", "warn": "amber", "leak": "red"}.get(status, "grey"),
        "inPlace": status in ("ok", "leak"), "intended": intended,
        "managed": "applied" if intended and status != "na" else None,
        "oneWay": False, "optional": False, "privileged": False, "error": "",
        "registered": False, "source": "black-ops",
        "switchable": status != "na",
    }
    r.update(kw)
    return r


def base_rows(master=True):
    rows = [
        row("hosts", "Claude Code telemetry host", privileged=True),
        row("dns", "DNS fallback servers", privileged=True),
        row("weather", "Weather location", value="rounded"),
        row("bluetooth", "Bluetooth pairing", value="not pairable"),
        row("debuginfod", "Debug symbol downloads", value="off"),
        row("watch", "Software watch", value="watching", optional=True),
        row("listen", "Listen mode", value="listening", optional=True, privileged=True),
    ]
    if not master:
        for r in rows:
            r.update(status="off", colour="grey", intended=False, managed=None,
                     inPlace=False, switchable=False, value="stock")
    return rows


def watch_obj(**kw):
    w = {"enabled": True, "hookInstalled": True, "lastScan": NOW - 3600,
         "lastScanKind": "changed", "lastScanError": "", "scanning": False,
         "inventoryCount": 4312, "pendingCount": 0, "flaggedCount": 0,
         "unreviewedCount": 0, "available": True}
    w.update(kw)
    return w


def listen_obj(**kw):
    l = {"enabled": True, "serviceActive": True, "since": NOW - 72 * 3600,
         "retentionHours": 72, "segments": 72, "contactCount": 812,
         "hostCount": 140, "unknownCount": 131, "leakCount": 0, "available": True}
    l.update(kw)
    return l


def report(**kw):
    rep = {
        "generatedAt": NOW, "version": "0.3.0", "master": True,
        "overall": "ok", "colour": "green", "headline": "On, 7 protections holding",
        "slipped": [], "unapplied": [], "attention": [], "leaks": [], "pending": [],
        "helperInstalled": True, "helperState": "current", "helperNote": "",
        "rows": base_rows(), "canPair": True, "pairSecondsLeft": 0,
        "omarchy": {"version": "4.0.4-1", "recorded": "4.0.4-1", "changed": False},
        "flagged": [], "watch": watch_obj(), "listen": listen_obj(),
        "rowsD": {"skipped": []},
    }
    rep.update(kw)
    return rep


def set_row(rep, id, **kw):
    for r in rep["rows"]:
        if r["id"] == id:
            r.update(kw)
            if "status" in kw and "colour" not in kw:
                r["colour"] = {"ok": "green", "warn": "amber", "leak": "red"}.get(kw["status"], "grey")
    return rep


def watch_item(program, path, signature, vendor, summary, reviewed=None, **kw):
    it = {
        "id": item_id("watch", "static", path, signature), "source": "watch",
        "kind": "static", "severity": "warn", "program": program, "exe": path,
        "package": program, "path": path, "host": None, "signature": signature,
        "vendor": vendor, "summary": summary, "firstSeen": NOW - 86400,
        "lastSeen": NOW - 3600, "count": 2,
    }
    it.update(kw)
    return finish(it, reviewed)


def contact(program, host, signature, vendor, summary, severity, reviewed=None, **kw):
    exe = f"/usr/bin/{program}"
    it = {
        "id": item_id("listen", "contact", exe, host, signature), "source": "listen",
        "kind": "contact", "severity": severity, "program": program, "exe": exe,
        "package": program, "path": None, "host": host, "signature": signature,
        "vendor": vendor, "summary": summary, "firstSeen": NOW - 7200,
        "lastSeen": NOW - 600, "count": 4,
    }
    it.update(kw)
    return finish(it, reviewed)


def finish(it, reviewed):
    """The fields the core adds, section 4.3."""
    it["reviewed"] = reviewed is not None
    it["verdict"] = reviewed
    it["active"] = reviewed is None
    it["colour"] = ("red" if it["severity"] == "leak" else "amber") if it["active"] else "grey"
    return it


def ordered(items):
    """The core's order: active first, red first, newest first."""
    return sorted(items, key=lambda i: (not i["active"], i["severity"] != "leak", -i["lastSeen"]))


WATCH_ITEMS = [
    watch_item("someapp", "/usr/bin/someapp", "datadog-intake", "Datadog",
               "Carries the address of Datadog's log intake."),
    watch_item("otherapp", "/usr/lib/otherapp/otherapp", "sentry-ingest", "Sentry",
               "Carries the address of a Sentry crash report intake.", lastSeen=NOW - 1800,
               version="2.4.1-1", ecosystem="pacman", match="ingest.sentry.io",
               optOut="Set SENTRY_DSN to an empty value in its environment."),
    watch_item("devtool", "/opt/devtool/bin/devtool",
               "segment-api", "Segment", "Carries the address of Segment's analytics API.",
               package=None, lastSeen=NOW - 900, count=1, ecosystem="mise"),
    watch_item("oldapp", "/usr/bin/oldapp", "datadog-intake", "Datadog",
               "Carries the address of Datadog's log intake.", reviewed="allowed"),
]


def fixtures():
    out = {}

    # Off: the dimmed open lock, and no flagged items at all.
    off = report(master=False, overall="off", colour="grey",
                 headline="Off. The machine is as it ships", rows=base_rows(master=False),
                 canPair=False, watch=watch_obj(enabled=False, lastScan=None, inventoryCount=0),
                 listen=listen_obj(enabled=False, serviceActive=False, since=None,
                                   retentionHours=None, segments=0, contactCount=0,
                                   hostCount=0, unknownCount=0))
    out["off"] = off

    # On with everything holding and nothing flagged: green.
    out["on-green"] = report()

    # The watch has flagged items nobody has reviewed: amber, the watch row
    # amber too, one reviewed item grey.
    rep = report(overall="warn", colour="amber", headline="On, but 3 flagged items need review",
                 flagged=ordered(WATCH_ITEMS),
                 watch=watch_obj(flaggedCount=4, unreviewedCount=3))
    out["watch-amber"] = rep

    # The first scan: many items at once, for "Mark all reviewed".
    many = [watch_item(f"app{n:02d}", f"/usr/bin/app{n:02d}", "datadog-intake", "Datadog",
                       "Carries the address of Datadog's log intake.", lastSeen=NOW - n)
            for n in range(12)]
    out["watch-baseline"] = report(overall="warn", colour="amber",
                                   headline="On, but 12 flagged items need review",
                                   flagged=ordered(many), watch=watch_obj(
                                       lastScanKind="full", flaggedCount=12, unreviewedCount=12))

    # The watch without its pacman hook: the row's own check says attention.
    rep = report(overall="warn", colour="amber", headline="On, but Software watch needs attention",
                 attention=["watch"], watch=watch_obj(hookInstalled=False))
    set_row(rep, "watch", status="warn", why="The pacman hook is not installed; run the installer.")
    out["watch-hook-missing"] = rep

    # Listen mode cannot run here: no bpftrace. The row is grey with no switch.
    rep = report(listen=listen_obj(enabled=False, serviceActive=False, since=None,
                                   retentionHours=72, segments=0, contactCount=0,
                                   hostCount=0, unknownCount=0))
    set_row(rep, "listen", status="na", value="needs bpftrace", intended=False,
            managed=None, inPlace=False, switchable=False,
            detail="bpftrace is not installed.")
    out["listen-na"] = rep

    # Listen mode installed but switched off.
    rep = report(listen=listen_obj(enabled=False, serviceActive=False, since=None,
                                   segments=0, contactCount=0, hostCount=0, unknownCount=0))
    set_row(rep, "listen", status="off", value="off", intended=False, managed=None,
            inPlace=False)
    out["listen-off"] = rep

    # Programs making contact with hosts that are not telemetry: amber.
    amber = [
        contact("editor", "flags.example-vendor.com", "example-flags", "Example Vendor",
                "Asked Example Vendor's feature flag service.", "warn"),
        contact("editor", "updates.example-vendor.com", "example-updates", "Example Vendor",
                "Checked for updates with Example Vendor.", "warn", lastSeen=NOW - 1200),
    ]
    out["listen-amber"] = report(overall="warn", colour="amber",
                                 headline="On, but 2 flagged items need review",
                                 flagged=ordered(amber))

    # A confirmed leak: red wins over an amber slip and amber items.
    red = amber + [
        contact("someapp", "http-intake.logs.us5.datadoghq.com", "datadog-intake", "Datadog",
                "Contacted Datadog's telemetry intake.", "leak"),
        contact("someapp", "api.segment.io", "segment-api", "Segment",
                "Contacted Segment's analytics API.", "warn"),
        contact("viewer", "o0.ingest.sentry.io", "sentry-ingest", "Sentry",
                "Contacted a Sentry crash report intake.", "leak", reviewed="false-positive"),
    ]
    rep = report(overall="leak", colour="red",
                 headline="On, but someapp contacted a telemetry host",
                 slipped=["hosts"], leaks=["listen"], flagged=ordered(red + WATCH_ITEMS[:1]),
                 listen=listen_obj(leakCount=1))
    set_row(rep, "listen", status="leak", why="someapp contacted a telemetry host.")
    set_row(rep, "hosts", status="warn", inPlace=False, value="not blocked",
            why="The block is gone from /etc/hosts. Switch on again to put it back.")
    out["listen-red"] = rep

    # Phase 1's own states: a slip, a row new in this version, the pair
    # window open, a rows.d row with a skipped file, and an old helper.
    rep = report(overall="warn", colour="amber", headline="On, but DNS fallback servers has slipped",
                 slipped=["dns"], unapplied=["debuginfod"], pairSecondsLeft=42,
                 helperState="outdated",
                 helperNote="The root helper is from another version. Run the installer again.",
                 rowsD={"skipped": [{"file": "broken.json", "why": "not valid JSON"}]})
    set_row(rep, "dns", status="warn", inPlace=False, value="Google, Cloudflare",
            why="Fallback servers are set again. Switch on again to put it back.",
            error="The root helper is from another version. Run the installer again.")
    set_row(rep, "debuginfod", status="warn", inPlace=False, value="on",
            why="Not put in place yet. Switch on again to apply it.")
    rep["rows"].append(row("nightloom/ollama-block", "ollama.com block", value="blocked",
                           registered=True, source="nightloom", switchable=False, managed=None))
    out["phase1"] = rep

    # Extensions that failed to load: their rows are missing and the
    # objects say why.
    rep = report(watch={"available": False, "error": "watch could not be loaded: SyntaxError"},
                 listen={"available": False, "error": ""})
    rep["rows"] = [r for r in rep["rows"] if r["id"] not in ("watch", "listen")]
    out["extensions-missing"] = rep
    return out


def main():
    for name, rep in fixtures().items():
        (HERE / f"{name}.json").write_text(json.dumps(rep, indent=2) + "\n")


if __name__ == "__main__":
    main()
