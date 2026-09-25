"""The upgrade from 0.1 to 0.2 on a machine that had 0.1 switched on.

0.2 dropped the rows for app stacks that are not part of stock Omarchy. The
protections those rows stood for must stay in place, now owned by the apps
concerned, so the upgrade forgets the rows without reverting them, and the
hosts block gives up the lines it no longer owns without unblocking them.
Until the helper is reinstalled, the old one is never run, because its
hosts-off would remove those lines."""
import json

import pytest

from conftest import HOSTS_01, HOSTS_01_OLLAMA, STOCK_HOSTS, state_01

DATADOG = "http-intake.logs.us5.datadoghq.com"
KEPT = {"hosts", "dns", "weather", "agents", "claude"}
REMOVED = ("onnx", "ollama-offline", "ollama-block", "openwebui", "proton")
NIGHTLOOM_LINES = """\
# onnxruntime telemetry and ComfyUI Sentry, blocked for Nightloom
0.0.0.0 mobile.events.data.microsoft.com
:: mobile.events.data.microsoft.com
0.0.0.0 o4507954455314432.ingest.us.sentry.io
:: o4507954455314432.ingest.us.sentry.io
"""
OLLAMA_LINES = """\
# ollama.com, blocked for Nightloom
0.0.0.0 ollama.com
:: ollama.com
"""
BLOCK_02 = f"""\
# BEGIN black-ops
# Managed by the Black Ops bar plugin. Switch it off there rather than editing here.
0.0.0.0 {DATADOG}
:: {DATADOG}
# END black-ops
"""
NIGHTLOOM_HOSTS_LINES = [f"{a} {h}" for h in ("mobile.events.data.microsoft.com",
                                               "o4507954455314432.ingest.us.sentry.io")
                         for a in ("0.0.0.0", "::")]


def nightloom_missing_hosts_lines(text):
    """The same test Nightloom's setup makes in missing_hosts_lines(): a
    line counts wherever it is in the file, comments aside."""
    lines = [line.split("#", 1)[0].split() for line in text.splitlines()]
    have = {(w[0], host) for w in lines if len(w) > 1 for host in w[1:]}
    return [line for line in NIGHTLOOM_HOSTS_LINES if tuple(line.split()) not in have]


def rows(rep):
    return {r["id"]: r for r in rep["rows"]}


def not_black_opss(sandbox):
    """Everything the removed rows managed, as it is now."""
    return {
        "ollama": sandbox.ollama_dropin.read_bytes(),
        "onnx": (sandbox.onnx.stat().st_mode & 0o777, sandbox.is_immutable(sandbox.onnx),
                 sorted(p.name for p in sandbox.onnx.iterdir())),
        "webui": sandbox.webui_values(),
        "proton": sandbox.proton.read_bytes(),
    }


@pytest.fixture
def upgraded(sandbox):
    """A machine that ran 0.1, switched on, and has just been upgraded to
    0.2 and had the installer run once more."""
    sandbox.machine_01()
    return sandbox


# ------------------------------------------------------------ the state file

def test_status_forgets_removed_rows_and_changes_nothing_else(upgraded, run):
    before = upgraded.snapshot()
    kept_before = not_black_opss(upgraded)
    rep = run("status")
    st = upgraded.state()
    assert set(st["rows"]) == KEPT
    assert all(st["rows"][k] == state_01()["rows"][k] for k in KEPT)
    assert "optional" not in st and st["version"] == 2 and st["master"] is True
    # Forgetting is all it does: no helper call, no file touched.
    assert upgraded.helper_verbs() == []
    assert upgraded.snapshot() == before
    assert not_black_opss(upgraded) == kept_before
    assert [r["id"] for r in rep["rows"]][:5] == ["weather", "agents", "dns", "claude", "hosts"]
    # The rows added since 0.3.0 have nothing to protect on this machine.
    # The software watch and listen mode are off, never not applicable, and
    # so is the Claude usage check while the Agents widget is on the bar.
    assert all(r["status"] == "na" for r in rep["rows"][5:]
               if r["id"] not in ("watch", "listen", "claude-usage"))
    assert rep["overall"] == "ok", rep
    assert oct(upgraded.state_file.stat().st_mode & 0o777) == "0o600"


def test_status_with_notify_forgets_them_too(upgraded, run):
    run("status", "--notify")
    assert set(upgraded.state()["rows"]) == KEPT
    assert upgraded.calls("notify-send") == []


def test_every_mention_of_a_removed_row_is_forgotten(upgraded, run, bo):
    st = state_01(ollama_block=True)
    st["excluded"] = ["proton", "claude"]
    st["notified"] = ["onnx", "dns"]
    st["errors"] = {"openwebui": "Open WebUI is running.", "dns": "an error"}
    upgraded.write(upgraded.state_file, json.dumps(st))
    run("status")
    st = upgraded.state()
    assert set(st["rows"]) == KEPT
    assert st["excluded"] == ["claude"]
    assert st["notified"] == ["dns"]
    assert st["errors"] == {"dns": "an error"}
    for row_id in REMOVED:
        assert row_id not in bo.BY_ID and row_id in bo.FORMER_ROWS
        assert row_id not in json.dumps(st)


def test_a_current_state_file_is_not_rewritten_by_status(upgraded, run):
    run("status")
    first = upgraded.state_file.read_bytes()
    mtime = upgraded.state_file.stat().st_mtime_ns
    run("status")
    assert upgraded.state_file.read_bytes() == first
    assert upgraded.state_file.stat().st_mtime_ns == mtime


