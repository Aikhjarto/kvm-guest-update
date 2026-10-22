# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the pre, post and cleanup hooks, run as they run in a VM.

The script's HOOKS and HOOKMAIN parts are taken from kvm-guest-update and run
with a fake upgrade, in a temporary directory instead of /etc/kvm-guest-update.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
SCRIPT = os.path.abspath(os.path.join(ROOT, "kvm-guest-update"))


def heredoc(name):
    """The text of the quoted here document read into the variable name."""
    with open(SCRIPT) as f:
        text = f.read()
    return re.search(r"^read -r -d '' %s <<'EOF'\n(.*?)\nEOF$" % name, text, re.M | re.S).group(1)


HOOK = """#!/bin/sh
echo "$KVM_GUEST_UPDATE_STAGE/{name} $KVM_GUEST_UPDATE_STATUS" >> "$TRACE"
exit {code}
"""


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class HookTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = directory.name
        self.trace = os.path.join(self.dir, "trace")

    def hook(self, stage, name, code=0, mode=0o755):
        """Add a hook that records "stage/name status" in the trace and exits with code."""
        os.makedirs(os.path.join(self.dir, stage + ".d"), exist_ok=True)
        path = os.path.join(self.dir, stage + ".d", name)
        with open(path, "w") as f:
            f.write(HOOK.format(name=name, code=code))
        os.chmod(path, mode)

    def run_hooks(self, upgrade_rc=0, hooks_only=False):
        """Run the hooks around a fake upgrade, or with -H's empty one; returns (trace lines, output)."""
        if hooks_only:
            upgrade = "pm_upgrade() {\n%s\n}" % heredoc("NOUPGRADE")
        else:
            upgrade = 'pm_upgrade() { echo "upgrade" >> "$TRACE"; rc=%d; }' % upgrade_rc
        script = "\n".join(["HOOKDIR=" + self.dir, heredoc("HOOKS"), upgrade, heredoc("HOOKMAIN")])
        result = subprocess.run(["bash", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, env=dict(os.environ, TRACE=self.trace, LC_ALL="de_DE.UTF-8"))
        self.assertEqual(result.returncode, 0, result.stdout)
        trace = []
        if os.path.exists(self.trace):
            with open(self.trace) as f:
                trace = f.read().splitlines()
        return trace, result.stdout

    def test_no_hooks(self):
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["upgrade"])
        self.assertTrue(out.endswith("EXIT: 0\n"), out)

    def test_order(self):
        for name in ("b", "10-x", "2-y", "B"):
            self.hook("pre", name)
        self.hook("post", "p")
        self.hook("cleanup", "c")
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["pre/10-x ok", "pre/2-y ok", "pre/B ok", "pre/b ok",
                                 "upgrade", "post/p ok", "cleanup/c ok"])
        self.assertNotIn("HOOK FAILED", out)

    def test_pre_fails(self):
        self.hook("pre", "1", 0)
        self.hook("pre", "2", 3)
        self.hook("pre", "3", 0)
        self.hook("post", "p")
        self.hook("cleanup", "c1", 1)
        self.hook("cleanup", "c2")
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["pre/1 ok", "pre/2 ok", "cleanup/c1 pre-failed", "cleanup/c2 pre-failed"])
        self.assertIn("HOOK FAILED: pre/2: exit code 3\n", out)
        self.assertIn("HOOK FAILED: cleanup/c1: exit code 1\n", out)
        self.assertTrue(out.endswith("EXIT: pre-hook\n"), out)

    def test_upgrade_fails(self):
        self.hook("post", "p")
        self.hook("cleanup", "c")
        trace, out = self.run_hooks(upgrade_rc=100)
        self.assertEqual(trace, ["upgrade", "cleanup/c upgrade-failed"])
        self.assertTrue(out.endswith("EXIT: 100\n"), out)

    def test_post_fails(self):
        self.hook("post", "p1", 2)
        self.hook("post", "p2")
        self.hook("cleanup", "c")
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["upgrade", "post/p1 ok", "cleanup/c post-failed"])
        self.assertIn("HOOK FAILED: post/p1: exit code 2\n", out)
        self.assertTrue(out.endswith("EXIT: 0\n"), out)

    def test_skipped_files(self):
        self.hook("pre", "not-executable", mode=0o644)
        self.hook("pre", "backup~")
        self.hook("pre", "old.dpkg-old")
        self.hook("pre", "conf.rpmnew")
        os.makedirs(os.path.join(self.dir, "pre.d", "subdir"))
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["upgrade"])

    def test_hooks_only(self):
        self.hook("pre", "a")
        self.hook("post", "p")
        self.hook("cleanup", "c")
        trace, out = self.run_hooks(hooks_only=True)
        self.assertEqual(trace, ["pre/a ok", "post/p ok", "cleanup/c ok"])
        self.assertIn("nothing to upgrade, running the hooks only", out)
        self.assertTrue(out.endswith("EXIT: 0\n"), out)

    def test_check_only_and_hooks_exclude_each_other(self):
        result = subprocess.run(["bash", SCRIPT, "-n", "-H"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("exclude each other", result.stderr)

    def test_writable_by_others(self):
        self.hook("pre", "open", mode=0o777)
        self.hook("cleanup", "c")
        trace, out = self.run_hooks()
        self.assertEqual(trace, ["cleanup/c pre-failed"])
        self.assertIn("HOOK FAILED: pre/open: not owned by", out)


if __name__ == "__main__":
    unittest.main()
