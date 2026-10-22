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

Check which VMs would be updated, then do a check-only run:

```sh
kvm-guest-update -l
kvm-guest-update -n
```

## Usage

```
kvm-guest-update [-n] [-o OS[,OS...]] [VM ...]
kvm-guest-update -l
```

| Option | Action |
|---|---|
| `-n` | Check only: refresh, download and the check. No upgrade, no `err` message. |
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

The summary shows for each VM one of: `up to date`, `upgraded N packages`,
`MANUAL UPGRADE NEEDED` with the expected questions, or `FAILED`/`TIMEOUT`
with the step. `REBOOT REQUIRED`, `CONFIG FILES TO MERGE` and
`REPOSITORY PROBLEM` are added where they apply. The same summary goes to the
system log with the tag `kvm-guest-update`.

The timeout per VM and step is 3600 s (`TIMEOUT` at the top of the script).

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
