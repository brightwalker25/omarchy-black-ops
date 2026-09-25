"""Listen mode: the root listener (system/listen) driven from fixtures, the
user side (lib/black_ops_listen.py) through bin/black-ops in the sandbox,
the three helper verbs through the stub sudo, and the installer's part.

Nothing here runs bpftrace, talks to systemd-resolved or needs root. The
listener's functions are called directly with canned varlink messages and
canned probe lines, and its folders are moved into pytest's temporary
folder."""
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import tomllib

import pytest

from conftest import REPO, load_module

DATADOG = "http-intake.logs.us5.datadoghq.com"
T0 = 1790000000                     # 2026-09-21 14:13:20 UTC
SERVICE = "omarchy-black-ops-listen.service"


@pytest.fixture
def L():
    """system/listen, imported."""
    return load_module("black_ops_listen_root", REPO / "system" / "listen")


def signatures(L):
    return L.load_signatures((REPO / "data" / "signatures.toml").read_text())


# ------------------------------------------------------------ fixtures: DNS

def wire_rr(name, rtype, ttl, rdata):
    """A resource record in DNS wire format, as resolved sends it in `raw`."""
    out = b""
    for label in name.rstrip(".").split("."):
        out += bytes([len(label)]) + label.encode()
    out += b"\0" + rtype.to_bytes(2, "big") + (1).to_bytes(2, "big")
    out += ttl.to_bytes(4, "big") + len(rdata).to_bytes(2, "big") + rdata
    return base64.b64encode(out).decode()


def a_answer(name, addr, ttl=300):
    parts = [int(p) for p in addr.split(".")]
    return {"rr": {"key": {"class": 1, "type": 1, "name": name}, "address": parts},
            "raw": wire_rr(name, 1, ttl, bytes(parts)), "ifindex": 3}


def aaaa_answer(name, addr, ttl=300):
    import ipaddress
    packed = ipaddress.IPv6Address(addr).packed
    return {"rr": {"key": {"class": 1, "type": 28, "name": name}, "address": list(packed)},
            "raw": wire_rr(name, 28, ttl, packed), "ifindex": 3}


def cname_answer(name, target, ttl=60):
    return {"rr": {"key": {"class": 1, "type": 5, "name": name}, "name": target},
            "raw": wire_rr(name, 5, ttl, b"\x00")}


def query(name, answers, qtype=1, state="success"):
    return {"parameters": {"state": state, "rcode": 0,
                           "question": [{"class": 1, "type": qtype, "name": name}],
                           "collectedQuestions": [{"class": 1, "type": qtype, "name": name}],
                           "answer": answers},
            "continues": True}


def stream(*msgs):
    return b"".join(json.dumps(m).encode() + b"\0" for m in msgs)


def probe_line(pid, uid, fam, port, addr, comm):
    """A line as the bpftrace probe prints it: the port in network order,
    read as a little-endian number."""
    raw = ((port & 0xFF) << 8) | (port >> 8)
    return f"C\t{pid}\t{uid}\t{fam}\t{raw}\t{addr}\t{comm}\n"


# ---------------------------------------------------------- varlink parsing

def test_varlink_messages_are_split_on_nul_across_reads(L):
    buf = L.VarlinkBuffer()
    data = stream({"parameters": {"ready": True}, "continues": True},
                  query("example.com", [a_answer("example.com", "93.184.216.34")]))
    cut = len(data) // 2
    first = buf.feed(data[:cut])
    second = buf.feed(data[cut:])
    msgs = first + second
    assert len(msgs) == 2 and msgs[0]["parameters"]["ready"] is True
    assert buf.buf == b""


def test_garbage_between_messages_is_skipped(L):
    buf = L.VarlinkBuffer()
    msgs = buf.feed(b"not json\0" + stream({"parameters": {"ready": True}}))
    assert msgs == [{"parameters": {"ready": True}}]


def test_the_ready_message_holds_no_answers(L):
    assert L.parse_query_result({"parameters": {"ready": True}, "continues": True}) == []


def test_a_and_aaaa_answers_with_their_ttls(L):
    msg = query("Example.COM.", [a_answer("example.com", "93.184.216.34", 3600)])
    assert L.parse_query_result(msg) == [("example.com", "93.184.216.34", 3600)]
    msg = query("example.com", [aaaa_answer("example.com", "2606:2800:220:1::248", 42)], qtype=28)
    assert L.parse_query_result(msg) == [("example.com", "2606:2800:220:1:0:0:0:248".replace(
        ":0:0:0:", "::"), 42)]


def test_a_cname_chain_is_reported_under_the_name_asked_for(L):
    msg = query(DATADOG, [cname_answer(DATADOG, "alb-logs-http-shard0.us5.datadoghq.com"),
                          a_answer("alb-logs-http-shard0.us5.datadoghq.com", "34.149.66.137", 60)])
    assert L.parse_query_result(msg) == [(DATADOG, "34.149.66.137", 60)]


def test_failed_lookups_and_other_types_give_nothing(L):
    assert L.parse_query_result(query("x.example", [], state="rcode-failure")) == []
    assert L.parse_query_result(query("x.example", [a_answer("x.example", "1.2.3.4")], qtype=65)) == []
    assert L.parse_query_result({"error": "io.systemd.System"}) == []


def test_a_record_without_raw_still_joins_with_the_floor(L):
    ans = a_answer("example.com", "93.184.216.34")
    del ans["raw"]
    assert L.parse_query_result(query("example.com", [ans])) == [("example.com", "93.184.216.34", None)]


def test_raw_ttl_reads_the_wire_format(L):
    assert L.raw_ttl(wire_rr("a.b.example", 1, 86400, b"\1\2\3\4")) == 86400
    assert L.raw_ttl("AAAA") is None
    assert L.raw_ttl("!!!") is None


