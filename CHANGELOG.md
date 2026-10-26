# Changelog

Notable changes to the Black Ops plugin. Versions follow
[semantic versioning](https://semver.org), and the format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

The helper has new verbs and blocks more hosts, so run the installer once
more after upgrading, then use "Apply what is new" in the panel. The LAN
discovery row is optional and stays off until switched on by itself.

### Added

- When Spycatcher 0.6.0 or later is installed, the installer records the
  files it writes as root with `spycatcher-report --record`, so Spycatcher's
  file integrity check grades them as the installer's instead of listing
  them to confirm after every install. Only a copy of `spycatcher-report`
  that root owns and only root can write is run, and nothing else depends
  on it.

- The README suggests a way to review the software watch's findings once for
  several machines: verdicts kept in a private repository, matched on program
  and signature, and applied with a short script.

- Listen mode and the software watch know two more kinds of tracking:
  the redirects podcast hosts put in front of episode files to log each
  play (Podtrac, Chartable, OP3 and others), and AdsWizz's audio ad
  tracking used by radio streams.
- When the root helper is missing or out of date, the panel and the text
  output now give the exact command to run, with the installer's real path
  on that machine and the home folder written as `~`, such as
  `sudo ~/.config/omarchy/plugins/brightwalker25.black-ops/bin/black-ops-install`,
  and say to switch Black Ops on again afterwards. The panel has a Copy
  command button that puts it on the clipboard with `wl-copy`; it runs
  nothing itself. The status JSON carries the command as `helperCommand`.

- A Proton VPN crash reports row, `proton-crash`, that sets
  `anonymous_crash_reports` to false in `~/.config/Proton/VPN/settings.json`
  and changes nothing else in the file. Switching off puts back the value it
  had, or takes the key out again if Black Ops added it. Crash reports that
  were already off are adopted and left off on the way off, because turning
  them off was the user's choice in the app. Without that file, the row is
  not applicable.
- Thirteen hosts in the hosts block beside Claude Code's Datadog intake:
  Claude Code's Sentry crash reports (`o1158394.ingest.us.sentry.io`),
  Codex's Sentry crash reports (`o33249.ingest.us.sentry.io`), 1Password's
  telemetry and Sentry (`telemetry.1passwordservices.com` and
  `core-sentry.1passwordservices.com`), Brave's daily usage ping and P3A
  analytics (`usage-ping.brave.com` and `star-randsrv.bsg.brave.com`), the
  Mozilla telemetry that Firefox-based browsers such as Zen send
  (`incoming.telemetry.mozilla.org`), and Google Analytics, which Obsidian
  and OnlyOffice carry (`google-analytics.com`, `www.google-analytics.com`,
  `ssl.google-analytics.com` and `region1.google-analytics.com`, and the
  newer Google Analytics 4 collectors `analytics.google.com` and
  `region1.analytics.google.com`). Pages that use Google Analytics stop
  reporting your visits to it.
- `ORT_DISABLE_TELEMETRY=1` in the opt-out variables, so onnxruntime, which
  local AI tools bring in, stops sending Microsoft telemetry.

- An optional LAN discovery row, off until switched on by itself, for
  machines that use a VPN. A VPN that sends everything through its tunnel
  also takes link-local multicast, so LocalSend and similar tools on the
  local network can no longer find this machine. The row adds the route
  `224.0.0.0/24` to the NetworkManager profile of each active Ethernet and
  Wi-Fi connection, and to the running routing table, without bringing any
  connection down, so the VPN stays up. It has no cost: routers never
  forward these addresses, so nothing else goes around the VPN. A route
  already there is adopted, and a Wi-Fi network joined for the first time
  reads as slipped until the row is switched on again.
- Helper verbs `lan-discovery-on` and `lan-discovery-off`. Like every other
  verb, they take no argument, so the sudoers rule stays a list of exact
  commands.

### Changed

- When the root helper is out of date and the rows waiting to be applied need
  root, the headline now says "On, but the root helper needs reinstalling"
  rather than naming those rows, since running the installer again is what
  applies them.

- Black Ops no longer covers only what stock Omarchy ships. The rule is now
  that unless telemetry is absolutely essential for a program to work, it is
  barred, and that applies to apps you install yourself too. This reverses
  the scope set in 0.2.0. Hosts that another stack blocks for
  itself stay that stack's.
- The hosts row is now called "Telemetry hosts". It applies on every
  machine, rather than reading as not applicable until Claude Code is set
  up, since the programs it covers can be installed at any time. A block
  written by an earlier version, with fewer hosts in it, reads as not
  applied yet rather than as slipped, and switching on adds the rest.
  Switching herdr's update check on or off leaves such a block as it is.
- An opt-out variables file written by an earlier version reads as not
  applied yet rather than as slipped, and switching off removes it as well.
- The weather location is now moved to the centre of a square about 1.5
  miles (2.4 km) across, the same width east to west as north to south,
  instead of rounded to two decimal places (about 1.1 km north to south and
  less east to west). A location rounded the old way shows as precise until
  the row is applied again.
- Security Scan is now called Spycatcher, so the README, the comments and the
  phase 2 contract use the new name, and the README's `--before` example
  names `brightwalker25.spycatcher`.

### Fixed

- A review carried over to a new version of a program says "Carried over
  from an earlier version" once. It used to add the phrase again on every
  update, so a review carried through four updates said it four times.

- The network identity row now changes the Wi-Fi MAC address when
  NetworkManager uses iwd as its Wi-Fi backend. iwd chooses the address
  itself and ignores NetworkManager's `wifi.cloned-mac-address`, so Wi-Fi
  kept the hardware address and the row stayed amber however often it
  reconnected. Where iwd is installed, the helper's `identity-on` now also
  sets `AddressRandomization=network` in `[General]` of `/etc/iwd/main.conf`,
  a stable address for each network, and restarts iwd, which drops Wi-Fi
  for a few seconds. The line is marked, a value of your own is commented
  out and put back on `identity-off`, and a `main.conf` that held nothing
  else is removed again. A drop-in from an earlier version reads as not
  applied yet under iwd, so switching on adds the rest.
- The uninstaller's list of root-owned pieces to put back by hand now
  includes the lines marked black-ops in `/etc/iwd/main.conf`, and how to
  restore a value of your own that switching on kept aside.

## [0.4.0] - 2026-09-24

The helper has new verbs and the Chromium policy a new key, so run the
installer once more after upgrading, then use "Apply what is new" in the
panel.

### Added

- An optional Bluetooth address row, off until switched on by itself: `Privacy=device` in `/etc/bluetooth/main.conf`,
  as a marked edit, so the adapter uses a private address on Bluetooth Low
  Energy. Low Energy devices paired before may need pairing again, and
  switching restarts Bluetooth, after which pairing is turned off again.
- An optional Avahi daemon row, off until switched on by itself, that stops
  and masks `avahi-daemon.service` and `avahi-daemon.socket`. Finding
  printers and other machines by name stops working.
- Helper verbs `bt-privacy-on`, `bt-privacy-off`, `avahi-mask` and
  `avahi-unmask`. The helper is version 0.4.0.
- Neovim plugin update check: sets `enabled = false` in the checker table
  of `~/.config/nvim/lua/config/lazy.lua`, so lazy.nvim stops fetching
  every plugin from GitHub about once an hour. Only that value is changed; a
  file that is not in the stock layout is left alone and the row turns
  amber.
- Opt-out variables: `~/.config/uwsm/env.d/90-black-ops-opt-out` sets
  `DO_NOT_TRACK=1` and the standard opt-outs for Deno, Next.js, .NET,
  HashiCorp tools, Astro, Gatsby, Turborepo, Storybook, the Azure CLI,
  PowerShell, the AWS SAM CLI, vcpkg and Hint. It applies fully from the
  next login.
- Claude usage check, an optional row: turns Claude off in the Agents
  panel, which otherwise sends your Claude Code sign-in token to
  `api.anthropic.com` every 15 minutes to read usage. The panel then no
  longer shows Claude usage; Claude Code itself is not affected.

### Changed

- The bar glyph is a rifle scope instead of a lock, so it no longer looks
  like Security Scan's lock beside it. The centre is filled while Black Ops
  is on and empty while it is off; the colours are unchanged.
- The software watch's first scan no longer reads as a fault. What it finds
  is still flagged and listed, but the headline says "the first scan found
  N items to review" and the watch row does not ask for attention until
  something new is found after it.
- The Chromium policy sets `EnableMediaRouter` to false, so Chromium stops
  searching the local network for Cast devices and casting from it stops
  working. A policy written by 0.3.0 reads as not applied yet, not slipped.
- The Avahi announcements row reads as not applicable while the Avahi daemon
  is masked.
- The Chromium, Bluetooth address and Avahi daemon rows say what switching
  them costs in the first sentence of their detail.
- Developer tool telemetry covers npm as well: `update-notifier=false` and
  `fund=false` in `~/.npmrc`. `audit` is left alone.
- The Agents panel row leaves Claude's value to the Claude usage check row
  while that row is on, so the two never undo each other.

### Fixed

- The software watch no longer flags a script for a telemetry host it
  exists to block, such as a tool that writes the host into `/etc/hosts`.
  Such a match is kept as a note instead. Binaries, and any file that also
  uses the host in a URL, are flagged as before.

## [0.3.0] - 2026-09-24

The helper has new verbs, so run the installer once more after upgrading,
then switch Black Ops on again to put the new rows in place.

### Added

- Rows for stock Omarchy: Bluetooth pairing, with a 60-second pair window;
  network identity; the Chromium privacy policy; NetworkManager's
  connectivity check; Avahi announcements; web app profiles; and developer
  tool telemetry for gh, Codex, the Grok CLI and mise.
- Optional rows, off until switched on one by one and never switched on by
  the main switch: the update badge, herdr's update check, the LocalSend
  firewall port, debug symbol downloads, Omarchy's crash diagnosis offer,
  and fwupd's peer sharing.
- Helper verbs for the rows that need root: `identity-on`, `identity-off`,
  `chromium-on`, `chromium-off`, `connectivity-on`, `connectivity-off`,
  `avahi-on`, `avahi-off`, `herdr-block-on`, `herdr-block-off`,
  `localsend-close`, `localsend-open`, `fwupd-p2p-on` and `fwupd-p2p-off`.
- The Omarchy version is recorded when Black Ops is switched on, and the
  first check after it changes is strict: every row that is not holding
  says so against the update, and the new version is recorded only once
  every row holds.
- rows.d: other stacks can register rows in
  `~/.config/omarchy-black-ops/rows.d` that only report.
- `~/.local/state/black-ops/summary.json`, counts and states only, for
  Security Scan.
- `docs/contract.md`, the fixed interface for the software watch, listen
  mode, their panel and the Security Scan section, with `lib/` stubs where
  they plug in and `data/signatures.toml`.
- The software watch: an inventory of pacman, Flatpak, AppImage, pip, npm
  and mise installs, a local static scan of each new or changed item for
  telemetry, a review store, `watch` and `review` commands, user units, and
  a pacman hook that records new packages.
- Listen mode: a root service, off by default, that joins systemd-resolved's
  lookups to a bpftrace connect probe, keeps its record in RAM and shreds it
  after the retention. New helper verbs `listen-on`, `listen-off` and
  `listen-purge`. A contact with a telemetry host is red.
- The panel lists flagged items and contacts under their rows, with review,
  purge and on and off buttons that confirm inside the panel.
- `--uninstall` removes the pacman hook, listen mode and its record.

### Changed

- The colour rule. A protection that is switched on but not in place is
  amber, as before. Red is new and kept for one thing: listen mode saw a
  program contact a known telemetry host. Red wins over amber in the bar.
- A row that was never put in place, such as one new in this version, reads
  as not applied yet rather than as slipped.
- A connection profile that sets the host name, MAC address or IPv6 privacy
  itself makes the network identity row amber; profile names are never
  shown.
- A LocalSend rule of your own, such as one for the local network only,
  reads as not applicable and is left alone.
- Notifications now also cover rows that need attention or are not applied
  yet, one for each problem and colour.

## [0.2.0] - 2026-09-23

Black Ops now covers only what stock Omarchy ships and sets up. Protections
for apps you install yourself belong to those apps.

### Removed

- The rows for the onnxruntime telemetry folder and its stray file sweep,
  Ollama's cloud features, the optional ollama.com block, Open WebUI's code
  execution and a VPN app's crash reports.
- `mobile.events.data.microsoft.com` and
  `o4507954455314432.ingest.us.sentry.io` from the hosts block, which now
  holds only Claude Code's Datadog intake.
- The helper verbs `onnx-lock`, `onnx-unlock`, `ollama-dropin-on`,
  `ollama-dropin-off`, `ollama-block-on` and `ollama-block-off`, and their
  lines in the sudoers rule.

### Added

- A `version` verb for the helper, which the rule allows and the installer
  uses to confirm what it installed.
- The panel compares the installed helper with the one in the plugin folder
  and, when they differ, says the installer needs running again, turns the
  lock amber while Black Ops is on, and never runs the old helper.
- Each row now reads as not applicable, with no error, on a machine that
  lacks what it protects, such as no chosen weather location, no Agents
  widget on the bar, or Claude Code never started.

### Changed

- Upgrading from 0.1 undoes nothing. The first run of 0.2.0 forgets the
  removed rows in the state file without reverting them. Switching on moves
  the other hosts 0.1 kept in the block out of it, to plain lines just above
  it with a comment, where they stay blocked; switching off in 0.2.0 removes
  only the Datadog pair and the block markers. The Ollama drop-in, the
  onnxruntime folder, Open WebUI's settings and the VPN app's settings are
  left exactly as they were.
- Any other line found inside the hosts block is moved out of it and kept,
  rather than dropped.
- The README describes each problem as it is in stock Omarchy 4.0.4.

## [0.1.1] - 2026-09-23

### Changed

- Off no longer claims the machine is stock when protections are in place by
  hand; it says how many are, and that the plugin is not managing them.
- The README opens with the exact problems each protection solves, what was
  seen on the machine for each, and what the plugin does not solve.

## [0.1.0] - 2026-09-23

### Added

- A bar widget with one main switch for nine privacy protections: three
  telemetry hosts blocked in a marked block in /etc/hosts, the onnxruntime
  telemetry folder emptied and locked, Ollama's cloud features and
  systemd-resolved's fallback servers turned off by drop-ins, the weather
  location rounded, the Agents panel limited to Claude, Claude Code's
  telemetry and error reporting turned off, Open WebUI's code execution
  turned off, and a VPN app's crash reports turned off.
- An optional block for ollama.com, with its own switch, which the main
  switch never turns on.
- Adoption of protections that are already in place, so nothing is applied
  twice, and migration of hand-written hosts lines into the marked block.
- Switching off, which undoes only what the plugin applied or adopted and
  leaves the machine as it ships. The weather rounding is the one exception,
  and the panel says so.
- A watchdog that checks every ten minutes, turns the bar icon amber when a
  protection has slipped, and sends one desktop notification per slip.
- `bin/black-ops-install`, which installs a root-owned helper accepting ten
  fixed verbs and a sudoers rule, checked with visudo, that allows exactly
  those verbs without a password. `--uninstall`, `--dry-run` and
  `--print-sudoers` are supported.
- A test suite that runs against a fake machine in a temporary folder and
  never touches the real system.
