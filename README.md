# kvm-guest-update

Updates the running Debian and openSUSE Leap VMs of a KVM host through the
QEMU guest agent. No SSH access or password is needed in the VMs.

- **Debian:** `apt-get update` and `apt-get upgrade --with-new-pkgs` (like
  `apt upgrade`: new dependencies are installed, nothing is removed).
- **openSUSE Leap:** `zypper refresh` and `zypper update --no-recommends`.

Each VM is checked before its upgrade, and skipped if the package manager
would ask a question. The packages are downloaded first, then:

- **Debian:** a VM is skipped if dpkg would ask about a conffile (changed
  locally and in the new package), or if a file managed by ucf is changed
  locally and its package is upgraded. debconf questions are not detected;
  they are answered with their defaults.
- **Leap:** a VM is skipped if the dry run reports a dependency problem,
  packages to be removed, or a license to agree to. Changed configuration
  files never stop zypper: rpm leaves `.rpmnew` or `.rpmsave` files, which are
  listed after the upgrade so you can merge them by hand.

Skipped VMs are logged with priority `err`, so that a log monitor can report
them right away; upgrade those by hand. Afterwards every VM is checked for a
needed reboot (newer or rebuilt kernel, `/run/reboot-required`,
`zypper needs-rebooting`). VMs are never rebooted.

