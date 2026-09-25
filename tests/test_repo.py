"""Checks on the repository itself."""
import json
import subprocess

from conftest import REPO

# Built from parts, so this file does not contain the word it looks for.
PRIVATE = ("black" + "bird").encode()


def tracked_files():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=REPO, capture_output=True, text=True).stdout.split()
    return [REPO / f for f in out]


def test_no_private_name_anywhere():
    for path in tracked_files():
        assert PRIVATE not in path.read_bytes().lower(), path
        assert PRIVATE.decode() not in str(path.relative_to(REPO)).lower(), path


def test_no_em_dashes_in_prose():
    for path in tracked_files():
        if path.suffix in (".md", ".qml", ".py", ".json") or path.parent.name in ("bin", "system"):
            assert "\u2014" not in path.read_text(encoding="utf-8"), path


def test_manifest():
    m = json.loads((REPO / "manifest.json").read_text())
    assert m["id"] == "brightwalker25.black-ops"
    assert m["version"] == "0.4.0"
    assert m["entryPoints"]["barWidget"] == "BarWidget.qml"
    defaults = m["barWidget"]["defaults"]
    assert defaults == {"refreshMinutes": 10, "notifyOnSlip": True}


def test_signatures_file_follows_the_contract():
    import fnmatch
    import re
    import tomllib
    data = tomllib.loads((REPO / "data" / "signatures.toml").read_text())
    assert data["schema"] == 1
    kinds = {"telemetry", "analytics", "crash-report", "feature-flags", "lookup", "update-check"}
    seen = set()
    for sig in data["signature"]:
        assert set(sig) == {"id", "vendor", "kind", "hosts", "strings", "about"}, sig
        assert re.fullmatch(r"[a-z0-9-]+", sig["id"]) and sig["id"] not in seen
        seen.add(sig["id"])
        assert sig["kind"] in kinds
        assert sig["hosts"] and all(h == h.lower() and not h.endswith(".") for h in sig["hosts"])
        assert all(len(s) >= 8 and s.isascii() for s in sig["strings"])
    # The pattern rule in docs/contract.md, section 8.
    datadog = next(s for s in data["signature"] if s["id"] == "datadog-intake")
    assert any(fnmatch.fnmatchcase("http-intake.logs.us5.datadoghq.com", p) for p in datadog["hosts"])


def test_the_installer_keeps_room_for_phase_2():
    text = (REPO / "bin" / "black-ops-install").read_text()
    for part in ("watch", "listen"):
        assert f"# ---- {part} " in text and f"# ---- end {part}" in text
