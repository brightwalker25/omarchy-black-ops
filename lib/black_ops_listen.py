"""Listen mode, for bin/black-ops: the part that runs as the user.

docs/contract.md, section 6, fixes what this module provides and what it may
read; docs/listen.md describes listen mode for the person using it. The root
half is system/listen, run by the omarchy-black-ops-listen service, which
writes the view this module reads:

    /run/black-ops-listen/view/contacts.json

bin/black-ops loads this file by path and calls only these functions:

    make_row(api)            -> the "listen" row: optional and privileged
    report(ctx, api)         -> the "listen" object of the status JSON
    flagged(ctx, api)        -> one item per contact whose host matches a
                                signature; severity "leak" for a telemetry,
                                analytics or crash-report signature, which is
                                the one thing that is ever red
    cli(ctx, api, argv)      -> `black-ops listen status|report|purge`

Nothing here writes a file, opens a network connection or needs root. The
root helper's listen-on, listen-off and listen-purge verbs do the switching.
"""
import argparse
import fnmatch
import hashlib
import json
import sys
import time
import tomllib

SERVICE = "omarchy-black-ops-listen.service"
RED_KINDS = ("telemetry", "analytics", "crash-report")
KIND_WORDS = {
    "telemetry": "telemetry intake",
    "analytics": "analytics collector",
    "crash-report": "crash report intake",
    "feature-flags": "feature flag service",
    "lookup": "lookup service",
    "update-check": "update check",
}
ABOUT = ("Records which program looked up which host and connected where, in RAM "
         "only, and turns red when a program contacts a known telemetry host. "
         "It needs bpftrace and runs as a root service while it is on.")


# ------------------------------------------------------------------ reading

def view_path(ctx):
    return ctx.run_dir / "black-ops-listen" / "view" / "contacts.json"


def monitor_socket(ctx):
    return ctx.run_dir / "systemd" / "resolve" / "io.systemd.Resolve.Monitor"


def load_view(ctx, api):
    """The listener's view, or None when there is none or it cannot be
    read. A document of another shape counts as none."""
    try:
        _, data = api.load_json(view_path(ctx))
    except api.ActionError:
        return None
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("contacts"), list):
        return None
    data["contacts"] = [c for c in data["contacts"] if isinstance(c, dict)
                        and isinstance(c.get("program"), str)
                        and isinstance(c.get("count"), int)
                        and isinstance(c.get("firstSeen"), int)
                        and isinstance(c.get("lastSeen"), int)]
    return data


def service_state(ctx):
    """{"load", "enabled", "active"} of the listen service, read with
    systemctl show. Unknown values read as not installed and not running."""
    rc, out, _ = ctx.run(["systemctl", "show", "-p", "LoadState", "-p", "UnitFileState",
                          "-p", "ActiveState", SERVICE], timeout=5)
    props = {}
    for line in out.splitlines() if rc == 0 else []:
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = v.strip()
    return {"load": props.get("LoadState", ""),
            "enabled": props.get("UnitFileState") in ("enabled", "enabled-runtime"),
            "active": props.get("ActiveState") in ("active", "reloading")}


def available(ctx):
    """"" when listen mode can run here, or why it cannot."""
    if not ctx.which("bpftrace"):
        return "bpftrace is not installed. Install it with: sudo pacman -S bpftrace"
    if not monitor_socket(ctx).exists():
        return "systemd-resolved's monitor socket is missing, so lookups cannot be seen."
    return ""


# ---------------------------------------------------------------- signatures

def load_signatures(api):
    """[(id, vendor, kind, [patterns])] from data/signatures.toml."""
    text = api.read_text(api.LIB_DIR.parent / "data" / "signatures.toml")
    try:
        data = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        return []
    out = []
    for sig in data.get("signature", []):
        if isinstance(sig, dict) and isinstance(sig.get("id"), str) and isinstance(sig.get("hosts"), list):
            out.append((sig["id"], str(sig.get("vendor", "")), str(sig.get("kind", "")),
                        [normal_host(h) for h in sig["hosts"] if isinstance(h, str)]))
    return out


def normal_host(host):
    return host.lower().rstrip(".")


def match_host(host, signatures):
    """The first signature a host matches, as (id, vendor, kind, pattern),
    or None.
    The rule in docs/contract.md, section 8. The listener applies the same
    rule to the root copy; this one uses the plugin's own copy, so a newly
    added signature applies at once to what is already recorded."""
    if not isinstance(host, str) or not host:
        return None
    h = normal_host(host)
    for sid, vendor, kind, pats in signatures:
        for p in pats:
            if fnmatch.fnmatchcase(h, p):
                return sid, vendor, kind, p
    return None


def item_id(exe, program, host, signature):
    """docs/contract.md, section 4.4."""
    parts = ["listen", "contact", exe or program or "", host, signature]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:16]


def severity(kind):
    return "leak" if kind in RED_KINDS else "warn"


def summary_for(vendor, kind):
    words = KIND_WORDS.get(kind, "service")
    text = f"Contacted {vendor}'s {words}." if vendor else f"Contacted a known {words}."
    return text[:119]


# ------------------------------------------------------------------ items

