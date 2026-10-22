# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests of the bash completion in completions/kvm-guest-update."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir)
SCRIPT = os.path.abspath(os.path.join(ROOT, "kvm-guest-update"))
COMPLETION = os.path.join(ROOT, "completions", "kvm-guest-update")

FAKE_VIRSH = """#!/bin/sh
# prints the running VMs like "virsh list --name", and the arguments to $VIRSH_ARGS
echo "$*" > "$VIRSH_ARGS"
printf '%s\\n' Debian_omd Debian_web Leap_build ''
"""


def usage_options():
    """The options the usage text lists."""
    result = subprocess.run(["bash", SCRIPT, "-h"], stdout=subprocess.PIPE,
                            universal_newlines=True, check=True)
    return set(re.findall(r"^  (-\w)\b", result.stdout, re.M)) | {"-h"}


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class CompletionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = directory.name
        virsh = os.path.join(self.dir, "virsh")
        with open(virsh, "w") as f:
            f.write(FAKE_VIRSH)
        os.chmod(virsh, 0o755)
        self.virsh_args = os.path.join(self.dir, "virsh-args")

    def complete(self, *words, command=SCRIPT, uri=None):
        """The candidates bash offers for the last of words, which may be empty."""
        script = 'source "$1"; shift; COMP_WORDS=("$@"); COMP_CWORD=$(($# - 1)); ' \
                 '_kvm_guest_update; printf "%s\\n" "${COMPREPLY[@]}"'
        env = dict(os.environ, PATH=self.dir + os.pathsep + os.environ["PATH"],
                   VIRSH_ARGS=self.virsh_args)
        env.pop("LIBVIRT_DEFAULT_URI", None)
        if uri:
            env["LIBVIRT_DEFAULT_URI"] = uri
        result = subprocess.run(["bash", "-c", script, "bash", COMPLETION, command] + list(words),
                                stdout=subprocess.PIPE, universal_newlines=True, check=True,
                                env=env)
        return [line for line in result.stdout.split("\n") if line]

    def test_syntax(self):
        subprocess.run(["bash", "-n", COMPLETION], check=True)

    def test_offers_exactly_the_options_of_usage(self):
        self.assertEqual(set(self.complete("-")), usage_options())

    def test_options_after_an_option(self):
        self.assertEqual(self.complete("-n", "-"), ["-n", "-o"])

    def test_nothing_after_list_or_help(self):
        self.assertEqual(self.complete("-l", ""), [])
        self.assertEqual(self.complete("-h", ""), [])

    def test_operating_systems(self):
        self.assertEqual(self.complete("-o", ""), ["debian", "opensuse-leap"])
        self.assertEqual(self.complete("-n", "-o", "op"), ["opensuse-leap"])

    def test_operating_system_list(self):
        self.assertEqual(self.complete("-o", "debian,"), ["debian,opensuse-leap"])
        self.assertEqual(self.complete("-o", "debian,o"), ["debian,opensuse-leap"])
        self.assertEqual(self.complete("-o", "debian,opensuse-leap,"), [])

    def test_operating_systems_from_the_script(self):
        script = os.path.join(self.dir, "kvm-guest-update")
        with open(SCRIPT) as f:
            text = f.read().replace("declare -A PM=(", "declare -A PM=([ubuntu]=apt ", 1)
        with open(script, "w") as f:
            f.write(text)
        self.assertEqual(self.complete("-o", "", command=script),
                         ["ubuntu", "debian", "opensuse-leap"])

    def test_operating_systems_of_the_command_in_path(self):
        os.symlink(SCRIPT, os.path.join(self.dir, "kvm-guest-update"))
        self.assertEqual(self.complete("-o", "", command="kvm-guest-update"),
                         ["debian", "opensuse-leap"])

    def test_vm_names(self):
        self.assertEqual(self.complete(""), ["Debian_omd", "Debian_web", "Leap_build"])
        self.assertEqual(self.complete("-n", "-o", "debian", "Deb"), ["Debian_omd", "Debian_web"])
        with open(self.virsh_args) as f:
            self.assertEqual(f.read().split(), ["--connect", "qemu:///system", "list", "--name"])

    def test_vm_names_are_offered_once(self):
        self.assertEqual(self.complete("Debian_omd", "Deb"), ["Debian_web"])

    def test_no_options_after_vm_names(self):
        self.assertEqual(self.complete("Leap_build", "-"), [])

    def test_libvirt_default_uri(self):
        self.complete("", uri="qemu+ssh://host/system")
        with open(self.virsh_args) as f:
            self.assertEqual(f.read().split()[:2], ["--connect", "qemu+ssh://host/system"])


if __name__ == "__main__":
    unittest.main()
