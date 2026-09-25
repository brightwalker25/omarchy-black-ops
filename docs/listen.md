# Listen mode

Listen mode records which program on this machine looked up which host and
connected to it, and turns the Black Ops scope red when a program contacts a
host known to collect telemetry, analytics or crash reports. It keeps what
it sees in RAM, sends nothing anywhere, and is off until you switch it on.

## What you need

- bpftrace, which listen mode uses to see connections:
  `sudo pacman -S bpftrace`
- systemd-resolved, which Omarchy uses by default, for the names that were
  looked up.
- The installer run once more after updating Black Ops, from the plugin
  folder: `sudo bin/black-ops-install`. It copies the listener to
  `/usr/local/lib/omarchy-black-ops/listen`, a copy of the signatures next
  to it, writes `/etc/omarchy-black-ops/listen.conf`, and installs the
  service `omarchy-black-ops-listen` disabled.

Until bpftrace is installed the listen row reads "not available".

## Switching it on and off

Switch Black Ops on, then switch the Listen mode row on in the panel. That
starts the service through the root helper. Switching the row off stops the
service and wipes everything it recorded. From a terminal:

    black-ops row listen on
    black-ops row listen off

## What it records

The listener reads two things and nothing else:

- The answers systemd-resolved gives, through its monitor interface: the
  name that was asked for and the addresses in the answer.
- Each connection a program starts, through one bpftrace probe on the
  kernel's connect path: the process id, the program's short name, its
  user, and the address and port it connects to. The executable and the app
  (the uwsm scope Omarchy starts each app in) are read from `/proc`.

It ties a connection to a name when the address it connects to was given
as an answer for that name shortly before. A connection with no matching
lookup is kept with its address and no name.

For each program and host it keeps the first time and the last time it was
seen, and how many times. Connections to the machine itself, such as
lookups sent to resolved, are not kept.

## Where it is kept

By default everything is under `/run/black-ops-listen`, which is in RAM and
is gone when the service stops or the machine shuts down:

- `segments/`, one file per hour, readable by root only.
- `view/contacts.json`, the totals the panel reads, readable by root and
  your account's group.

Files older than the retention are overwritten and removed every hour. The
retention is 72 hours unless you change it, from 1 hour to 720 hours (30
days):

    sudo bin/black-ops-install --listen-retention 24

To keep the record across a reboot, it can be kept on disk instead, in
`/var/log/black-ops-listen`:

    sudo bin/black-ops-install --listen-keep yes

Running it again with `--listen-keep no` overwrites and removes that folder.

To wipe everything now, use Purge now in the panel, or:

    black-ops listen purge

The service writes nothing to the journal apart from its start and stop,
and a warning when bpftrace or resolved's monitor stops, which names no
host and no program.

## Reading it

    black-ops listen status
    black-ops listen report
    black-ops listen report --hours 6

`report` lists each program with the hosts it contacted, how often, and
when last. A host that matches a signature is marked RED for telemetry,
analytics or crash reports and flag for the other kinds. A host with no
lookup seen is shown by its address.

## Colours

- Red: a program contacted a host matching a telemetry, analytics or
  crash-report signature, and you have not reviewed it. Red wins over
  every other colour.
- Amber: a program contacted a host matching another kind of signature,
  such as feature flags or an update check, and you have not reviewed it;
  or the service is switched on but not running, or is running without one
  of its two sources.
- Hosts that match no signature are counted as new and change no colour.

Each flagged contact can be reviewed in the panel as allowed or a false
positive, after which it is grey. A review holds for that program and host
across restarts; a new host is a new item.

## What it cannot see

- DNS over HTTPS. A browser that sends its lookups straight to its own
  resolver over HTTPS, as Firefox and Chromium can, bypasses
  systemd-resolved. Its connections are still seen, but by address only,
  with no name, so a signature cannot match them.
- Hard-coded addresses. A program that connects to an address it never
  looked up shows up by address only.
- Lookups that bypass resolved in other ways, such as a program with its
  own resolver, or a VPN client that writes `/etc/resolv.conf` itself. A VPN
  app that sets its DNS through NetworkManager goes through resolved, so its
  lookups are seen.
- Shared addresses. When two names answer with the same address, as is
  common behind a CDN, a connection is tied to whichever of them was looked
  up last.
- Data sent without a new connection. A program that keeps one connection
  open is counted once for it, however much it sends.
- Anything sent without connect(), such as UDP sent with sendto() to an
  address the socket was never connected to, and traffic from the kernel
  itself, such as WireGuard.
- Programs in another network namespace are seen, but their lookups may
  not go through this machine's resolved.

## What shred can and cannot do

In RAM, removing a file is enough. For the store on disk, the folder is
made with copy-on-write switched off (`chattr +C`) before anything is
written to it, so that on btrfs `shred` overwrites the blocks a file
really used rather than writing new copies beside them. Even so, an SSD
remaps writes inside the drive, so the old contents can survive in cells
the drive no longer maps, and with TRIM (discard) disabled the file system
never tells the drive which blocks are free. Shredding makes recovery
harder; it does not make it impossible. Full-disk encryption (LUKS) is what
really protects data at rest, and it is why the store on disk is safe to
use on an encrypted machine.

## Cost

The probe runs in the kernel and only reports IPv4 and IPv6 connects. The
listener wakes when there is something to read, writes its files every 15
seconds while there is news (every 60 seconds for the store on disk) and
prunes once an hour. It runs at low CPU and disk priority, with its memory
capped. bpftrace itself uses some tens of megabytes of memory while it runs.

## Suspend, VPNs and restarts

The probe and the monitor subscription carry on through suspend and resume.
If systemd-resolved restarts, as it does when a VPN or Black Ops' own DNS
row changes its settings, the listener subscribes again. If bpftrace stops,
the listener starts it again with a growing pause, and after two quick
failures in a row it tries the other probe (the connect() tracepoint). If
the listener itself fails, systemd restarts it.

## Testing it after installing

1. `sudo pacman -S bpftrace`, then `sudo bin/black-ops-install`.
2. Switch Black Ops on and the Listen mode row on. Then
   `systemctl status omarchy-black-ops-listen` should show it active, and
   `black-ops listen status` should say it is running with no warning
   about bpftrace or the monitor.
3. Make a connection with a name: `curl -sI https://example.com >/dev/null`.
   Within about 15 seconds, `black-ops listen report --hours 1` should list
   curl with example.com.
4. Make one without a name: `curl -sI https://1.1.1.1 >/dev/null`. It
   should appear by address, with "(no lookup seen)".
5. To see red without contacting a telemetry service, point a signature
   host at 192.0.2.1, an address reserved for documentation that nothing
   answers, by adding the line `192.0.2.1 api.segment.io` to `/etc/hosts`
   with sudo. Then run `curl -m 3 http://api.segment.io/`, which fails
   after three seconds, and remove the line again. resolved answers the
   lookup from `/etc/hosts`, so the monitor sees it. The row and the scope
   should turn red within a status refresh. Review it in the panel to turn
   it grey, or purge. If nothing turns red, check with
   `black-ops listen report` whether the connection was seen by address
   only, which would mean this version of resolved does not report answers
   from `/etc/hosts` to its monitor.
6. Purge now, then `black-ops listen report` should list nothing.
7. Suspend and resume, then repeat step 3 to confirm it still records.
8. If the service fails to start, `journalctl -u omarchy-black-ops-listen`
   shows the reason, and `sudo bpftrace -l 'kprobe:security_socket_connect'`
   shows whether the probe point exists. If bpftrace reports a missing
   capability, the `CapabilityBoundingSet=` line in the unit is the place to
   look.