def items_from(view, signatures):
    """One item per program and host that matches a signature. Entries the
    listener split by unit are joined again, because the id does not
    include the unit."""
    items = {}
    for c in (view or {}).get("contacts", []):
        host = c.get("host")
        sig = match_host(host, signatures)
        if sig is None and isinstance(c.get("signature"), str) and isinstance(c.get("kind"), str):
            # A signature the root copy knows and this copy does not.
            sig = (c["signature"], "", c["kind"], None)
        if sig is None or not host:
            continue
        sid, vendor, kind, pattern = sig
        exe = c.get("exe") if isinstance(c.get("exe"), str) else None
        iid = item_id(exe, c["program"], normal_host(host), sid)
        it = items.get(iid)
        if it is None:
            items[iid] = {
                "id": iid, "source": "listen", "kind": "contact", "severity": severity(kind),
                "program": c["program"], "exe": exe, "package": None, "path": None,
                # What matched, for the panel to show; see docs/contract.md,
                # section 16.
                "match": {"signature": sid, "vendor": vendor, "kind": kind, "pattern": pattern},
                "host": normal_host(host), "signature": sid, "vendor": vendor,
                "summary": summary_for(vendor, kind),
                "firstSeen": c["firstSeen"], "lastSeen": c["lastSeen"], "count": c["count"],
            }
        else:
            it["firstSeen"] = min(it["firstSeen"], c["firstSeen"])
            it["lastSeen"] = max(it["lastSeen"], c["lastSeen"])
            it["count"] += c["count"]
    return sorted(items.values(), key=lambda i: -i["lastSeen"])


def counts(view, signatures, reviews):
    """The numbers in the listen object of the status JSON."""
    contacts = (view or {}).get("contacts", [])
    hosts, unknown = set(), set()
    for c in contacts:
        name = c.get("host") if isinstance(c.get("host"), str) else None
        key = normal_host(name) if name else c.get("addr")
        if not key:
            continue
        hosts.add(key)
        if match_host(name, signatures) is None and not c.get("signature"):
            unknown.add(key)
    items = items_from(view, signatures)
    leaks = [i for i in items if i["severity"] == "leak" and i["id"] not in reviews]
    return {"contactCount": sum(c["count"] for c in contacts), "hostCount": len(hosts),
            "unknownCount": len(unknown), "leakCount": len(leaks)}


# ------------------------------------------------------------ the contract

def flagged(ctx, api):
    return items_from(load_view(ctx, api), load_signatures(api))


def report(ctx, api):
    svc = service_state(ctx)
    view = load_view(ctx, api) if svc["active"] else None
    rep = {
        "enabled": svc["enabled"],
        "serviceActive": svc["active"],
        "since": view.get("since") if view else None,
        "retentionHours": view.get("retentionHours") if view else None,
        "segments": int(view.get("segments") or 0) if view else 0,
    }
    rep.update(counts(view, load_signatures(api), api.load_reviews(ctx)))
    # Additions the contract allows: whether both sources are live.
    rep["probeRunning"] = bool(view.get("probeRunning")) if view else False
    rep["dnsConnected"] = bool(view.get("dnsConnected")) if view else False
    return rep


def make_row(api):
    class ListenRow(api.Row):
        id = "listen"
        label = "Listen mode"
        optional = True
        privileged = True
        about = ABOUT

        def check(self, ctx, rec=None):
            why_not = available(ctx)
            if why_not:
                return api.result("na", "not available", self.about + " " + why_not)
            svc = service_state(ctx)
            if svc["load"] == "not-found":
                return api.result("out", "not installed", self.about,
                                  why="The listen service is not installed. Run sudo bin/black-ops-install.")
            if svc["active"]:
                view = load_view(ctx, api)
                sigs = load_signatures(api)
                reviews = api.load_reviews(ctx)
                active = [i for i in items_from(view, sigs) if i["id"] not in reviews]
                leaks = [i for i in active if i["severity"] == "leak"]
                others = [i for i in active if i["severity"] != "leak"]
                if leaks:
                    progs = sorted({i["program"] for i in leaks})
                    names = ", ".join(progs[:2]) + (f" and {len(progs) - 2} more" if len(progs) > 2 else "")
                    return api.result("in", f"{len(leaks)} telemetry contact" + ("s" if len(leaks) != 1 else ""),
                                      self.about, leak=True,
                                      attention=f"Listen mode saw {names} contact a telemetry host.")
                if others:
                    progs = sorted({i["program"] for i in others})
                    names = ", ".join(progs[:2]) + (f" and {len(progs) - 2} more" if len(progs) > 2 else "")
                    return api.result("in", f"{len(others)} contact" + ("s" if len(others) != 1 else "")
                                      + " to review", self.about,
                                      attention=f"Listen mode saw {names} contact a flagged host that has not been reviewed.")
                if view is not None and not (view.get("probeRunning") and view.get("dnsConnected")):
                    lost = "bpftrace" if not view.get("probeRunning") else "systemd-resolved's monitor"
                    return api.result("in", "listening in part", self.about,
                                      attention=f"Listen mode is running without {lost}, so it sees only part of what happens.")
                return api.result("in", "listening", self.about)
            if svc["enabled"]:
                return api.result("in", "not running", self.about,
                                  attention="Listen mode is switched on but its service is not running.")
            return api.result("out", "off", self.about)

        def apply(self, ctx, chk, rec):
            ctx.helper("listen-on")

        def revert(self, ctx, rec):
            ctx.helper("listen-off")

    return ListenRow()


