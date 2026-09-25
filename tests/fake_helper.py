"""Run the real root helper, system/apply, inside a test sandbox.

The stub sudo in conftest.py runs this in place of the installed helper. It
loads system/apply from the repository and points every path it uses into
the sandbox named by BLACK_OPS_FAKE_ROOT before calling its main(). The root
and install checks are skipped, because the tests do not run as root.
"""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
root = Path(os.environ["BLACK_OPS_FAKE_ROOT"]).resolve()

loader = importlib.machinery.SourceFileLoader("apply", str(REPO / "system" / "apply"))
spec = importlib.util.spec_from_loader("apply", loader)
apply = importlib.util.module_from_spec(spec)
loader.exec_module(apply)

etc = root / "etc"
apply.TRUSTED_UID = os.getuid()
apply.TRUSTED_BASE = str(etc)
apply.ETC = str(etc)
apply.RESOLVED_DROPIN_DIR = str(etc / "systemd/resolved.conf.d")
apply.NM_CONF_DIR = str(etc / "NetworkManager/conf.d")
apply.CHROMIUM_POLICY_DIR = str(etc / "chromium/policies/managed")
apply.AVAHI_DIR = str(etc / "avahi")
apply.FWUPD_DIR = str(etc / "fwupd")
apply.BT_DIR = str(etc / "bluetooth")
apply.AVAHI_UNIT_FILE = str(root / "usr/lib/systemd/system/avahi-daemon.service")
apply.NMCLI = str(root / "bin" / "nmcli")
apply.UFW = str(root / "bin" / "ufw")
apply.SYSTEMCTL = str(root / "bin" / "systemctl")
apply.RESOLVECTL = str(root / "bin" / "resolvectl")
apply.CLEAN_ENV = {"PATH": str(root / "bin"), "BLACK_OPS_FAKE_ROOT": str(root)}
apply.LISTEN_UNIT = str(etc / "systemd/system/omarchy-black-ops-listen.service")
apply.LISTEN_CONF = str(etc / "omarchy-black-ops/listen.conf")
apply.LISTEN_RUN = str(root / "run/black-ops-listen")
apply.LISTEN_KEEP = str(root / "var/log/black-ops-listen")
apply.LISTEN_SIGNAL_WAIT = 0
apply.require_root = lambda: None
apply.check_own_install = lambda: None

for value in (apply.ETC, apply.RESOLVED_DROPIN_DIR, apply.NM_CONF_DIR, apply.CHROMIUM_POLICY_DIR,
              apply.AVAHI_DIR, apply.FWUPD_DIR, apply.BT_DIR, apply.AVAHI_UNIT_FILE, apply.NMCLI, apply.UFW, apply.LISTEN_UNIT,
              apply.LISTEN_CONF, apply.LISTEN_RUN, apply.LISTEN_KEEP):
    assert value.startswith(str(root)), value

sys.exit(apply.main(["apply"] + sys.argv[1:], os.environ))
