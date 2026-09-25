"""bin/black-ops-install, run only in the modes that need no root and change
nothing: printing the sudoers rule, a dry run, and the refusal to run
without root. It is never run for real here."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import REPO

INSTALLER = REPO / "bin" / "black-ops-install"
HELPER = "/usr/local/lib/omarchy-black-ops/apply"


def installer(*args):
    env = {"PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", str(INSTALLER), *args], capture_output=True, text=True, env=env)


def rule_commands(text):
    """The commands the rule allows, with continuation lines joined."""
    body = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
    body = body.replace("\\\n", " ")
    lines = [l for l in body.splitlines() if l.strip()]
    assert len(lines) == 1, lines
    m = re.fullmatch(r"(\S+) ALL=\(root\) NOPASSWD: (.*)", lines[0].strip())
    assert m, lines[0]
    return m.group(1), [c.strip() for c in m.group(2).split(",")]


def test_sudoers_rule_allows_exactly_the_helper_verbs(helper):
    r = installer("--print-sudoers", "alice")
    assert r.returncode == 0, r.stderr
    user, commands = rule_commands(r.stdout)
    assert user == "alice"
    assert commands == [f"{HELPER} {verb}" for verb in helper.VERBS]
    # No wildcards, no other program, no environment passing.
    assert "*" not in r.stdout
    assert "SETENV" not in r.stdout and "env_keep" not in r.stdout
    assert "ALL=(root)" in r.stdout and "(ALL)" not in r.stdout


def test_installer_and_helper_list_the_same_verbs(helper):
    text = INSTALLER.read_text()
    block = re.search(r"VERBS=\((.*?)\)", text, re.S).group(1)
    assert tuple(block.split()) == helper.VERBS


@pytest.mark.skipif(shutil.which("visudo") is None, reason="visudo is not installed")
def test_sudoers_rule_passes_visudo(tmp_path):
    r = installer("--print-sudoers", "alice")
    f = tmp_path / "rule"
    f.write_text(r.stdout)
    check = subprocess.run(["visudo", "-cf", str(f)], capture_output=True, text=True)
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.parametrize("name", ["", "Alice", "alice;id", "a b", "-alice", "alice\n"])
def test_account_names_are_validated(name):
    assert installer("--print-sudoers", name).returncode != 0


def test_refuses_to_install_without_root():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    r = installer()
    assert r.returncode == 1
    assert "root" in r.stderr
    assert r.stdout == ""


def test_dry_run_changes_nothing_and_says_so():
    r = installer("--dry-run")
    assert r.returncode == 0, r.stderr
    assert "Dry run: nothing was changed." in r.stdout
    assert "visudo -cf" in r.stdout


def test_the_rule_no_longer_names_the_verbs_0_1_had():
    r = installer("--print-sudoers", "alice")
    _, commands = rule_commands(r.stdout)
    assert f"{HELPER} version" in commands
    for verb in ("onnx-lock", "onnx-unlock", "ollama-dropin-on", "ollama-dropin-off",
                 "ollama-block-on", "ollama-block-off"):
        assert verb not in r.stdout


def test_uninstall_names_only_what_black_ops_owns():
    r = installer("--uninstall", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "no-fallback.conf" in r.stdout
    assert "onnxruntime" not in r.stdout and "ollama" not in r.stdout


def test_uninstall_removes_the_pacman_hook_before_the_script_it_runs():
    r = installer("--uninstall", "--dry-run")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    hook = out.index("rm -f /etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook")
    assert hook < out.index("rm -rf /usr/local/lib/omarchy-black-ops")
    assert "rm -rf /var/lib/omarchy-black-ops" in out
    assert "rm -rf /etc/omarchy-black-ops" in out