# ------------------------------------------------------------------ the CLI

def status_text(rep):
    if not rep.get("enabled") and not rep.get("serviceActive"):
        return "Listen mode is off."
    state = "running" if rep.get("serviceActive") else "switched on but not running"
    lines = [f"Listen mode is {state}."]
    if rep.get("serviceActive"):
        since = rep.get("since")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(since)) if since else "unknown"
        lines.append(f"  Recording since {when}, keeping {rep.get('retentionHours')} hours.")
        lines.append(f"  {rep['contactCount']} connections to {rep['hostCount']} hosts, "
                     f"{rep['unknownCount']} of them matching no signature.")
        lines.append(f"  Unreviewed telemetry contacts: {rep['leakCount']}.")
        if not rep.get("probeRunning"):
            lines.append("  bpftrace is not running, so connections are not being seen.")
        if not rep.get("dnsConnected"):
            lines.append("  resolved's monitor is not connected, so host names are not being seen.")
    return "\n".join(lines)


def report_rows(view, signatures, hours, now):
    """Contacts seen in the last `hours`, grouped by program."""
    cutoff = now - hours * 3600 if hours else None
    progs = {}
    for c in (view or {}).get("contacts", []):
        if cutoff is not None and c["lastSeen"] < cutoff:
            continue
        host = c.get("host") if isinstance(c.get("host"), str) else None
        sig = match_host(host, signatures)
        entry = {"host": host or c.get("addr"), "named": bool(host),
                 "signature": sig[0] if sig else c.get("signature"),
                 "kind": sig[2] if sig else c.get("kind"),
                 "firstSeen": c["firstSeen"], "lastSeen": c["lastSeen"], "count": c["count"]}
        key = (c["program"], c.get("exe"))
        p = progs.setdefault(key, {"program": c["program"], "exe": c.get("exe"),
                                   "units": set(), "contacts": {}})
        if isinstance(c.get("unit"), str):
            p["units"].add(c["unit"])
        old = p["contacts"].get(entry["host"])
        if old is None:
            p["contacts"][entry["host"]] = entry
        else:
            old["firstSeen"] = min(old["firstSeen"], entry["firstSeen"])
            old["lastSeen"] = max(old["lastSeen"], entry["lastSeen"])
            old["count"] += entry["count"]
    out = []
    for p in progs.values():
        contacts = sorted(p["contacts"].values(), key=lambda e: (-e["count"], e["host"] or ""))
        out.append({"program": p["program"], "exe": p["exe"], "units": sorted(p["units"]),
                    "count": sum(e["count"] for e in contacts), "contacts": contacts})
    out.sort(key=lambda p: (-p["count"], p["program"]))
    return out


def cli(ctx, api, argv):
    ap = argparse.ArgumentParser(prog="black-ops listen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("report")
    p.add_argument("--hours", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("purge")
    p.add_argument("--status", action="store_true")
    try:
        args = ap.parse_args(argv[1:])
    except SystemExit as exc:
        return 0 if exc.code == 0 else 2
    if args.cmd == "status":
        rep = report(ctx, api)
        print(json.dumps(rep) if args.json else status_text(rep))
        return 0
    if args.cmd == "report":
        if args.hours < 0 or args.hours > 720:
            print("black-ops listen report: --hours takes 1 to 720", file=sys.stderr)
            return 2
        view = load_view(ctx, api)
        rows = report_rows(view, load_signatures(api), args.hours, int(time.time()))
        if args.json:
            print(json.dumps(rows))
            return 0
        if view is None:
            print("Listen mode has nothing recorded. Is it switched on and running?")
            return 0
        for r in rows:
            where = r["exe"] or "executable not known"
            units = f"  [{', '.join(r['units'])}]" if r["units"] else ""
            print(f"{r['program']}  ({where}){units}  {r['count']} connections")
            for e in r["contacts"]:
                mark = ""
                if e["signature"]:
                    mark = ("  RED " if e["kind"] in RED_KINDS else "  flag ") + e["signature"]
                elif not e["named"]:
                    mark = "  (no lookup seen)"
                else:
                    mark = "  new"
                last = time.strftime("%m-%d %H:%M", time.localtime(e["lastSeen"]))
                print(f"    {e['count']:>6}  {e['host']}  last {last}{mark}")
        return 0
    # purge
    try:
        out = ctx.helper("listen-purge")
    except api.ActionError as exc:
        print(f"black-ops listen purge: {exc}", file=sys.stderr)
        return 1
    # The report is always brought up to date, so summary.json, which
    # Security Scan reads, stops counting the purged contacts at once.
    rep = api.current_report(ctx)
    if args.status:
        print(json.dumps(rep))
    else:
        print(out or "listen-purge: purged")
    return 0
