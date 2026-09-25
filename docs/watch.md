# The software watch

The software watch looks through the software installed on this machine for
signs of telemetry, crash reporting and analytics. It covers any program,
not only what Omarchy ships. It reads files and nothing else: it never runs
a program it scans, it needs no root, and it sends nothing anywhere.

It is an optional row, off until you switch it on in the panel or with:

```
bin/black-ops row watch on
```

## What it looks at

The watch keeps an inventory of what is installed:

- pacman packages, including foreign ones built from the AUR;
- flatpaks, system and user, with their permissions;
- AppImages in `~/Applications`, `~/.local/bin`, `~/Downloads`,
  `~/AppImages`, the home folder itself and `/opt`;
- pip distributions in the user site-packages and in virtual environments;
- global npm packages, in the npm prefix, `~/.npm-global` and mise's Node;
- mise installs, the version in use for each tool;
- loose programs in `~/.local/bin`, `~/.cargo/bin` and `~/bin`, and folders
  under `/opt` that no package owns.

The first scan reads everything. After that, a scan reads only what is new
or has changed: a package whose version differs, or a file whose size or
modification time differs. The weekly scan reads everything again.

## What it looks for

In order of how much each says:

1. A telemetry library, by its package name: `sentry_sdk`, `posthog`,
   `wandb`, `gradio`, `streamlit`, `onnxruntime`, `chromadb`, `langsmith`,
   OpenTelemetry exporters, Scarf, Statsig, Mixpanel, Amplitude, Segment and
   the `@sentry` packages. Names are read from dist-info folders, from
   `node_modules` folders and from the header of an Electron `app.asar`.
2. A telemetry switch in a program's files, such as `GH_TELEMETRY` in gh or
   `DISABLE_TELEMETRY`. Only a switch with no prefix, or one that starts with
   the program's own name, counts. A switch named for another tool, such as
   `DOTNET_CLI_TELEMETRY_OPTOUT` inside a version manager, is kept as a note.
   Browsers are skipped for this signal, because their code is full of
   constants with the word in them and their telemetry is set through their
   preferences.
3. A Sentry key, a host such as `o123.ingest.us.sentry.io`.
4. An Electron crash reporter set with `uploadToServer: true` in the app's
   own code.
5. A host from `data/signatures.toml`, such as Datadog's intake, and a
   telemetry or crash report host of the program's own vendor, such as
   `telemetry.<vendor>.com`. Google Analytics counts only in a program's own
   code and never in a browser, since browser engines carry its hosts in
   their block lists.
6. What programs leave behind in the home folder: Glean pings waiting to be
   sent, crash reports marked as submitted, a usage statistics consent file
   holding a client id, and telemetry state files.

A host in a small text file that exists to block it is kept as a note
instead of being flagged: every line naming the host maps it to `0.0.0.0`,
`127.0.0.1` or `::`, as a hosts file does, or the file holds a block list
(a name such as `BLOCKED_HOSTS` or `BLOCKLIST`), refers to `/etc/hosts` and
has a null address. A file that also uses the host in a URL, and any binary,
is flagged as usual.

Weaker signs are kept as notes and change no colour: an update check (for
example `latest-linux.yml` or a `*_DISABLE_UPDATE` switch), a flatpak with
network access and the whole file system, an installation id, a downloaded
IP location database, crash reports a Chromium based program has written,
and files the watch could not read.

Compressed files are handled like this. A `.br` file is read through
`brotli -dc` when brotli is installed. An `app.asar` is read directly, as it
is not compressed. An AppImage's payload is read through `unsquashfs` when
it is installed, one file at a time and without unpacking it to disk; the
watch never uses `--appimage-extract`, because that runs the AppImage.
Without unsquashfs, the AppImage is listed as not read.

Each scan reads files with GNU grep in batches, with a memory limit on each
grep, at the lowest CPU and disk priority. Files over 512 MiB, pictures,
fonts, translations and documentation are skipped. A scan stops starting new
work after three hours, and the next scan carries on from there.

## Findings

Each flagged item names the program, says in one sentence what was found,
and carries its evidence: the file and the string matched. Where an opt-out
is known it is given, and when the program has a telemetry switch, the
switch found is the suggested opt-out. The value to give it is in the
program's own documentation.

A flagged item is amber until you review it. Nothing the watch finds is ever
red; red is kept for listen mode, which sees a program actually contact a
telemetry host.

