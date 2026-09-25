# omarchy-black-ops

One switch in the Omarchy bar for a set of privacy protections in stock
Omarchy. Switched on, it keeps the weather panel from sending your precise
location, stops the Agents panel from asking services you have not set up,
stops systemd-resolved from falling back to public DNS servers, turns off
Claude Code's telemetry with a hosts file entry as a backstop, keeps
Bluetooth from accepting pairing, stops the
host name and hardware MAC
address reaching every network, sets Chromium's privacy policies, turns off
NetworkManager's connectivity check and Avahi's announcements, gives each
web app a browser profile of its own, turns off usage reports in the
developer tools Omarchy installs and Neovim's plugin update check, and sets
the usual opt-out variables such as `DO_NOT_TRACK`. Nine more protections
are optional and off until you switch each one on. Switched off, Black Ops removes all of that
again and leaves the machine as it ships.

A watchdog checks every ten minutes that each protection is still in place.
When one has slipped, which is usually an update putting a file back, the
scope in the bar turns amber and a single desktop notification says which one.
After Omarchy itself is updated, the first check is strict: see
[After an Omarchy update](#after-an-omarchy-update).

The plugin is a privacy tool first, so it sends nothing anywhere and logs
nothing sensitive. See [Privacy](#privacy).

## What this solves

Each protection answers one problem found in stock Omarchy 4.0.4 in a privacy
audit on 2026-09-23. The audit read the installed code and configuration and
watched DNS lookups and connections. Each entry says what was seen, in which
program, and what the fix is. None of it is done by Black Ops itself, which
sends nothing anywhere. A row whose program is missing, or not set up yet, is
shown as not applicable and is left alone.

1. **The weather panel sends a precise location.** Omarchy's weather panel
   stores the place you choose in
   `~/.local/state/omarchy/settings/weather.json` at five decimal places,
   about a metre, and sends those coordinates with every refresh to wttr.in
   and open-meteo.com. A VPN does not hide this, because the location is
   inside the request. Reported upstream as
   [omarchy#13050](https://github.com/omacom/omarchy/issues/13050).
   *Solved by:* moving the stored coordinates to the centre of a square about
   1.5 miles (2.4 km) across, which is all a forecast needs.

2. **The Agents panel makes Codex fetch from GitHub.** The Agents widget is
   on the bar by default with every provider enabled. Its Codex usage check
   starts Codex's own client, which fetches OpenAI's plugin list from GitHub
   on each refresh and leaves a folder behind each time, whether or not you
   use Codex. Reported upstream as
   [omarchy#13051](https://github.com/omacom/omarchy/issues/13051).
   *Solved by:* the panel set to Claude only.

3. **A failing resolver sends DNS to Google, Cloudflare or Quad9.** Omarchy
   enables systemd-resolved, which falls back to public resolvers compiled
   into it when the configured ones stop answering. With a VPN, a tunnel that
   drops without a kill switch quietly hands every lookup to one of them.
   *Solved by:* an empty `FallbackDNS=`, so lookups fail instead.

4. **Claude Code sends telemetry to Datadog.** Omarchy installs Claude Code
   for every account, and it reports usage telemetry and errors by default.
   While it ran, it looked up `http-intake.logs.us5.datadoghq.com`, its
   Datadog intake, every ten to twenty seconds.
   *Solved by:* its own documented switches, `DISABLE_TELEMETRY` and
   `DISABLE_ERROR_REPORTING`, with that host blocked in `/etc/hosts` as a
   backstop in case an update stops honouring them.

5. **Bluetooth accepts pairing from anyone in range.** BlueZ makes the
   adapter pairable whenever it starts it, Omarchy's pairing agent accepts
   every request without asking, and the adapter announces the host name.
   Commented upstream on
   [omarchy#7889](https://github.com/omacom/omarchy/issues/7889).
   *Solved by:* pairing kept off, by a login service and by the watchdog,
   with a 60-second pair window in the panel, and the adapter named
   "laptop".

6. **Every network sees the host name and the hardware MAC address.**
   NetworkManager sends the host name in DHCP requests and uses the
   hardware address by default. Reported upstream as
   [omarchy#13054](https://github.com/omacom/omarchy/issues/13054).
   *Solved by:* a NetworkManager drop-in with no host name in DHCP, a stable
   per-network MAC address, and IPv6 temporary addresses. A drop-in of your
   own that sets some of these is left in place.

7. **Chromium sends what you type and more.** Chromium ships with search
   suggestions, page preloading, Google's error pages, the spelling service
   and usage reports on, and it searches the local network for Cast devices
   over mDNS. Reported upstream as
   [omarchy#13053](https://github.com/omacom/omarchy/issues/13053).
   *Solved by:* a managed policy file of its own beside Omarchy's
   `color.json`. Safe Browsing and updates are left as they are. Casting
   from Chromium stops working.

8. **NetworkManager checks in with archlinux.org.** It fetches
   `ping.archlinux.org` on every connection change and every few minutes.
   *Solved by:* a drop-in that turns the check off. One already turned off
   over D-Bus is adopted as it is.

9. **Avahi announces the machine to the local network.** Omarchy enables
   Avahi, which publishes the host name and addresses over mDNS.
   *Solved by:* `disable-publishing=yes`, as a marked edit to
   `avahi-daemon.conf` that switching off takes out byte for byte. Finding
   printers still works.

10. **Web apps share one browser profile.** Every web app Omarchy installs
    opens in the main Chromium profile, so each site can see the cookies and
    logins the others use.
    *Solved by:* a launcher that opens each web app in a profile of its own.
    It covers web apps started from the app launcher. Omarchy's keyboard
    shortcuts for web apps call its launcher directly and are not covered.

11. **Developer tools report usage.** gh, Codex and the Grok CLI send usage
    reports, mise looks up versions at its own server, and npm asks
    `registry.npmjs.org` for its own latest version on every run.
    *Solved by:* each tool's own setting: `gh config set telemetry
    disabled`, `[analytics] enabled = false` in `~/.codex/config.toml`,
    `[features] telemetry = false` and `[telemetry] trace_upload = false` in
    `~/.grok/config.toml`, `use_versions_host = false` for mise, and
    `update-notifier=false` and `fund=false` in `~/.npmrc`. Only those keys
    are touched, and a setting you made by hand is adopted.

12. **Neovim checks GitHub for plugin updates.** Omarchy's LazyVim setup
    turns on lazy.nvim's update checker, which fetches every installed
    plugin from GitHub about once an hour while Neovim is open, silently.
    *Solved by:* `enabled = false` in the checker table of
    `~/.config/nvim/lua/config/lazy.lua`.

13. **Nothing asks developer tools to stay quiet.** None of the common
    opt-out variables, `DO_NOT_TRACK` among them, is set anywhere.
    *Solved by:* a uwsm environment file that sets them for the session.

Optional, off until switched on one by one:

- The update badge, which runs `checkupdates` every six hours.
- herdr's update check, by sinking `herdr.dev`.
- The LocalSend port, which Omarchy opens to every network. A rule of your
  own, such as one for your local network only, is left alone.
- Debug symbol downloads from `debuginfod.archlinux.org`, turned off for the
  session through uwsm. Omarchy's crash diagnosis still sets its own server
  when you ask it for one.
- Omarchy's crash diagnosis offer, which puts up a notification for each
  crash that sends its details to an AI assistant when clicked.
- fwupd's peer sharing, which offers firmware metadata to other machines on
  the local network through Passim.
- The Avahi daemon, which still listens for and sends mDNS on the local
  network with announcing turned off. Masking it stops finding printers
  and other machines by name.
- Bluetooth address privacy, `Privacy=device` in
  `/etc/bluetooth/main.conf` as a marked edit, so on Bluetooth Low Energy
  the adapter uses a private address that changes over time instead of its
  fixed one. It is optional because it has a cost: Low Energy devices
  paired before it is switched on may need pairing again, and switching it
  on or off restarts Bluetooth, which drops connected devices for a few
  seconds.
- The Agents panel's Claude usage check, which sends your Claude Code
  sign-in token to `api.anthropic.com` every 15 minutes. Switched on, the
  panel no longer shows Claude usage; Claude Code itself is not affected.

Black Ops covers what stock Omarchy ships and sets up. Problems in apps you
install yourself, such as the onnxruntime telemetry that local AI tools can
bring in, are handled by those apps, not by Black Ops. Those apps can show
their own protections in the panel through [rows.d](#rows-from-other-stacks),
where they only report.

**What it does not solve.** It does not inspect traffic, so it cannot see a
new phone-home that nobody has found yet; the watchdog only confirms that the
known fixes are still in place. It does not stop what your browser, mail or
other everyday apps send, and it does not replace a VPN or a firewall. Data
that was sent before a protection was switched on cannot be recalled.

## The bar and the panel

The glyph is a rifle scope, so it cannot be mistaken for Security Scan's
lock beside it. Its colours are fixed rather than taken
from the theme, and match the lights in the panel. Green is on and holding,
amber is a real problem, grey is off or not applicable, and red is kept for
one thing: listen mode, when it is switched on, saw a program on
this machine contact a known telemetry host. Nothing else is red.

| Glyph | Meaning |
|---|---|
| Scope with a filled centre, green | On, and every protection is holding. |
| Scope with a filled centre, amber | On, but a protection has slipped, is not applied yet or needs attention, or the root helper needs reinstalling. |
| Scope with a filled centre, red | On, and a program was seen contacting a telemetry host. |
| Empty scope, dimmed | Off, not managing. Protections put in place by hand are counted and shown. |
| Empty scope, amber | Off, but something could not be removed. |

Clicking it opens the panel. The main switch sits at the top. Below it, each
protection has a row with a dot (green for holding, amber for a problem,
grey for off or not applicable), what it is doing now, a line explaining
what it does and why, and a switch of its own. A row switched off while the
main switch is on stays off until you switch it on again, and the watchdog
ignores it. When something has slipped or is not applied yet, a button
offers to put it in place; switching on again is always safe, because what
is already in place is left alone. With Bluetooth pairing on, a button opens
a 60-second pair window.

Middle-click the glyph to check again at once. From a keybinding:

```
omarchy-shell brightwalker25.black-ops toggle
omarchy-shell brightwalker25.black-ops switchOn
omarchy-shell brightwalker25.black-ops switchOff
```

## The protections

| Row | What switching on does | Needs root |
|---|---|---|
| Weather location | Moves the stored coordinates to the centre of a 1.5-mile square (one-way) | no |
| Agents panel | Leaves Claude on, turns Codex and Fireworks off | no |
| DNS fallback servers | Adds a drop-in with an empty `FallbackDNS=` and restarts systemd-resolved | yes |
| Claude Code telemetry | Sets `DISABLE_TELEMETRY` and `DISABLE_ERROR_REPORTING` | no |
| Claude Code telemetry host | Sinks Claude Code's Datadog intake on IPv4 and IPv6 in /etc/hosts | yes |
| Bluetooth pairing | Pairing off, a login service that keeps it off, the adapter named "laptop" | no |
| Network identity | `/etc/NetworkManager/conf.d/90-black-ops-identity.conf` | yes |
| Chromium privacy policy | `/etc/chromium/policies/managed/black-ops.json`; casting stops working | yes |
| Connectivity check | `/etc/NetworkManager/conf.d/90-black-ops-connectivity.conf` | yes |
| Avahi announcements | `disable-publishing=yes` in `avahi-daemon.conf`, marked | yes |
| Web app profiles | Each web app's launcher opens it in a profile of its own | no |
| Developer tool telemetry | The settings above for five tools, in each tool's own configuration | no |
| Neovim plugin update check | `enabled = false` in the checker table of `~/.config/nvim/lua/config/lazy.lua` | no |
| Opt-out variables | `~/.config/uwsm/env.d/90-black-ops-opt-out` with `DO_NOT_TRACK=1` and the rest | no |
| Update badge (optional) | Takes the badge off the bar | no |
| herdr update check (optional) | Sinks `herdr.dev` in /etc/hosts | yes |
| LocalSend firewall port (optional) | Deletes Omarchy's two `53317` rules from ufw | yes |
| Debug symbol downloads (optional) | `~/.config/uwsm/env.d/90-black-ops-debuginfod` with an empty `DEBUGINFOD_URLS` | no |
| Crash diagnosis offer (optional) | `systemctl --user mask omarchy-crash-watch` | no |
| Firmware peer sharing (optional) | `P2pPolicy=nothing` in `/etc/fwupd/fwupd.conf`, marked | yes |
| Avahi daemon (optional) | Stops and masks `avahi-daemon.service` and `avahi-daemon.socket` | yes |
| Bluetooth address (optional) | `Privacy=device` in `/etc/bluetooth/main.conf`, marked, and Bluetooth restarted | yes |
| Claude usage check (optional) | Turns Claude off in the Agents panel | no |

**Weather location.** The plugin moves the latitude and longitude in
`~/.local/state/omarchy/settings/weather.json` to the centre of a grid square
about 1.5 miles (2.4 km) on each side, the same width east to west as north
to south, and keeps the name. The square is fixed to the map, so a place
always gives the same point, and the stored point says only which square you
are in. This is the one change that is not undone: switching off does
not restore the precision, because the precise figures are not kept anywhere,
and the row says so. Until a place has been chosen, the row is not
applicable.

**Agents panel.** In `~/.config/omarchy/shell.json`, the `omarchy.agents`
entry's providers are set to Claude on, Codex off and Fireworks off, so the
panel stops asking services you do not use. If you do use Codex or Fireworks,
switch this row off. The change goes through `omarchy bar set`, which has the
running shell write the file itself; if the shell is not running, the file is
edited directly and atomically and the shell is told to reload. Switching off
sets all three back to enabled. With the widget not on the bar, the row is
not applicable. While the optional Claude usage check row is on, that row
decides Claude's value and this one leaves it alone.

**DNS fallback servers.** `/etc/systemd/resolved.conf.d/no-fallback.conf`
empties systemd-resolved's list of fallback servers. The row turns amber if a
drop-in sorted after it sets fallback servers again.

**Claude Code telemetry.** `DISABLE_TELEMETRY` and `DISABLE_ERROR_REPORTING`
are set to `"1"` in the `env` section of `~/.claude/settings.json`
(`$CLAUDE_CONFIG_DIR` is honoured). Switching off removes those two keys and
nothing else, and removes `env` itself only if the plugin created it. Until
Claude Code has been started once and made its settings folder, the row is
not applicable.

**Claude Code telemetry host.** `http-intake.logs.us5.datadoghq.com` is
mapped to `0.0.0.0` and `::` inside a block marked `# BEGIN black-ops` and
`# END black-ops`, and the resolver cache is flushed after every change.
Lines for the same host added by hand are moved into the block the first time
it is switched on, so the file never holds them twice. Any other line found
inside the block is moved out of it and kept, never deleted. Without Claude
Code set up, and with no block in place, the row is not applicable.

**Chromium privacy policy.** The policy includes `EnableMediaRouter`
set to false, which stops Chromium searching the local network for Cast
devices, so casting from Chromium stops working. A policy file written by
0.3.0 lacks it and reads as not applied yet, in amber, until the row is
applied again.

**Bluetooth address.** Low Energy devices paired before this is switched
on, such as some mice, keyboards and earbuds, may not reconnect until they
are paired again, because they were never given the key that recognises a
private address; devices paired afterwards are not affected. BlueZ reads
the setting only when it starts, so switching on or off restarts
`bluetooth.service` if it is running, which drops connected devices for a
few seconds. The restart makes the adapter pairable again, so with
Bluetooth pairing on, its login service is run at once to turn that off.
The row reads the setting from `main.conf` and, where `btmgmt` is
installed, confirms from the adapter that it is in effect. Classic
Bluetooth, which most headphones use, keeps the fixed address; the
`(public)` that `bluetoothctl show` prints is that address. The adapter's
`Name` is left alone, since the "laptop" alias already replaces it.

**Avahi daemon.** Finding printers and other machines on the local network
by name stops working. With both units masked, nothing starts the daemon
again, and the Avahi announcements row reads as not applicable rather than
amber, since a stopped daemon announces nothing. `/etc/nsswitch.conf` and
the ufw rules for mDNS are left alone; they do nothing with the daemon
stopped. Switching off unmasks both units and starts whichever of them is
enabled, as Omarchy ships them.

**Developer tool telemetry.** Its cost: npm no longer says when a newer npm
is out, and mise lists versions from each tool's own source, such as
GitHub, which can be slower. For npm, `update-notifier=false` and
`fund=false` are written to `~/.npmrc` (`$NPM_CONFIG_USERCONFIG` is
honoured) as plain `key=value` lines. A key already there is changed where
it stands, a missing one is added at the end, and switching off puts back
the old line or takes out the added one, byte for byte. `audit` is left
alone. Without npm on the `PATH`, npm is left out of the count. The value
reads "5 of 5 off" when every tool is installed.

**Neovim plugin update check.** Its cost: Neovim's status line no longer
shows that plugin updates are waiting; `:Lazy update` still works when you
ask. Only the `true` after `enabled =` inside `checker = { ... }` in
`~/.config/nvim/lua/config/lazy.lua` is changed, to `false`, and switching
off changes it back only if Black Ops made the change. A checker already off
is adopted. If the file is not there, the row is not applicable. If it does
not have one plain `checker` table with one `enabled = true` or `false` in
it, the row turns amber, says why, and leaves the file alone. It applies the
next time Neovim starts.

**Opt-out variables.** Its cost: Deno and HashiCorp tools such as Terraform
no longer say when a newer version is out. The file is written the same way
as the debug symbol one, one `export NAME=value` line each, for
`DO_NOT_TRACK=1`, `DENO_NO_UPDATE_CHECK=1`, `NEXT_TELEMETRY_DISABLED=1`,
`DOTNET_CLI_TELEMETRY_OPTOUT=1`, `CHECKPOINT_DISABLE=1`,
`ASTRO_TELEMETRY_DISABLED=1`, `GATSBY_TELEMETRY_DISABLED=1`,
`TURBO_TELEMETRY_DISABLED=1`, `STORYBOOK_DISABLE_TELEMETRY=1`,
`AZURE_CORE_COLLECT_TELEMETRY=0`, `POWERSHELL_TELEMETRY_OPTOUT=1`,
`SAM_CLI_TELEMETRY=0`, `VCPKG_DISABLE_METRICS=1` and `HINT_TELEMETRY=off`.
Claude Code reads `DO_NOT_TRACK` exactly as it reads `DISABLE_TELEMETRY`,
which the Claude Code telemetry row sets already, so it changes nothing else
there. The row also sets the variables the session does not have yet in the
systemd user manager, so programs started from the desktop get them at
once; they apply fully from the next login. Switching off removes the file
and unsets only the variables it set. Variables already set by hand in the
session are adopted. Without uwsm, which reads the file, the row is not
applicable.

**Debug symbol downloads.** The value is set through uwsm rather than
`~/.config/environment.d`, because uwsm passes the login shell's
environment to the session after environment.d has been read, and Arch's
`/etc/profile.d/debuginfod.sh` sets the server there. The row takes it out of
the running session at once and fully from the next login.

**Firmware peer sharing.** `/etc/fwupd/fwupd.conf` is readable only by root,
so the row reads the policy back from the flags fwupd puts on its remotes,
and only while fwupd is already running; it never starts fwupd to ask.

**Claude usage check.** Its cost: the Agents panel no longer shows Claude
usage. Claude Code itself works exactly as before: the row changes only the
`omarchy.agents` entry in `~/.config/omarchy/shell.json` and never reads or
changes anything in `~/.claude`. The widget's collector,
`omarchy-agent-usage-claude`, sends your Claude Code sign-in token to
`api.anthropic.com` to read usage every `refreshIntervalSec` (900 seconds,
15 minutes, by default), 30 seconds after the shell starts and when the
panel opens. Switching this on sets Claude's provider to off, through the
same `omarchy bar set` call and atomic fallback the Agents panel row uses, so
the widget passes `--except claude` and the collector never runs. With every
provider off the widget stays on the bar, runs no collector at all, and its
panel says it has no subscriptions to show. Switching off turns Claude back
on only if this row turned it off. The main switch never switches it on.

## What off means

Off means the machine as it ships. Switching off undoes every row the plugin
applied or adopted:

- the hosts block goes, with the Datadog lines in it, and every line outside
  it stays;
- the DNS, network identity and connectivity drop-ins and the Chromium
  policy file are removed, and the services are told to reload;
- the marked lines in `avahi-daemon.conf`, `fwupd.conf` and Bluetooth's
  `main.conf` are taken out and whatever they had commented out is put back,
  and Bluetooth is restarted;
- the Avahi daemon is unmasked and started again;
- the Agents panel has all three providers enabled again;
- the two Claude Code keys are removed;
- the Bluetooth login service goes and the adapter gets its own name back;
  pairing is left as it is, and BlueZ makes it pairable again when it next
  starts the adapter;
- each web app's launcher is put back as it was; the profiles hold your
  logins for those sites, so they are kept in
  `~/.local/share/black-ops-webapps`;
- gh's telemetry is set to `enabled`, mise's setting is unset, and the Codex
  and Grok keys are taken out, with a table the plugin added removed once it
  is empty; the npm lines are put back as they were, and `~/.npmrc` is
  removed if the plugin created it;
- Neovim's update checker is set back to `enabled = true`;
- the opt-out variables file goes, and the variables it set in the running
  session are unset;
- an optional row's change is undone in the same way.

The weather location stays on its grid square, as described above.

A protection that was already in place when the plugin was first switched on
is *adopted*. It is recorded, not applied a second time, and it is removed on
the way off like any other. A protection you add by hand after switching on,
or on a row you had switched off, is not the plugin's, and switching off
leaves it alone. The record of which rows are the plugin's is kept in
`~/.local/state/omarchy-black-ops/state.json`.

## After an Omarchy update

Black Ops records the Omarchy version (`pacman -Q omarchy`) when it is
switched on. The first check after that version changes is strict: the
headline and every row that is not holding say that it has been so since the
update, and the new version becomes the baseline only once every protection
passes. Until then the check is repeated with that wording on every tick.

## Software watch and listen mode

Two optional rows look past stock Omarchy. They report on any program, but
the only fixes Black Ops switches are still the stock ones above; for
anything else the panel shows the opt-out it found.

The software watch notes everything you install, from pacman and the AUR,
Flatpak, AppImages, pip, npm and mise, and scans each new or changed item
on this machine for telemetry: known telemetry libraries, telemetry
switches, Sentry addresses, crash uploads and update checks. It runs no
program it scans and needs no root. A pacman hook records new packages at
once; the other sources are checked when their folders change, daily, and
in full once a week. A flagged item turns the scope amber until you review
it, and it is flagged again only if a later version adds something new.
Details are in [docs/watch.md](docs/watch.md).

Listen mode records which program on this machine contacted which host. It
joins systemd-resolved's lookups to a bpftrace probe on outgoing
connections, keeps the record in RAM, and shreds it after 72 hours by
default. It is off until switched on, needs `sudo pacman -S bpftrace`, and
sends nothing anywhere. A contact with a known telemetry host turns the scope
red. It cannot see lookups a browser makes over DNS-over-HTTPS, and shows a
program that connects to a fixed address by that address only. Details are
in [docs/listen.md](docs/listen.md), and the panel is described in
[docs/panel.md](docs/panel.md).

## Rows from other stacks

Other stacks, such as Nightloom, can show their own protections in the panel
by writing a JSON file to `~/.config/omarchy-black-ops/rows.d/`. Those rows
only report: they have no switch, their checks are declarative, and a file
there can never make Black Ops run a program or send anything. A file that
anyone else can write, or that does not follow the format, is skipped and
named in the panel. The format is in [docs/contract.md](docs/contract.md),
section 10.

## Upgrading from 0.3

0.4.0 adds helper verbs and a key to the Chromium policy, so run the
installer once more after pulling:

```
sudo ~/Work/omarchy-black-ops/bin/black-ops-install
```

The Chromium policy then reads as not applied yet, in amber, rather than
as slipped. Use "Apply what is new" in the panel, or run `bin/black-ops
on`. The Avahi daemon and Bluetooth address rows are optional and stay off.

## Upgrading from 0.2

0.3.0 adds rows and helper verbs, so run the installer once more after
pulling:

```
sudo ~/Work/omarchy-black-ops/bin/black-ops-install
```

Until then the rows that need root say the helper needs reinstalling. The
rows new in 0.3.0 read as not applied yet, in amber, rather than as slipped.
After installing, switch Black Ops on once more in the panel, or run
`bin/black-ops on`, which puts them in place and adopts whatever you have
already set by hand. The optional rows stay off.

## Upgrading from 0.1

Version 0.1 also managed protections for apps that stock Omarchy does not
install. They left Black Ops in 0.2.0 without being undone:

- The next run, whether a status check or switching on, forgets those rows
  in the state file and changes nothing else.
- Hosts that 0.1 kept inside the block, other than Claude Code's, are moved
  out of it the next time Black Ops is switched on, to plain lines just
  above it with a comment saying what they are for. They stay blocked, and
  switching Black Ops off no longer removes them.
- Everything else those rows managed is left exactly as it is.

The helper that makes the changes needing root is different in 0.2.0, so run
the installer once more after pulling:

```
sudo ~/Work/omarchy-black-ops/bin/black-ops-install
```

Until then the panel says the helper needs reinstalling, the scope is amber
while Black Ops is on, and the two rows that need root are left as they are.
The old helper is never run, because its way of switching off would remove
the lines that now belong to other apps. After installing, switch Black Ops
on once more in the panel, or run `bin/black-ops on`, so the block is
rewritten.

## Installing

The plugin is not in any registry yet. From a clone at
`~/Work/omarchy-black-ops`, three steps sit outside the repository.

1. Link the plugin into Omarchy's plugin folder:

   ```
   ln -s ~/Work/omarchy-black-ops ~/.config/omarchy/plugins/brightwalker25.black-ops
   omarchy-shell shell rescanPlugins
   ```

2. Put it on the bar. This adds `{ "id": "brightwalker25.black-ops" }` to
   `bar.layout.right` in `~/.config/omarchy/shell.json`:

   ```
   omarchy plugin enable brightwalker25.black-ops --section right
   ```

   `--before <id>`, `--after <id>` and `--index <n>` choose the position, for
   example `--before brightwalker25.security-scan`.

3. Run the privileged installer once:

   ```
   sudo ~/Work/omarchy-black-ops/bin/black-ops-install
   ```

   Run it again after pulling a new version, since the helper is a copy. The
   panel compares the installed copy with the one in the plugin folder and
   says when they differ. `bin/black-ops-install --dry-run` shows every
   action without root and changes nothing.

Nothing is switched on by installing. Open the panel and use the main switch.

### What the privileged step installs

A bar panel has nowhere to type a password, so the changes that need root
are made by a small helper that sudo lets your account run without one. The
installer writes these two, plus the software watch's hook and listen mode's
service, described in [docs/watch.md](docs/watch.md) and
[docs/listen.md](docs/listen.md):

| Path | What it is |
|---|---|
| `/usr/local/lib/omarchy-black-ops/apply` | The helper, owned by root, mode 755 |
| `/etc/sudoers.d/omarchy-black-ops` | A rule, mode 0440, checked with `visudo -cf` before it is moved into place |

The rule names the helper once for each verb it accepts, so sudo itself
refuses anything else:

```
version
hosts-on          hosts-off
dns-on            dns-off
identity-on       identity-off
chromium-on       chromium-off
connectivity-on   connectivity-off
avahi-on          avahi-off
herdr-block-on    herdr-block-off
localsend-close   localsend-open
fwupd-p2p-on      fwupd-p2p-off
listen-on         listen-off        listen-purge
bt-privacy-on     bt-privacy-off
avahi-mask        avahi-unmask
```

`version` prints the helper's version and changes nothing; the installer uses
it to confirm what it installed. No verb takes a path or any other text. The
helper refuses to run unless it is root and unless its own file and every
folder above it are owned by root and writable by nobody else. It opens every
folder one component at a time without following links, writes each file
under a new name and renames it into place, and refuses a target that turns
out to be a link. It runs under `python3 -I`, so no environment variable can
change what it loads. Installing replaces both the helper and the rule, so a
verb an earlier version had stops working as soon as the installer has run.

To see the rule before installing:

```
~/Work/omarchy-black-ops/bin/black-ops-install --print-sudoers (whoami)
```

## Uninstalling

Switch Black Ops off in the panel first if you want the machine returned to
stock. Then:

```
sudo ~/Work/omarchy-black-ops/bin/black-ops-install --uninstall
omarchy plugin disable brightwalker25.black-ops
rm ~/.config/omarchy/plugins/brightwalker25.black-ops
rm -r ~/.local/state/omarchy-black-ops ~/.local/state/black-ops
rm -rf ~/.local/share/omarchy-black-ops ~/.config/omarchy-black-ops
```

`--uninstall` removes the helper and the rule and leaves the protections as
they are. It prints the root-owned pieces to remove by hand if the plugin
was not switched off first.

## Settings

| Setting | Default | Effect |
|---|---|---|
| Check every (minutes) | 10 | How often the watchdog runs, with the panel open or closed |
| Notify when a protection slips | on | One notification per problem, and no more until it has gone or its colour has changed |

## Privacy

The plugin makes no network connection of any kind. A check reads local files
and nothing else. It asks sudo for nothing, so the watchdog leaves nothing in
the journal. A test replaces the socket functions
with ones that fail and runs a full check and a switch-on against them.

It keeps no log. The state file records row names, the words "applied" or
"adopted", times, short error messages, the Omarchy version last checked,
the Bluetooth name it replaced, the update badge's place on the bar, and
which developer tools it changed. It never records a coordinate or the
contents of a file, and it is readable only by you.

It also writes `~/.local/state/black-ops/summary.json`, readable only by
you, for tools such as Security Scan. That file holds counts and states and
nothing else: no host, program, path or file name.

Two things outside the plugin do record something. sudo writes each helper
call to the system journal, as it does for every sudo command, and that entry
holds the verb, such as `dns-on`, and nothing else. The desktop notification
for a slip names the protection, such as "DNS fallback servers has slipped",
and stays in the notification history; it can be turned off in the settings.

## From a terminal

The script the panel runs works on its own:

```
bin/black-ops --text           # every row, one line each
bin/black-ops --pretty         # the JSON the panel reads
bin/black-ops on
bin/black-ops off
bin/black-ops row claude off   # one row
```

Row ids: `weather`, `agents`, `dns`, `claude`, `hosts`, `bluetooth`,
`identity`, `chromium`, `connectivity`, `avahi`, `webapps`, `dev-telemetry`,
`nvim-checker`, `opt-out-env`, and the optional `update-badge`, `herdr`,
`localsend`, `debuginfod`, `crash-watch`, `fwupd-p2p`, `avahi-daemon`,
`bt-privacy` and `claude-usage`. `bin/black-ops pair` opens the Bluetooth
pair window.

## Adding a protection

Each row is a small class in `bin/black-ops` with a `check`, an `apply` and a
`revert`, listed once in `ROWS`; the `Row` class says what each must do. A
row that needs root also needs a verb in `system/apply` and in the
installer's `VERBS`, and a test checks that the two lists agree. A row that
is later removed goes in `FORMER_ROWS`, and its record is forgotten rather
than reverted.

The software watch and listen mode live in `lib/`, against the fixed
interface in [docs/contract.md](docs/contract.md).

## Tests

```
python3 -m pytest
```

The tests never touch the real `/etc`, your home folder or any service. Each
one builds a fake machine in a temporary folder, points every path at it
through environment variables, and stubs `sudo`, `systemctl`, `resolvectl`,
`notify-send` and the rest. The stub sudo allows exactly the commands the
installer's rule names, and runs the real helper with its paths moved into
the sandbox. The tests refuse to run as root.

## Limits

- JSON files are rewritten with the indent they already had and their keys in
  the same order, so a file written by jq or Omarchy comes back byte for byte
  apart from the changed values. A file laid out unevenly by hand would come
  back evenly laid out, with the same content.
- The DNS row looks for overriding drop-ins in `/etc/systemd/resolved.conf.d`
  only, not in `/run` or `/usr/lib`.
- Omarchy's keyboard shortcuts for web apps, such as Super+Shift+A, are not
  covered by the web app profiles row.
- The firmware peer sharing row cannot confirm the policy while fwupd is not
  running, and trusts its own record until fwupd next runs.
- The Bluetooth address row covers Bluetooth Low Energy only. Classic
  Bluetooth always uses the fixed address, and without `btmgmt` the row
  trusts `main.conf`.
- The hosts block and the helper refuse to work through a symbolic link, so a
  machine whose `/etc/hosts` is a link cannot use the hosts row.

## Written with AI help

Yes, an AI helped write this. No, it is not Skynet (or is it? 😉). Either
way, I have checked the code to make sure it is not plotting Judgment Day. If
that still puts you off, no hard feelings. The whole point of Linux is that
you decide what runs on your computer.

## Licence

MIT. The bar widget and the panel scaffolding are derived from Omarchy's own
plugins; see [LICENSE](LICENSE).