# ------------------------------------------------------------ the hosts block

def test_status_says_the_block_needs_tidying(upgraded, run):
    r = rows(run("status"))["hosts"]
    assert r["status"] == "ok" and r["value"] == "blocked, block to tidy"
    assert "earlier version" in r["detail"]


def test_on_hands_the_other_hosts_over_without_unblocking_them(upgraded, run):
    kept_before = not_black_opss(upgraded)
    rep = run("on")
    assert upgraded.helper_verbs() == ["hosts-on"]
    text = upgraded.hosts.read_text()
    assert text == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES + "\n" + BLOCK_02
    assert nightloom_missing_hosts_lines(text) == []
    assert rows(rep)["hosts"]["value"] == "blocked"
    assert rep["overall"] == "ok", rep
    assert set(upgraded.state()["rows"]) == KEPT
    assert not_black_opss(upgraded) == kept_before


def test_off_after_the_upgrade_keeps_what_now_belongs_to_nightloom(upgraded, run):
    kept_before = not_black_opss(upgraded)
    run("on")
    rep = run("off")
    assert rep["overall"] == "off", rep
    text = upgraded.hosts.read_text()
    assert text == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES
    assert nightloom_missing_hosts_lines(text) == []
    assert not upgraded.dns_dropin.exists()
    assert not_black_opss(upgraded) == kept_before
    assert json.loads(upgraded.proton.read_text())["anonymous_crash_reports"] is False
    assert upgraded.state()["rows"] == {}


def test_off_straight_after_the_upgrade_is_just_as_safe(upgraded, run):
    kept_before = not_black_opss(upgraded)
    run("off")
    assert sorted(upgraded.helper_verbs()) == ["dns-off", "hosts-off"]
    text = upgraded.hosts.read_text()
    assert text == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES
    assert nightloom_missing_hosts_lines(text) == []
    assert not_black_opss(upgraded) == kept_before


def test_an_ollama_block_moves_out_and_stays(sandbox, run):
    sandbox.machine_01(ollama_block=True)
    run("on")
    text = sandbox.hosts.read_text()
    assert text == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES + OLLAMA_LINES + "\n" + BLOCK_02
    assert "ollama-block" not in sandbox.state()["rows"]
    run("off")
    assert sandbox.hosts.read_text() == STOCK_HOSTS + "\n" + NIGHTLOOM_LINES + OLLAMA_LINES


# ------------------------------------------------------------ an old helper

def etc_files(sandbox):
    return {k: v for k, v in sandbox.snapshot().items() if k.startswith(str(sandbox.etc))}


OLD_HELPER = "#!/usr/bin/python3 -I\n# Black Ops 0.1 helper, with ten verbs.\nVERBS = ()\n"


def test_an_old_helper_is_reported_and_never_run(sandbox, run):
    sandbox.machine_01()
    sandbox.install_helper(OLD_HELPER)
    etc_before = etc_files(sandbox)
    kept_before = not_black_opss(sandbox)
    rep = run("status")
    assert rep["helperState"] == "outdated"
    assert "a version before 0.2.0" in rep["helperNote"]
    assert "sudo bin/black-ops-install" in rep["helperNote"]
    assert rep["overall"] == "warn"
    assert rep["headline"] == "On, but the root helper needs reinstalling"
    assert rows(rep)["hosts"]["error"] == rep["helperNote"]
    # Neither on nor off runs it: 0.1's hosts-off would unblock the hosts
    # that now belong to Nightloom.
    run("on")
    rep = run("off")
    assert sandbox.calls("sudo") == []
    assert etc_files(sandbox) == etc_before
    assert not_black_opss(sandbox) == kept_before
    assert sandbox.hosts.read_text() == HOSTS_01
    assert rep["overall"] == "warn"
    assert set(rep["pending"]) == {"hosts", "dns"}
    assert set(sandbox.state()["rows"]) == {"hosts", "dns"}
    # The unprivileged rows still switch.
    assert "DISABLE_TELEMETRY" not in json.loads(sandbox.claude.read_text())["env"]


def test_an_old_helper_with_a_version_is_named(sandbox, run, bo):
    sandbox.stock_machine()
    text = (sandbox.helper.read_text()
            .replace(f'HELPER_VERSION = "{bo.VERSION}"', 'HELPER_VERSION = "0.1.9"'))
    sandbox.install_helper(text)
    rep = run("status")
    assert rep["helperState"] == "outdated"
    assert "from version 0.1.9" in rep["helperNote"]


def test_after_reinstalling_the_helper_is_current(sandbox, run):
    sandbox.machine_01()
    sandbox.install_helper(OLD_HELPER)
    assert run("status")["helperState"] == "outdated"
    sandbox.install_helper()
    rep = run("status")
    assert rep["helperState"] == "current" and rep["helperNote"] == ""
    assert rep["overall"] == "ok"


def test_the_panel_text_mentions_the_helper(sandbox, bo, capsys):
    sandbox.machine_01()
    sandbox.install_helper(OLD_HELPER)
    assert bo.main(["status", "--text"], sandbox.env) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Black Ops: On, but the root helper needs reinstalling"
    assert out.rstrip().endswith("from the plugin folder.")