```
bin/black-ops watch list                # flagged and not reviewed
bin/black-ops watch list --all          # reviewed ones too
bin/black-ops watch list --notes        # and the notes
bin/black-ops review ID allow           # or false-positive, or clear
bin/black-ops review ID allow --note "Checked; its switch is set."
bin/black-ops review --all allow        # every watch item not reviewed yet
```

`review --all` covers the watch's items. Add `--source listen` or
`--source any` to include listen mode's.

A reviewed item stays reviewed through updates. It is flagged again only
when a later version of the program adds something the review did not see,
such as a new switch or a new host. When a program's file moves to a new
path, as an AppImage does when renamed for a new version, the review moves
with it, as long as nothing new was found.

## The first scan

Switching the row on starts the first scan in the background. It usually
finds a number of programs at once, which is the state the machine was
already in. They are flagged and listed as usual, but while only they are
waiting, the headline reads "the first scan found N items to review" and
the watch row itself does not ask for attention. Anything found after the
first scan has read everything is counted as new. To accept all of them as
they are, as a baseline:

```
bin/black-ops watch baseline            # says how many would be accepted
bin/black-ops watch baseline --yes
```

From then on, only something new is flagged.

## When it scans

Switching the row on writes these user units to `~/.config/systemd/user`
and enables them. Switching it off stops and removes them.

| Unit | When |
|---|---|
| `black-ops-watch.path` | pacman has installed or upgraded packages; scans those packages |
| `black-ops-watch-user.path` | something changed in the user install folders or a virtual environment; scans what changed |
| `black-ops-watch-daily.timer` | daily, and on the next start if the machine was off; scans what changed |
| `black-ops-watch-weekly.timer` | weekly, the same way; scans everything |

Each scan runs as a one-shot service with `Nice=19` and the idle disk
scheduling class. You can also scan by hand:

```
bin/black-ops watch scan --changed      # or --pending, or --full
bin/black-ops watch status
```

### The pacman hook

pacman runs as root, so it cannot start a user unit. The installer adds a
hook that runs after each transaction and a small root-owned script that
writes the names of the packages installed or upgraded, and nothing else,
to `/var/lib/omarchy-black-ops/pending`. The user's watch reads that folder.
The script never fails a transaction, and it removes its files after 30
days.

The installer puts these in place:

| Path | What it is |
|---|---|
| `/etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook` | The hook, mode 644 |
| `/usr/local/lib/omarchy-black-ops/watch-spool` | The script it runs, owned by root, mode 755 |
| `/var/lib/omarchy-black-ops/pending/` | The folder it writes to, mode 755 |

Without the hook the watch still works on its timers, and the row asks for
attention to say so.

## Settings

An optional file, `~/.config/omarchy-black-ops/watch.toml`:

```toml
venvs = ["~/somewhere/.venv"]     # virtual environments to add
venv_roots = ["~/AI", "~/Work"]   # folders searched for pyvenv.cfg
venv_depth = 4                    # how deep that search goes, 1 to 8
skip = ["~/Downloads"]            # folders never read
```

Without it, virtual environments are found by their `pyvenv.cfg` under
`~/AI`, `~/Work`, `~/Projects`, `~/src`, `~/code`, `~/.venvs`,
`~/.virtualenvs`, and the pipx, virtualenv and uv tool folders, four levels
deep.

## What it keeps

Under `~/.local/state/black-ops`, readable only by you:

| File | What it holds |
|---|---|
| `inventory/index.json` | Every file read, with its size, modification time, package, version and the signatures found in it |
| `inventory/spool-seen.txt` | The spool files already read |
| `watch.json` | Flagged items with their evidence, notes, and the last scan |
| `reviewed.toml` | Your reviews |

`summary.json`, which Security Scan reads, holds only the number of flagged
and unreviewed items and the time of the last scan. Switching the row off
keeps these files, so your reviews survive. To remove them:

```
rm -r ~/.local/state/black-ops/inventory ~/.local/state/black-ops/watch.json
```

## Limits

- A program that builds its telemetry host at run time, or keeps it
  encrypted, is found only by its library or its switch, if at all.
- pip distributions are recognised by name; their files are not read.
- An AppImage's payload needs unsquashfs, from the squashfs-tools package.
- The user .path unit lists the virtual environments found when the row was
  switched on. A new one is picked up by the daily scan, or at once after
  switching the row off and on again.
- A string in a program is not proof that it sends anything. Listen mode is
  what confirms a contact.