# ------------------------------------------------------ bpftrace output

def test_probe_lines_are_parsed_and_the_port_turned_round(L):
    ev = L.parse_probe_line(probe_line(4242, 1000, 4, 443, "34.149.66.137", "claude"))
    assert ev == {"pid": 4242, "uid": 1000, "comm": "claude", "addr": "34.149.66.137", "port": 443}
    ev = L.parse_probe_line(probe_line(7, 0, 6, 8443, "2606:4700::1111", "Web Content"))
    assert ev["addr"] == "2606:4700::1111" and ev["port"] == 8443 and ev["comm"] == "Web Content"


def test_a_v4_mapped_v6_address_is_reported_as_v4(L):
    ev = L.parse_probe_line(probe_line(7, 0, 6, 443, "::ffff:1.2.3.4", "x"))
    assert ev["addr"] == "1.2.3.4"


def test_a_comm_with_a_tab_stays_whole(L):
    ev = L.parse_probe_line(probe_line(7, 0, 4, 80, "1.2.3.4", "odd\tname"))
    assert ev["comm"] == "odd\tname"


@pytest.mark.parametrize("line", [
    "", "Attaching 1 probe...\n", "C\tx\t0\t4\t0\t1.2.3.4\tc\n",
    "C\t1\t0\t4\t0\tnot-an-ip\tc\n", "C\t1\t0\t5\t0\t1.2.3.4\tc\n", "C\t1\t0\t4\t70000\t1.2.3.4\tc\n",
    "D\t1\t0\t4\t0\t1.2.3.4\tc\n",
])
def test_anything_else_from_bpftrace_is_ignored(L, line):
    assert L.parse_probe_line(line) is None


def test_loopback_and_the_stub_resolver_are_not_kept(L):
    keep = lambda addr, port=443: L.worth_keeping({"addr": addr, "port": port})
    assert not keep("127.0.0.53", 53) and not keep("::1") and not keep("0.0.0.0")
    assert keep("192.168.1.1") and keep("34.149.66.137") and not keep("1.2.3.4", 0)


def test_the_probe_scripts_print_what_the_parser_reads(L):
    for name, script in L.PROBES:
        assert script.count('printf("C\\t%d\\t%d\\t4\\t%d\\t%s\\t%s\\n"') == 1, name
        assert script.count('printf("C\\t%d\\t%d\\t6\\t%d\\t%s\\t%s\\n"') == 1, name
    assert "kprobe:security_socket_connect" in L.PROBE_KPROBE
    assert "tracepoint:syscalls:sys_enter_connect" in L.PROBE_TRACEPOINT


def test_the_unit_comes_from_the_cgroup(L):
    text = ("0::/user.slice/user-1000.slice/user@1000.service/app.slice/"
            "app-Hyprland-firefox@a1b2.scope\n")
    assert L.unit_of(text) == "app-Hyprland-firefox@a1b2.scope"
    assert L.unit_of("0::/system.slice/NetworkManager.service\n") == "NetworkManager.service"
    assert L.unit_of("0::/\n") is None and L.unit_of(None) is None


def test_exe_and_unit_are_read_from_proc_once(L, tmp_path):
    proc = tmp_path / "proc"
    (proc / "42").mkdir(parents=True)
    os.symlink("/usr/bin/someapp", proc / "42" / "exe")
    (proc / "42" / "cgroup").write_text("0::/user.slice/app.slice/app-someapp.scope\n")
    cache = L.ProcCache(str(proc))
    assert cache.get(42, "someapp", T0) == ("/usr/bin/someapp", "app-someapp.scope")
    (proc / "42" / "cgroup").write_text("0::/elsewhere.scope\n")
    assert cache.get(42, "someapp", T0 + 10)[1] == "app-someapp.scope"
    assert cache.get(42, "someapp", T0 + 61)[1] == "elsewhere.scope"
    assert cache.get(43, "gone", T0) == (None, None)


# ---------------------------------------------------------------- the join

def test_a_connection_is_named_by_the_lookup_before_it(L):
    j = L.Joiner()
    j.add(DATADOG, "34.149.66.137", 60, T0)
    assert j.lookup("34.149.66.137", T0 + 5) == DATADOG
    # The floor keeps an answer past a short TTL, and no longer.
    assert j.lookup("34.149.66.137", T0 + L.JOIN_FLOOR) == DATADOG
    assert j.lookup("34.149.66.137", T0 + L.JOIN_FLOOR + 1) is None
    assert j.lookup("1.1.1.1", T0) is None


def test_a_long_ttl_is_kept_and_capped(L):
    j = L.Joiner()
    j.add("a.example", "1.2.3.4", 3600, T0)
    assert j.lookup("1.2.3.4", T0 + 3599) == "a.example"
    j.add("b.example", "5.6.7.8", 10 ** 6, T0)
    assert j.lookup("5.6.7.8", T0 + L.JOIN_CEILING + 1) is None


def test_the_latest_lookup_of_a_shared_address_wins(L):
    j = L.Joiner()
    j.add("one.example", "1.2.3.4", 300, T0)
    j.add("two.example", "1.2.3.4", 300, T0 + 1)
    assert j.lookup("1.2.3.4", T0 + 2) == "two.example"


def test_the_join_table_is_bounded(L, monkeypatch):
    monkeypatch.setattr(L, "JOIN_MAX_ENTRIES", 3)
    j = L.Joiner()
    for i in range(5):
        j.add(f"h{i}.example", f"10.0.0.{i}", 300, T0)
    assert len(j.by_addr) == 3 and j.lookup("10.0.0.4", T0) == "h4.example"


# -------------------------------------------------------------- the store