Hooks in the VMs can run commands before and after the upgrade, e.g. to stop
and start a service (see [Hooks](#hooks)).

The upgrade runs in each VM as a transient systemd unit,
`kvm-guest-update.service`, not as a child of the guest agent. It keeps
running when the guest agent itself is upgraded and restarted, and when this
script is interrupted (Ctrl+C, SSH disconnect).

## Requirements

On the KVM host:

- bash 4 or newer, `virsh` (libvirt), `jq`, `base64`, `logger`
- run as root (libvirt connection `qemu:///system`)

In each VM:

- `qemu-guest-agent` running, with the virtio-serial channel
  `org.qemu.guest_agent.0` in the libvirt domain. It must allow
  `guest-get-osinfo`, `guest-exec`, `guest-exec-status` and
  `guest-file-open/write/close`. The Debian and openSUSE packages allow these
  by default, unless a block list is set in the agent's configuration.
- systemd (`systemd-run`), and a writable `/root` and `/var/log`

## Installation

```sh
install -m 755 kvm-guest-update /usr/local/sbin/
```

The bash completion completes the options, the operating systems after
`-o` (also in a comma-separated list) and the names of the running VMs. It
reads the operating systems from the `PM` table of the installed script, and
the VMs from `virsh list` on `qemu:///system` (or `LIBVIRT_DEFAULT_URI`), so
as a user that is not root it needs read access to libvirt, e.g. through the
`libvirt` group. The packages install it; otherwise:

```sh
install -D -m 644 completions/kvm-guest-update /usr/share/bash-completion/completions/kvm-guest-update
```

Check which VMs would be updated, then do a check-only run:

```sh
kvm-guest-update -l
kvm-guest-update -n
```

## Usage

```
kvm-guest-update [-n | -H] [-o OS[,OS...]] [VM ...]
kvm-guest-update -l
```

| Option | Action |
|---|---|
| `-n` | Check only: refresh, download and the check. No upgrade, no hooks, no `err` message. |
| `-H` | Run the [hooks](#hooks) also in VMs with nothing to upgrade. Not together with `-n`. |
| `-o OS` | Only VMs with these operating systems, as reported by the guest agent (`ID` from os-release): `debian`, `opensuse-leap`. Several separated by commas, or `-o` given more than once. |
| `-l` | List the running VMs, their operating systems and package managers, then exit. |
| `VM ...` | Only these VMs, by their name in `virsh list`. Default: every running VM with a supported operating system. |

`-o` and VM names can be combined; then a VM must match both. A VM named on
the command line that is skipped (not running, no guest agent, operating system
not supported or not selected) is listed in the summary with the reason.
Without VM names, VMs without a guest agent or with an unsupported operating
system are listed in one `not updated:` line after the summary.

Examples:

```sh
kvm-guest-update                          # all supported VMs
kvm-guest-update -o debian                # only the Debian VMs
kvm-guest-update -n Leap_build Debian_omd # check two VMs
```

The summary shows for each VM one of: `up to date`, `up to date, hooks run`
(with `-H`), `upgraded N packages`,
`MANUAL UPGRADE NEEDED` with the expected questions, `SKIPPED: a pre hook
failed`, or `FAILED`/`TIMEOUT` with the step. `REBOOT REQUIRED`,
`CONFIG FILES TO MERGE`, `REPOSITORY PROBLEM` and `HOOK FAILED` are added where
they apply. The same summary goes to the system log with the tag
`kvm-guest-update`; the lines of VMs that need a manual upgrade or had a hook
fail are logged again with priority `err`.

The timeout per VM and step is 3600 s (`TIMEOUT` at the top of the script).

## Hooks

Executable files in these directories **in the VM** run when that VM is
upgraded:

| Directory | When |
|---|---|
| `/etc/kvm-guest-update/pre.d/` | before the upgrade |
| `/etc/kvm-guest-update/post.d/` | after the upgrade, if it succeeded |
| `/etc/kvm-guest-update/cleanup.d/` | at the end, always: also when a pre hook, the upgrade or a post hook failed |

- The files of each directory run in name order (C locale: `10-a` before
  `2-b` before `B` before `a`), as root, with stdin from `/dev/null`. Their
  output goes to `/var/log/kvm-guest-update.log` in the VM and to the log on
  the host.
- **pre:** if a hook fails (exit code other than 0), nothing else runs except
  the cleanup hooks: no further pre hooks, no upgrade, no post hooks. The
  summary says `SKIPPED: a pre hook failed`.
- **post:** if a hook fails, the remaining post hooks are not run. If the
  upgrade failed, no post hook runs.
- **cleanup:** all of them run, also when one of them fails.
- Hooks run only when there is something to upgrade, or with `-H` also when
  there is nothing to upgrade (then pre, post and cleanup run without an
  upgrade between them). They never run with `-n`, nor in a VM whose upgrade
  needs answers to questions (`MANUAL UPGRADE NEEDED`).
- Each hook gets `KVM_GUEST_UPDATE_STAGE` (`pre`, `post` or `cleanup`) and
  `KVM_GUEST_UPDATE_STATUS`: `ok`, or for the cleanup hooks what went wrong
  before them: `pre-failed`, `upgrade-failed` or `post-failed`.
- Not run: files that are not executable, and leftovers of editors and package
  managers (`*~`, `*.bak`, `*.dpkg-*`, `*.rpmnew`, `*.rpmsave`, `*.rpmorig`).
  A hook not owned by root, or writable by group or others, is not run either
  and counts as failed.
- A failed hook adds `HOOK FAILED: <stage>/<name>: ...` to the summary, and
  the VM's summary line is logged with priority `err`.
- The hooks run within the upgrade's systemd unit, so the timeout (`TIMEOUT`)
  covers them too.

Example: stop a service for the upgrade and start it again in any case.

```sh
# /etc/kvm-guest-update/pre.d/10-stop-myapp
#!/bin/sh
systemctl stop myapp

# /etc/kvm-guest-update/cleanup.d/10-start-myapp
#!/bin/sh
systemctl start myapp
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

tests the bash completion, and the hooks with a fake upgrade.

## Logs

- `/var/log/kvm-guest-update/<date>_<time>/<vm>.log` on the host: the check,
  the upgrade and the reboot check of each VM
- `/var/log/kvm-guest-update.log` in each VM: the output of its last upgrade

## Adding an operating system

The `PM` table at the top of the script maps the `ID` the guest agent reports to
a package manager (`apt` or `zypper`). Other distributions using one of them
can be added there, e.g. `[ubuntu]=apt`. This is untested: check the reboot
check and the dry run parsing for that distribution, and run with `-n` first.
openSUSE Tumbleweed needs `zypper dup`, not `zypper update`, so it isn't a
simple addition.

## Migrating from debian_updates.sh and leap_updates.sh

`kvm-guest-update` replaces both scripts and works the same way. These differ:

- The unit in the VM is `kvm-guest-update.service` instead of
  `debian-updates.service` or `leap-updates.service`. An upgrade started by the
  old scripts is not detected as already running, but the package manager's
  lock still keeps both from running at the same time.
- Log tag, log directories and the upgrade script in the VM
  (`/root/kvm-guest-update-upgrade.sh`) are named `kvm-guest-update`. Delete
  the old `/root/debian_updates_upgrade.sh` and `/root/leap_updates_upgrade.sh`
  in the VMs if you like.
- Debian results say "questions expected" instead of "prompts expected".

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