@pytest.fixture
def store(L, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SHRED", str(tmp_path / "no-shred"))
    s = L.Store(str(tmp_path / "run"), str(tmp_path / "keep"), False, os.getgid())
    s.prepare()
    return s


def listener(L, store, now=T0):
    lst = L.Listener({"retention": 72, "account": None, "keep": False}, signatures(L), store, now)
    lst.procs = L.ProcCache("/nonexistent-proc")
    return lst


def test_the_folders_have_the_contract_modes(L, store, tmp_path):
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
    assert mode(tmp_path / "run") == 0o750
    assert mode(tmp_path / "run/view") == 0o750
    assert mode(tmp_path / "run/segments") == 0o700
    assert not (tmp_path / "keep").exists()


def test_events_are_joined_counted_and_written(L, store, tmp_path):
    lst = listener(L, store)
    lst.on_answers(L.parse_query_result(query(DATADOG, [a_answer(DATADOG, "34.149.66.137", 60)])), T0)
    for i in range(3):
        lst.on_connect(L.parse_probe_line(probe_line(42, 1000, 4, 443, "34.149.66.137", "claude")),
                       T0 + 10 * i)
    lst.on_connect(L.parse_probe_line(probe_line(43, 1000, 4, 443, "9.9.9.9", "curl")), T0 + 30)
    assert lst.on_connect(L.parse_probe_line(probe_line(44, 1000, 4, 53, "127.0.0.53", "x")),
                          T0) is None
    store.flush()
    lst.write_view(T0 + 40)

    seg = tmp_path / "run/segments" / L.segment_name(T0)
    assert stat.S_IMODE(os.stat(seg).st_mode) == 0o600
    lines = [json.loads(l) for l in seg.read_text().splitlines()]
    assert [l["src"] for l in lines] == ["resolve", "connect", "connect", "connect", "connect"]
    assert list(lines[1]) == ["t", "src", "pid", "comm", "exe", "unit", "uid", "host", "addr", "port"]
    assert lines[1]["host"] == DATADOG and lines[4]["host"] is None

    view_file = tmp_path / "run/view/contacts.json"
    assert stat.S_IMODE(os.stat(view_file).st_mode) == 0o640
    view = json.loads(view_file.read_text())
    assert view["schema"] == 1 and view["retentionHours"] == 72 and view["segments"] == 1
    by_prog = {c["program"]: c for c in view["contacts"]}
    c = by_prog["claude"]
    assert (c["host"], c["signature"], c["kind"], c["count"]) == (DATADOG, "datadog-intake", "telemetry", 3)
    assert (c["firstSeen"], c["lastSeen"]) == (T0, T0 + 20)
    # A connection with no lookup keeps a null host, and its address.
    assert by_prog["curl"]["host"] is None and by_prog["curl"]["addr"] == "9.9.9.9"
    assert by_prog["curl"]["signature"] is None


def test_a_lookup_is_written_once_an_hour(L, store, tmp_path):
    lst = listener(L, store)
    answers = [("example.com", "93.184.216.34", 300)]
    for i in range(5):
        lst.on_answers(answers, T0 + i)
    store.flush()
    seg = (tmp_path / "run/segments" / L.segment_name(T0)).read_text()
    assert seg.count('"resolve"') == 1


# ---------------------------------------------------- retention and shred

def test_segment_names_are_utc_hours(L):
    assert L.segment_name(T0) == "2026092114.jsonl"
    assert L.segment_start("2026092114.jsonl") == T0 - T0 % 3600
    assert L.segment_start("notes.txt") is None and L.segment_start("2026099999.jsonl") is None


def test_only_segments_past_the_retention_expire(L):
    hour = T0 - T0 % 3600
    names = [L.segment_name(hour - h * 3600) for h in range(0, 80)]
    old = L.expired(names, hour + 1800, 72)
    # Half an hour into the current hour, the window reaches back to 71.5
    # hours before its start. The hour that began 72 hours before it ended
    # 71 hours before, inside the window, so it is kept; the one before it
    # ended 72 hours before and goes.
    assert L.segment_name(hour - 73 * 3600) in old
    assert L.segment_name(hour - 72 * 3600) not in old
    assert len(old) == 80 - 73
    assert L.expired(names, hour + 1800, 1) == sorted(names[2:])
    assert L.segment_name(hour) not in L.expired(names, hour + 1, 1)


def test_the_next_prune_is_on_the_hour(L):
    assert L.next_hour(T0) % 3600 == 0 and 0 < L.next_hour(T0) - T0 <= 3600
    assert L.next_hour(T0 - T0 % 3600) == T0 - T0 % 3600 + 3600


def test_pruning_wipes_old_segments_and_drops_their_counts(L, store, tmp_path):
    lst = listener(L, store)
    old_t = T0 - 80 * 3600
    lst.on_connect(L.parse_probe_line(probe_line(1, 0, 4, 443, "1.2.3.4", "old")), old_t)
    lst.on_connect(L.parse_probe_line(probe_line(1, 0, 4, 443, "1.2.3.4", "new")), T0)
    store.flush()
    old_file = tmp_path / "run/segments" / L.segment_name(old_t)
    assert old_file.exists()
    removed = lst.prune(T0)
    assert removed == [L.segment_name(old_t)]
    assert not old_file.exists()
    assert [c["program"] for c in lst.view(T0)["contacts"]] == ["new"]


def test_wipe_overwrites_before_it_unlinks(L, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SHRED", str(tmp_path / "no-shred"))
    f = tmp_path / "seg"
    f.write_bytes(b"secret" * 100)
    seen = []
    real_unlink = os.unlink

    def spy(path, *a, **kw):
        seen.append(open(path, "rb").read())
        return real_unlink(path, *a, **kw)
    monkeypatch.setattr(L.os, "unlink", spy)
    L.wipe(str(f))
    assert not f.exists() and seen == [b"\0" * 600]


def test_wipe_uses_shred_when_it_is_there(L, tmp_path, monkeypatch):
    log = tmp_path / "shred.log"
    fake = tmp_path / "shred"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nrm -f -- \"$3\"\n")
    fake.chmod(0o755)
    monkeypatch.setattr(L, "SHRED", str(fake))
    f = tmp_path / "seg"
    f.write_text("x")
    L.wipe(str(f))
    assert not f.exists() and log.read_text().split() == ["-fuz", "--", str(f)]


def test_purge_empties_memory_and_every_store(L, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SHRED", str(tmp_path / "no-shred"))
    s = L.Store(str(tmp_path / "run"), str(tmp_path / "keep"), True, os.getgid())
    s.prepare()
    lst = listener(L, s)
    lst.on_answers([("example.com", "1.2.3.4", 300)], T0)
    lst.on_connect(L.parse_probe_line(probe_line(1, 0, 4, 443, "1.2.3.4", "x")), T0)
    s.flush()
    lst.write_view(T0)
    assert list((tmp_path / "keep/segments").iterdir())
    lst.purge()
    lst.write_view(T0)
    assert not list((tmp_path / "keep/segments").iterdir())
    assert json.loads((tmp_path / "run/view/contacts.json").read_text())["contacts"] == []
    assert lst.joiner.lookup("1.2.3.4", T0) is None


def test_a_restart_with_the_disk_store_counts_what_is_kept(L, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SHRED", str(tmp_path / "no-shred"))
    s = L.Store(str(tmp_path / "run"), str(tmp_path / "keep"), True, os.getgid())
    s.prepare()
    lst = listener(L, s)
    for i in range(4):
        lst.on_connect(L.parse_probe_line(probe_line(1, 0, 4, 443, "1.2.3.4", "x")), T0 + i)
    s.flush()
    again = listener(L, s, T0 + 100)
    again.reload(T0 + 100)
    [c] = again.view(T0 + 100)["contacts"]
    assert c["count"] == 4 and c["firstSeen"] == T0


@pytest.mark.parametrize("text, want", [
    ("", {"retention": 72, "account": None, "keep": False}),
    ("RetentionHours=24\nAccount=alice\nKeepAcrossReboot=yes\n",
     {"retention": 24, "account": "alice", "keep": True}),
    ("RetentionHours=0\n", {"retention": 1, "account": None, "keep": False}),
    ("RetentionHours=100000\n", {"retention": 720, "account": None, "keep": False}),
    ("RetentionHours=-3\nAccount=Bad Name\n", {"retention": 72, "account": None, "keep": False}),
])
def test_listen_conf(L, text, want):
    assert L.parse_conf(text) == want


# ------------------------------------------------------ signature matching

@pytest.mark.parametrize("host, sig", [
    (DATADOG, "datadog-intake"),
    ("HTTP-INTAKE.LOGS.US5.DATADOGHQ.COM.", "datadog-intake"),
    ("o4507954455314432.ingest.us.sentry.io", "sentry-ingest"),
    ("mobile.events.data.microsoft.com", "microsoft-1ds"),
    ("datadoghq.com", None),
    ("example.com", None),
    ("", None),
    (None, None),
])
def test_hosts_match_signatures_by_the_contract_rule(L, host, sig):
    assert L.match_host(host, signatures(L))[0] == sig


def test_the_listener_and_the_user_side_match_alike(L, bo):
    user = bo.EXT["listen"]
    sigs_root = signatures(L)
    sigs_user = user.load_signatures(bo.API)
    data = tomllib.loads((REPO / "data" / "signatures.toml").read_text())
    hosts = ["example.com", "www.google-analytics.com", "api.segment.io", DATADOG]
    for sig in data["signature"]:
        hosts += [h.replace("*", "x.y") for h in sig["hosts"]]
    for h in hosts:
        root = L.match_host(h, sigs_root)
        mine = user.match_host(h, sigs_user)
        assert root[0] == (mine[0] if mine else None), h


# ------------------------------------------------ the user side, sandboxed

STUB_SYSTEMCTL = """\
#!{py}
import os, sys
root = os.environ["BLACK_OPS_FAKE_ROOT"]
with open(os.path.join(root, "calls.log"), "a") as fh:
    fh.write("systemctl " + " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
state_file = os.path.join(root, "listen-state")
try:
    load, enabled, active = open(state_file).read().split()
except OSError:
    load, enabled, active = "loaded", "disabled", "inactive"
unit = "omarchy-black-ops-listen.service"
def save():
    open(state_file, "w").write(" ".join((load, enabled, active)))
if args and args[-1] == unit:
    if args[0] == "show":
        print("LoadState=" + load)
        print("UnitFileState=" + enabled)
        print("ActiveState=" + active)
    elif args[:2] == ["enable", "--now"]:
        enabled, active = "enabled", "active"
        save()
    elif args[:2] == ["disable", "--now"]:
        enabled, active = "disabled", "inactive"
        save()
    elif args[0] == "is-active":
        sys.exit(0 if active == "active" else 3)
    sys.exit(0)
if args[:2] == ["--user", "is-active"]:
    print("inactive")
    sys.exit(3)
sys.exit(0)
"""


class Listen:
    """The sandbox, with what listen mode needs to be available."""

    def __init__(self, sandbox):
        self.box = sandbox
        sandbox.stock_machine()
        sandbox.stub("systemctl", STUB_SYSTEMCTL.format(py=sys.executable))
        sandbox.stub("bpftrace", "#!/bin/sh\nexit 0\n")
        sock = sandbox.root / "run/systemd/resolve/io.systemd.Resolve.Monitor"
        sandbox.write(sock, "")
        # The unit the installer would have put in place.
        sandbox.write(sandbox.etc / "systemd/system" / SERVICE,
                      (REPO / "system" / SERVICE).read_text())
        self.run_dir = sandbox.root / "run/black-ops-listen"

    def state(self, load="loaded", enabled="disabled", active="inactive"):
        (self.box.root / "listen-state").write_text(f"{load} {enabled} {active}")

    def view(self, contacts, **extra):
        doc = {"schema": 1, "generatedAt": T0 + 600, "since": T0 - 3600, "retentionHours": 72,
               "segments": 2, "probe": "kprobe", "probeRunning": True, "dnsConnected": True,
               "contacts": contacts}
        doc.update(extra)
        self.box.write(self.run_dir / "view/contacts.json", json.dumps(doc))
        seg = self.run_dir / "segments/2026092114.jsonl"
        self.box.write(seg, '{"t":1790000000,"src":"connect"}\n')


def contact(program="someapp", host=DATADOG, count=4, exe="/usr/bin/someapp", **kw):
    c = {"program": program, "exe": exe, "unit": f"app-{program}.scope", "host": host,
         "signature": None, "kind": None, "firstSeen": T0, "lastSeen": T0 + 500, "count": count}
    c.update(kw)
    return c


@pytest.fixture
def lb(sandbox):
    return Listen(sandbox)


def rows(rep):
    return {r["id"]: r for r in rep["rows"]}


def on(run, lb):
    run("on")
    rep = run("row", "listen", "on")
    return rep


def test_the_row_is_optional_privileged_and_off_by_default(run, lb):
    rep = run("status")
    r = rows(rep)["listen"]
    assert r["optional"] and r["privileged"] and not r["intended"]
    assert r["status"] == "off" and r["colour"] == "grey"
    assert rep["listen"]["available"] is True and rep["listen"]["enabled"] is False
    rep = run("on")
    assert rows(rep)["listen"]["status"] == "off"      # the main switch leaves it off
    assert not any(v.startswith("listen") for v in lb.box.helper_verbs())


def test_not_applicable_without_bpftrace(run, lb):
    (lb.box.bin / "bpftrace").unlink()
    r = rows(run("status"))["listen"]
    assert r["status"] == "na" and "pacman -S bpftrace" in r["detail"]


def test_not_applicable_without_the_monitor_socket(run, lb):
    (lb.box.root / "run/systemd/resolve/io.systemd.Resolve.Monitor").unlink()
    assert rows(run("status"))["listen"]["status"] == "na"


def test_switching_on_and_off_goes_through_the_helper(run, lb):
    rep = on(run, lb)
    assert lb.box.helper_verbs()[-1] == "listen-on"
    assert f"systemctl enable --now {SERVICE}" in lb.box.calls("systemctl")
    r = rows(rep)["listen"]
    assert r["status"] == "ok" and r["colour"] == "green" and r["value"] == "listening"
    lb.view([contact(host="example.com")])
    lb.box.clear_calls()
    rep = run("row", "listen", "off")
    assert lb.box.helper_verbs() == ["listen-off"]
    assert f"systemctl disable --now {SERVICE}" in lb.box.calls("systemctl")
    # listen-off purges as well: nothing recorded is left.
    assert list((lb.run_dir / "segments").iterdir()) == []
    # A stopped listener's view is rebuilt empty.
    assert json.loads((lb.run_dir / "view/contacts.json").read_text())["contacts"] == []
    assert rows(rep)["listen"]["status"] == "off"


def test_listen_on_refuses_when_the_service_is_not_installed(run, lb):
    (lb.box.etc / "systemd/system" / SERVICE).unlink()
    rep = on(run, lb)
    assert "not installed" in rows(rep)["listen"]["error"]


def test_purge_wipes_and_signals_a_running_listener(run, lb, bo, capsys):
    on(run, lb)
    lb.view([contact()])
    lb.box.clear_calls()
    capsys.readouterr()
    assert bo.main(["listen", "purge", "--status"], lb.box.env) == 0
    rep = json.loads(capsys.readouterr().out)
    assert lb.box.helper_verbs() == ["listen-purge"]
    assert f"systemctl kill --kill-whom=main --signal=SIGUSR1 {SERVICE}" in lb.box.calls("systemctl")
    assert list((lb.run_dir / "segments").iterdir()) == []
    assert rep["flagged"] == [] and rep["overall"] == "ok"


def test_purge_leaves_an_empty_view_when_the_listener_is_stopped(run, lb, bo, capsys):
    on(run, lb)
    lb.view([contact()])
    lb.state(enabled="enabled", active="failed")
    assert bo.main(["listen", "purge"], lb.box.env) == 0
    assert "listen-purge: purged" in capsys.readouterr().out
    view = json.loads((lb.run_dir / "view/contacts.json").read_text())
    assert view["contacts"] == [] and view["retentionHours"] == 72
    assert stat.S_IMODE(os.stat(lb.run_dir / "view/contacts.json").st_mode) == 0o640


def test_a_plain_purge_brings_the_summary_up_to_date(run, lb, bo, capsys):
    on(run, lb)
    lb.view([contact()])
    run("status", "--notify")
    summary = lb.box.home / ".local/state/black-ops/summary.json"
    assert json.loads(summary.read_text())["listen"]["leaks"] == 1
    assert bo.main(["listen", "purge"], lb.box.env) == 0
    capsys.readouterr()
    assert json.loads(summary.read_text())["listen"]["leaks"] == 0


def test_a_telemetry_contact_is_one_red_item(run, lb):
    on(run, lb)
    lb.view([contact(), contact(host="example.com", count=9)])
    rep = run("status")
    assert rep["overall"] == "leak" and rep["colour"] == "red"
    r = rows(rep)["listen"]
    assert r["status"] == "leak" and r["colour"] == "red"
    assert r["why"] == "Listen mode saw someapp contact a telemetry host."
    assert rep["leaks"] == ["listen"]
    [item] = rep["flagged"]
    want_id = hashlib.sha256("\0".join(["listen", "contact", "/usr/bin/someapp", DATADOG,
                                        "datadog-intake"]).encode()).hexdigest()[:16]
    assert item["id"] == want_id
    assert item["match"] == {"signature": "datadog-intake", "vendor": "Datadog", "kind": "telemetry",
                             "pattern": "http-intake.logs.*.datadoghq.com"}
    assert item["source"] == "listen" and item["kind"] == "contact" and item["severity"] == "leak"
    assert item["colour"] == "red" and item["active"] is True
    assert (item["program"], item["exe"], item["host"]) == ("someapp", "/usr/bin/someapp", DATADOG)
    assert (item["signature"], item["vendor"]) == ("datadog-intake", "Datadog")
    assert (item["firstSeen"], item["lastSeen"], item["count"]) == (T0, T0 + 500, 4)
    assert DATADOG not in item["summary"] and len(item["summary"]) < 120
    assert set(item) >= {"id", "source", "kind", "severity", "program", "exe", "package", "path",
                         "host", "signature", "vendor", "summary", "firstSeen", "lastSeen",
                         "count", "reviewed", "verdict", "active", "colour"}
    lst = rep["listen"]
    assert lst["enabled"] and lst["serviceActive"] and lst["available"]
    assert (lst["contactCount"], lst["hostCount"], lst["unknownCount"], lst["leakCount"]) == (13, 2, 1, 1)
    assert (lst["since"], lst["retentionHours"], lst["segments"]) == (T0 - 3600, 72, 2)


def test_red_wins_over_amber(run, lb):
    on(run, lb)
    lb.box.dns_dropin.unlink() if lb.box.dns_dropin.exists() else None
    lb.box.write(lb.box.hosts, lb.box.hosts.read_text().replace(DATADOG, "x.invalid"))
    lb.view([contact()])
    rep = run("status")
    assert rep["overall"] == "leak" and rep["colour"] == "red"


def test_a_reviewed_contact_turns_grey(run, lb):
    on(run, lb)
    lb.view([contact()])
    item = run("status")["flagged"][0]
    lb.box.write(lb.box.home / ".local/state/black-ops/reviewed.toml",
                 f'schema = 1\n\n[items."{item["id"]}"]\nverdict = "allowed"\nat = {T0 + 600}\n')
    rep = run("status")
    assert rep["flagged"][0]["colour"] == "grey" and rep["flagged"][0]["reviewed"] is True
    assert rep["overall"] == "ok" and rows(rep)["listen"]["status"] == "ok"
    assert rep["listen"]["leakCount"] == 0


def test_other_signature_kinds_are_amber_and_unknown_hosts_neutral(run, lb):
    on(run, lb)
    data = tomllib.loads((REPO / "data/signatures.toml").read_text())
    amber = next(s for s in data["signature"] if s["kind"] not in ("telemetry", "analytics", "crash-report"))
    host = amber["hosts"][0].replace("*", "a")
    lb.view([contact(host=host), contact(program="curl", host=None, addr="9.9.9.9"),
             contact(program="firefox", host="example.org")])
    rep = run("status")
    [item] = rep["flagged"]
    assert item["severity"] == "warn" and item["colour"] == "amber" and item["signature"] == amber["id"]
    # The row raises its own status: amber for an unreviewed flagged contact.
    r = rows(rep)["listen"]
    assert rep["overall"] == "warn" and r["status"] == "warn" and r["colour"] == "amber"
    assert "has not been reviewed" in r["why"] and rep["attention"] == ["listen"]
    assert rep["listen"]["unknownCount"] == 2
    lb.box.write(lb.box.home / ".local/state/black-ops/reviewed.toml",
                 f'schema = 1\n\n[items."{item["id"]}"]\nverdict = "false-positive"\nat = {T0}\n')
    rep = run("status")
    assert rep["overall"] == "ok" and rows(rep)["listen"]["status"] == "ok"


def test_items_split_by_unit_are_one_item(run, lb):
    on(run, lb)
    lb.view([contact(unit="app-a.scope", count=2), contact(unit="app-b.scope", count=3,
                                                          firstSeen=T0 - 50, lastSeen=T0 + 900)])
    [item] = run("status")["flagged"]
    assert (item["count"], item["firstSeen"], item["lastSeen"]) == (5, T0 - 50, T0 + 900)


def test_an_unknown_exe_falls_back_to_the_program_for_the_id(run, lb):
    on(run, lb)
    lb.view([contact(exe=None)])
    [item] = run("status")["flagged"]
    assert item["id"] == hashlib.sha256("\0".join(["listen", "contact", "someapp", DATADOG,
                                                  "datadog-intake"]).encode()).hexdigest()[:16]


def test_nothing_is_flagged_while_the_row_is_off(run, lb):
    run("on")
    lb.state(enabled="enabled", active="active")
    lb.view([contact()])
    rep = run("status")
    assert rep["flagged"] == [] and rep["overall"] == "ok"


def test_enabled_but_not_running_needs_attention(run, lb):
    on(run, lb)
    lb.state(enabled="enabled", active="failed")
    rep = run("status")
    r = rows(rep)["listen"]
    assert r["status"] == "warn" and "not running" in r["why"]
    assert rep["attention"] == ["listen"]


def test_a_dead_probe_needs_attention(run, lb):
    on(run, lb)
    lb.view([], probeRunning=False)
    r = rows(run("status"))["listen"]
    assert r["status"] == "warn" and "bpftrace" in r["why"]


def test_a_broken_view_reads_as_empty(run, lb):
    on(run, lb)
    lb.box.write(lb.run_dir / "view/contacts.json", "{not json")
    rep = run("status")
    assert rep["flagged"] == [] and rep["listen"]["contactCount"] == 0


def test_the_summary_holds_counts_and_no_host(run, lb):
    on(run, lb)
    lb.view([contact(), contact(program="firefox", host="example.org", count=3)])
    run("status", "--notify")
    text = (lb.box.home / ".local/state/black-ops/summary.json").read_text()
    s = json.loads(text)
    assert s["listen"] == {"enabled": True, "leaks": 1, "unknownHosts": 1, "retentionHours": 72}
    for word in (DATADOG, "datadoghq", "example.org", "someapp", "firefox", "/usr/bin"):
        assert word not in text


def test_notifications_name_the_program_and_never_the_host(run, lb):
    on(run, lb)
    lb.view([contact()])
    run("status", "--notify")
    notes = lb.box.calls("notify-send")
    assert any("someapp contacted a telemetry host" in n for n in notes)
    assert not any(DATADOG in n for n in notes)


def test_listen_status_and_report_commands(run, lb, bo, capsys):
    on(run, lb)
    lb.view([contact(), contact(program="curl", host=None, addr="9.9.9.9", exe=None)])
    capsys.readouterr()
    assert bo.main(["listen", "status", "--json"], lb.box.env) == 0
    assert json.loads(capsys.readouterr().out)["leakCount"] == 1
    assert bo.main(["listen", "status"], lb.box.env) == 0
    assert "Listen mode is running." in capsys.readouterr().out
    assert bo.main(["listen", "report", "--json"], lb.box.env) == 0
    progs = {p["program"]: p for p in json.loads(capsys.readouterr().out)}
    assert progs["someapp"]["contacts"][0]["signature"] == "datadog-intake"
    assert progs["curl"]["contacts"][0]["host"] == "9.9.9.9"
    assert bo.main(["listen", "report"], lb.box.env) == 0
    out = capsys.readouterr().out
    assert "RED datadog-intake" in out and "(no lookup seen)" in out


def test_listen_command_usage_errors_exit_2(lb, bo, capsys):
    assert bo.main(["listen"], lb.box.env) == 2
    assert bo.main(["listen", "frobnicate"], lb.box.env) == 2
    assert bo.main(["listen", "report", "--hours", "x"], lb.box.env) == 2
    assert bo.main(["listen", "report", "--hours", "9999"], lb.box.env) == 2


# ----------------------------------------------- helper verbs and installer

def test_the_three_verbs_are_in_both_lists(helper):
    text = (REPO / "bin" / "black-ops-install").read_text()
    block = re.search(r"VERBS=\((.*?)\)", text, re.S).group(1).split()
    for verb in ("listen-on", "listen-off", "listen-purge"):
        assert verb in helper.VERBS and verb in block
        assert helper.parse_verb(["apply", verb]) == verb


def test_the_helper_refuses_to_wipe_a_folder_others_can_write(helper, tmp_path, monkeypatch):
    d = tmp_path / "run/black-ops-listen/segments"
    d.mkdir(parents=True)
    (d / "x.jsonl").write_text("x")
    d.chmod(0o777)
    monkeypatch.setattr(helper, "TRUSTED_UID", os.getuid())
    with pytest.raises(helper.HelperError):
        helper.wipe_folder(str(d))
    assert (d / "x.jsonl").exists()


def installer(*args):
    return subprocess.run(["bash", str(REPO / "bin/black-ops-install"), *args],
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})


def test_the_installer_puts_listen_mode_in_place_disabled():
    # A dry run from your own account names your own account.
    import getpass
    r = installer("--dry-run", "--listen-retention", "24", "--listen-keep", "yes")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "/usr/local/lib/omarchy-black-ops/listen" in out
    assert "/usr/local/lib/omarchy-black-ops/signatures.toml" in out
    assert "/etc/systemd/system/omarchy-black-ops-listen.service" in out
    assert "RetentionHours=24" in out and f"Account={getpass.getuser()}" in out and "KeepAcrossReboot=yes" in out
    assert "chattr +C /var/log/black-ops-listen" in out
    assert "systemctl daemon-reload" in out
    assert "enable" not in out.replace("disabled", "")


@pytest.mark.parametrize("value", ["0", "721", "x", "-1", "1e3"])
def test_the_installer_refuses_a_bad_retention(value):
    r = installer("--dry-run", "--listen-retention", value)
    assert r.returncode != 0 and "1 to 720" in r.stderr


def test_the_installer_refuses_a_bad_keep_value():
    assert installer("--dry-run", "--listen-keep", "maybe").returncode != 0


def test_the_listen_part_of_the_installer_stays_between_its_markers():
    text = (REPO / "bin/black-ops-install").read_text()
    inside = text.split("# ---- listen ", 1)[1].split("# ---- end listen", 1)[0]
    # Uninstall has to name the service to remove it, so it is left out.
    uninstall = text.split('if [ "$UNINSTALL" -eq 1 ]; then', 1)[1].split("\nfi\n", 1)[0]
    outside = text.replace(inside, "").replace(uninstall, "")
    for word in ("omarchy-black-ops-listen.service", "listen.conf", "system/listen"):
        assert word in inside and word not in outside


def test_the_unit_keeps_the_contract_and_is_hardened():
    unit = (REPO / "system" / SERVICE).read_text()
    lines = {l.strip() for l in unit.splitlines()}
    for want in ("ExecStart=/usr/bin/python3 -I /usr/local/lib/omarchy-black-ops/listen",
                 "RuntimeDirectory=black-ops-listen", "RuntimeDirectoryMode=0750",
                 "RuntimeDirectoryPreserve=no", "ProtectSystem=strict", "ProtectHome=yes",
                 "PrivateNetwork=no", "NoNewPrivileges=yes", "After=systemd-resolved.service",
                 "StandardOutput=null", "LogLevelMax=warning", "RestrictAddressFamilies=AF_UNIX",
                 "IPAddressDeny=any", "Restart=on-failure"):
        assert want in lines, want
    caps = next(l for l in lines if l.startswith("CapabilityBoundingSet=")).split("=", 1)[1].split()
    assert "CAP_NET_ADMIN" not in caps and "CAP_SYS_MODULE" not in caps and "CAP_NET_RAW" not in caps


def test_the_listener_opens_no_network_socket():
    text = (REPO / "system" / "listen").read_text()
    assert "AF_INET" not in text and "socket.AF_UNIX" in text
    assert "urllib" not in text and "http.client" not in text


def test_items_carry_their_source_themselves(bo):
    """So that they survive a core that checks for the field."""
    user = bo.EXT["listen"]
    view = {"contacts": [contact()]}
    [item] = user.items_from(view, user.load_signatures(bo.API))
    assert item["source"] == "listen" and item["match"]["signature"] == "datadog-intake"


# ------------------------------------------- the listener's loop, end to end

RUNNER = """\
import sys
sys.path.insert(0, {tests!r})
from conftest import load_module
L = load_module("listen_root", {listen!r})
L.CONF = {conf!r}
L.SIGNATURES = {sigs!r}
L.RUN_DIR = {run!r}
L.KEEP_DIR = {keep!r}
L.MONITOR = {sock!r}
L.BPFTRACE = {bpftrace!r}
L.SHRED = "/nonexistent"
L.PROC = {proc!r}
L.FLUSH_RUN = 0.5
sys.exit(L.run())
"""


def test_the_listener_joins_live_sources_and_purges_on_sigusr1(tmp_path):
    """The whole loop, with a fake resolved monitor on a Unix socket and a
    fake bpftrace that prints one connection. It runs as the user, in a
    child process, against folders in the test's temporary folder."""
    import signal
    import socket
    import threading

    sock_path = str(tmp_path / "monitor.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    got = {}

    def serve():
        conn, _ = srv.accept()
        got["request"] = conn.recv(65536)
        conn.sendall(stream({"parameters": {"ready": True}, "continues": True},
                            query(DATADOG, [a_answer(DATADOG, "34.149.66.137", 60)])))
        got["done"] = threading.Event()
        got["done"].wait(30)
        conn.close()
    t = threading.Thread(target=serve, daemon=True)
    t.start()

    bpftrace = tmp_path / "bpftrace"
    bpftrace.write_text("#!/bin/sh\nsleep 1\nprintf '" +
                        probe_line(4242, 1000, 4, 443, "34.149.66.137", "claude").replace("\t", "\\t")
                        .replace("\n", "\\n") + "'\nexec sleep 60\n")
    bpftrace.chmod(0o755)
    conf = tmp_path / "listen.conf"
    conf.write_text("RetentionHours=5\n")
    run_dir = tmp_path / "run"
    script = RUNNER.format(tests=str(REPO / "tests"), listen=str(REPO / "system/listen"),
                           conf=str(conf), sigs=str(REPO / "data/signatures.toml"),
                           run=str(run_dir), keep=str(tmp_path / "keep"), sock=sock_path,
                           bpftrace=str(bpftrace), proc=str(tmp_path / "proc"))
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    view_file = run_dir / "view/contacts.json"

    def wait_for(pred, secs=15):
        end = time.time() + secs
        while time.time() < end:
            try:
                doc = json.loads(view_file.read_text())
                if pred(doc):
                    return doc
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        child.kill()
        raise AssertionError(child.communicate())

    try:
        doc = wait_for(lambda d: d["contacts"])
        [c] = doc["contacts"]
        assert (c["program"], c["host"], c["signature"], c["count"]) == ("claude", DATADOG,
                                                                          "datadog-intake", 1)
        assert doc["retentionHours"] == 5 and doc["probe"] == "kprobe"
        assert json.loads(got["request"].rstrip(b"\0"))["method"] == \
            "io.systemd.Resolve.Monitor.SubscribeQueryResults"
        assert list((run_dir / "segments").iterdir())
        child.send_signal(signal.SIGUSR1)
        wait_for(lambda d: d["contacts"] == [])
        assert list((run_dir / "segments").iterdir()) == []
        child.send_signal(signal.SIGTERM)
        out, err = child.communicate(timeout=15)
        assert child.returncode == 0, err
        # Nothing it printed names a host or a program.
        assert b"datadog" not in out + err and b"claude" not in out + err
    finally:
        if child.poll() is None:
            child.kill()
        if "done" in got:
            got["done"].set()
        srv.close()


def test_a_probe_that_keeps_failing_is_retried_with_the_other_probe(L, capsys):
    p = L.Probe()
    for _ in range(2):
        p.started = time.monotonic()
        p.failed()
    assert p.name == "tracepoint" and p.retry_at > time.monotonic()
    # A probe that ran for a while before it died starts the count again.
    p.started = time.monotonic() - 3600
    p.failed()
    assert p.fails == 1 and p.name == "tracepoint"
    assert p.retry_at - time.monotonic() <= 2.1
    err = capsys.readouterr().err
    assert err.startswith("<4>black-ops listen: bpftrace stopped")


def test_bpftrace_missing_is_a_failure_not_a_crash(L, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "BPFTRACE", str(tmp_path / "missing"))
    p = L.Probe()
    assert p.start() is None and p.proc is None and p.fails == 1
