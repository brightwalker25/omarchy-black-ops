# Black Ops phase 2 contract

Contract version 2, fixed with Black Ops 0.3.0. Version 2 adds the
software watch's changes listed in section 16. Four pieces of work are
built against this file at the same time:

- A, the software watch: `lib/black_ops_watch.py`, the pacman hook, the user
  units and timers, the static scan, the inventory and the review store.
- B, listen mode: `lib/black_ops_listen.py`, the root service
  `omarchy-black-ops-listen`, its RAM store and three helper verbs.
- C, the panel: the watch and listen rows and the review list in
  `Panel.qml`, and anything the bar needs in `BarWidget.qml`.
- D, Security Scan: a Privacy section that reads
  `~/.local/state/black-ops/summary.json`.

Everything below is fixed. A change to a field, a path, a verb or a format
goes through the coordinator and bumps the contract version at the top, so
that no piece is built against a shape another piece no longer produces.
Where this file says "may", the choice is the builder's.

## 1. Rules every piece keeps

1. Nothing Black Ops does sends data anywhere. No piece opens a network
   connection, resolves a name, or starts a program that does. Listen mode
   observes the machine's own traffic and keeps what it sees in RAM.
2. Colours: green is on and holding; amber is a real problem; grey is off,
   not applicable, or reviewed. Red means one thing only: listen mode saw a
   program on this machine contact a host that matches a signature of kind
   `telemetry`, `analytics` or `crash-report`, and nobody has reviewed it.
   A static finding, a slipped protection, a missing hook or a stale scan is
   amber at most. When anything is red, the overall colour is red.
3. Detection may cover any program on the machine. Anything that switches
   something covers stock Omarchy only.
4. The account name and `/home/<name>` never appear in a file in the
   repository. Paths are written as `~/...` in docs and built from `$HOME` or
   the XDG variables in code. Files outside the repository that the
   installer writes, such as a systemd unit, may name the account.
5. summary.json holds counts and states only: no host, program, package,
   path or file name.
6. Prose in the README, CHANGELOG and comments: plain sentences, no
   em-dashes, no idioms, no bold for emphasis.
7. The tests never touch the real `/etc`, home folder, `/run`, `/var` or any
   service. Every path a piece uses can be moved into the test sandbox (see
   section 11).

## 2. Who edits what

| File | Owner |
|---|---|
| `lib/black_ops_watch.py` | A |
| `lib/black_ops_listen.py` | B |
| `system/listen` (the root listener) | B |
| `system/watch-spool` (the pacman hook's program) | A |
| `system/apply` | B adds the three listen verbs and nothing else |
| `bin/black-ops-install` | A edits only between the `# ---- watch` markers, B only between the `# ---- listen` markers, and B adds its three verbs to `VERBS` |
| `data/signatures.toml` | read by A and B; entries added through the coordinator |
| `Panel.qml`, `BarWidget.qml` | C |
| Security Scan repository | D |
| `bin/black-ops` | nobody in phase 2; ask the coordinator for a change to the core |
| `tests/test_watch.py`, `tests/test_listen.py`, `tests/test_panel_contract.py` | A, B, C respectively |

README and CHANGELOG entries are written by each piece for its own part,
under headings of its own, so that merges do not collide.

## 3. Paths

`$STATE` is `$XDG_STATE_HOME`, or `~/.local/state` when that is unset.

| Path | Written by | Mode | What it holds |
|---|---|---|---|
| `$STATE/omarchy-black-ops/state.json` | core | 0600 | Which rows are on; unchanged from 0.2 apart from the `omarchy` key |
| `$STATE/black-ops/` | core, A | 0700 | The folder for everything below |
| `$STATE/black-ops/summary.json` | core | 0600 | Section 7 |
| `$STATE/black-ops/reviewed.toml` | A (the review command) | 0600 | Section 9 |
| `$STATE/black-ops/inventory/index.json` | A | 0600 | Section 5.4 |
| `$STATE/black-ops/inventory/spool-seen.txt` | A | 0600 | Spool file names already processed, one per line |
| `$STATE/black-ops/watch.json` | A | 0600 | The watch's own flagged items and last-scan record, section 5.5 |
| `~/.config/systemd/user/black-ops-watch*.{path,service,timer}` | A (the watch row) | 0644 | Section 5.2 |
| `~/.config/omarchy-black-ops/rows.d/*.json` | other stacks | 0644 | Rows that only report; section 10 |
| `/var/lib/omarchy-black-ops/pending/` | root, the pacman hook | 0755 | Spool, section 5.1 |
| `/etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook` | installer (A's part) | 0644 | Section 5.1 |
| `/usr/local/lib/omarchy-black-ops/watch-spool` | installer (A's part) | 0755 root | Section 5.1 |
| `/usr/local/lib/omarchy-black-ops/listen` | installer (B's part) | 0755 root | Section 6.2 |
| `/usr/local/lib/omarchy-black-ops/signatures.toml` | installer (B's part) | 0644 root | A root-owned copy of `data/signatures.toml` for the listener |
| `/etc/systemd/system/omarchy-black-ops-listen.service` | installer (B's part) | 0644 | Section 6.2 |
| `/etc/omarchy-black-ops/listen.conf` | installer (B's part) | 0644 | `RetentionHours=72` and `Account=<name>` |
| `/run/black-ops-listen/` | root, the listener | 0750 root:<account's group> | Section 6.3 |

## 4. The status JSON

`black-ops status` prints one JSON object. What 0.2 printed is unchanged.
0.3.0 adds the fields below, and phase 2 fills in `watch`, `listen` and
`flagged`. The panel renders these and decides nothing itself.

### 4.1 Top level

| Field | Type | Meaning |
|---|---|---|
| `overall` | `"ok"`, `"warn"`, `"leak"`, `"off"` | `leak` wins over `warn` |
| `colour` | `"green"`, `"amber"`, `"red"`, `"grey"` | The colour of `overall` |
| `slipped` | list of row ids | Switched on, was in place, is not now |
| `unapplied` | list of row ids | Switched on, never put in place, such as a row new in this version |
| `attention` | list of row ids | In place, but something needs looking at |
| `leaks` | list of row ids | Rows whose own check set `leak` (only the `listen` row may) |
| `flagged` | list of items | Section 4.3; empty while Black Ops is off |
| `watch` | object | Section 5.5; `{"available": false, "error": ""}` until A is built |
| `listen` | object | Section 6.5; `{"available": false, "error": ""}` until B is built |
| `omarchy` | object | `{"version": "4.0.4-1", "recorded": "4.0.4-1", "changed": false}` |
| `rowsD` | object | `{"skipped": [{"file": "x.json", "why": "..."}]}` |

### 4.2 Each row

Every row, including `watch` and `listen` once built, has:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `watch`, `listen`, a built-in id, or `<stack>/<id>` for a rows.d row |
| `status` | `"ok"`, `"warn"`, `"leak"`, `"off"`, `"na"` | |
| `colour` | `"green"`, `"amber"`, `"red"`, `"grey"` | |
| `label`, `value`, `detail`, `why`, `error` | string | As in 0.2 |
| `intended`, `inPlace`, `optional`, `privileged`, `oneWay` | bool | As in 0.2 |
| `managed` | `"applied"`, `"adopted"` or null | |
| `switchable` | bool | The panel shows a switch only when this is true and `status` is not `na` |
| `registered` | bool | A rows.d row; never switchable |
| `source` | string | `"black-ops"`, or the stack name for a rows.d row |

### 4.3 A flagged item

Both extensions report findings in one shape. The core adds `source`,
`reviewed`, `verdict`, `active` and `colour`, and sorts the list: active
before reviewed, red before amber, newest first.

```json
{
  "id": "3f9c0a1b2c4d5e6f",
  "source": "listen",
  "kind": "contact",
  "severity": "leak",
  "program": "someapp",
  "exe": "/usr/bin/someapp",
  "package": "someapp",
  "path": null,
  "host": "http-intake.logs.us5.datadoghq.com",
  "signature": "datadog-intake",
  "vendor": "Datadog",
  "summary": "Contacted Datadog's telemetry intake.",
  "firstSeen": 1790000000,
  "lastSeen": 1790000500,
  "count": 4,
  "reviewed": false,
  "verdict": null,
  "active": true,
  "colour": "red"
}
```

| Field | Type | Set by | Rule |
|---|---|---|---|
| `id` | 16 lower-case hex | extension | Section 4.4 |
| `source` | `"watch"`, `"listen"` | core | |
| `kind` | `"static"` (A), `"contact"` (B) | extension | |
| `severity` | `"warn"`, `"leak"` | extension | A always `warn`. B `leak` only for a signature kind of `telemetry`, `analytics` or `crash-report`, else `warn`. The core lowers anything else claiming `leak` to `warn` |
| `program` | string | extension | The program's short name, `comm` for B |
| `exe` | string or null | extension | Absolute path of the executable, when known |
| `package` | string or null | extension | The pacman package owning `exe` or `path`, when known |
| `path` | string or null | A | The file the static scan matched |
| `host` | string or null | B | Required for `contact`; null for `static` |
| `signature` | string | extension | An `id` from the signatures file |
| `vendor` | string | extension | The signature's `vendor` |
| `summary` | string | extension | One plain sentence, under 120 characters, with no host in it |
| `firstSeen`, `lastSeen` | integer, epoch seconds | extension | |
| `count` | integer | extension | B: contacts seen; A: matching strings found |
| `version` | string or null | A | The version of the program the item was found in |
| `ecosystem` | string | A | Where the program came from: a `source` value of section 5.4 |
| `match` | string or null | A | The one matched string that best shows why the item is flagged, such as a switch name or a Sentry key's host |
| `optOut` | string or null | A | A suggested opt-out when one is known, such as the telemetry switch found in the program |
| `evidence` | list | A | Up to eight `{"file": path, "match": string}` pairs |
| `firstScan` | bool | A | Found before the first scan of everything had finished, so part of the machine as it already was |
| `reviewed`, `verdict`, `active`, `colour` | | core | `active` is not reviewed. `colour` is `red` for an active leak, `amber` for another active item, `grey` once reviewed |

Only items from a row that is switched on are listed, and none while Black
Ops is off.

### 4.4 Item ids

The id is the first 16 hex digits of the SHA-256 of these parts joined by a
NUL byte, as UTF-8:

- A: `watch`, `static`, `path`, `signature`
- B: `listen`, `contact`, `exe` or, when that is unknown, `program`, `host`,
  `signature`

So the same program contacting the same host keeps its id, and a review
outlives restarts and new segments. A new host or a new path is a new item.

## 5. Software watch (A)

### 5.1 The pacman hook and spool

The installer writes `/etc/pacman.d/hooks/90-omarchy-black-ops-watch.hook`:

```
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = *

[Action]
Description = Black Ops: noting changed packages for the software watch
When = PostTransaction
Exec = /usr/local/lib/omarchy-black-ops/watch-spool
NeedsTargets
```

`watch-spool` runs as root with `python3 -I` or a plain `sh`. It reads the
package names pacman passes on standard input and writes them, one per line,
to `/var/lib/omarchy-black-ops/pending/<epoch>-<pid>.list`, mode 0644. It
removes spool files older than 30 days. It never fails the transaction: any
error is printed and it exits 0. It writes package names and nothing else.

### 5.2 User units

Switching the `watch` row on writes and enables these in
`~/.config/systemd/user/`, and switching it off disables and removes them.
The `ExecStart` path is the plugin's `bin/black-ops`, resolved when the row is
switched on.

| Unit | What it does |
|---|---|
| `black-ops-watch.path` | `PathChanged=/var/lib/omarchy-black-ops/pending`, starts `black-ops-watch.service` |
| `black-ops-watch.service` | `black-ops watch scan --pending --quiet`, `Type=oneshot`, `Nice=19`, `IOSchedulingClass=idle` |
| `black-ops-watch-daily.timer` | `OnCalendar=daily`, `Persistent=true`, `RandomizedDelaySec=1h`, starts `black-ops-watch-daily.service` |
| `black-ops-watch-daily.service` | `black-ops watch scan --changed --quiet`, same limits |
| `black-ops-watch-weekly.timer` | `OnCalendar=weekly`, `Persistent=true`, `RandomizedDelaySec=2h`, starts `black-ops-watch-weekly.service` |
| `black-ops-watch-weekly.service` | `black-ops watch scan --full --quiet`, same limits |
| `black-ops-watch-user.path` | `PathChanged=` for each user install folder of section 5.3 and each virtual environment's site-packages found when the row is switched on; starts `black-ops-watch-user.service` |
| `black-ops-watch-user.service` | `black-ops watch scan --changed --quiet`, same limits |

The row needs no root. Without the hook it still works on the timers alone,
and its check says so as `attention`.

### 5.3 Scans

- `--pending`: the packages named in spool files not yet in `spool-seen.txt`.
- `--changed`: every pacman package whose version differs from the
  inventory, and every file in the user folders below whose size or mtime
  differs.
- `--full`: everything.

User folders: `~/.local/bin`, `~/.local/share/mise/installs`, `~/.cargo/bin`,
`~/.npm-global` and the npm prefix, `~/Applications`, `~/.local/share/flatpak/exports/bin`,
`/var/lib/flatpak/exports/bin`, and AppImages under `~`. A scan reads regular
files only, never follows a link out of these folders, skips files over
512 MiB, and looks for each signature's `strings` as bytes. It never runs a
file it scans.

### 5.4 The inventory

`inventory/index.json`:

```json
{
  "schema": 1,
  "generatedAt": 1790000000,
  "items": [
    {"path": "/usr/bin/someapp", "source": "pacman", "package": "someapp",
     "version": "1.2-1", "sha256": "…", "size": 123456, "mtime": 1789990000,
     "scannedAt": 1790000000, "signatures": ["datadog-intake"]}
  ]
}
```

`source` is one of `pacman`, `mise`, `npm`, `cargo`, `flatpak`, `appimage`,
`local`, `pip`. Each item also has `unit`, the key of the package, app or
environment it belongs to. `sha256` is filled in only for a file an item
points at, and is null otherwise, so that a scan reads each file once.

### 5.5 What the watch reports

`report(ctx, api)` returns the `watch` object of the status JSON:

```json
{
  "enabled": true,
  "hookInstalled": true,
  "lastScan": 1790000000,
  "lastScanKind": "changed",
  "lastScanError": "",
  "scanning": false,
  "inventoryCount": 4312,
  "pendingCount": 0,
  "flaggedCount": 2,
  "unreviewedCount": 1
}
```

The core adds `"available": true`. `watch.json` in `$STATE/black-ops` is the
watch's own store for its findings and last-scan record; its shape is A's
choice.

The object also has `baselineAt` (epoch seconds or null) and `noteCount`.

The `watch` row's check: `na` never; `out` with the row off; `in` when the
units are enabled; `in` with `attention` when the hook is missing, when the
last scan failed, when no scan has finished for eight days, or when a
flagged item is not reviewed, unless every such item has `firstScan`. It
never sets `leak`. When every active item in `flagged` has `firstScan`, the
core's headline is "On, the first scan found N items to review" instead of
"On, but N flagged items need review"; the colour is still amber.

## 6. Listen mode (B)

### 6.1 What it does

A root service records which program looked up which host and connected
where, in RAM only, and matches each host against the signatures. It is off
by default and has its own switch, the optional, privileged `listen` row.

### 6.2 The service

`/etc/systemd/system/omarchy-black-ops-listen.service`, installed disabled:

```
[Unit]
Description=Black Ops listen mode: which program contacts which host, kept in RAM
After=systemd-resolved.service

[Service]
ExecStart=/usr/bin/python3 -I /usr/local/lib/omarchy-black-ops/listen
RuntimeDirectory=black-ops-listen
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=no
ProtectSystem=strict
ProtectHome=yes
PrivateNetwork=no
NoNewPrivileges=yes
```

It reads two sources and nothing else:

- DNS: the varlink interface `io.systemd.Resolve.Monitor` on
  `/run/systemd/resolve/io.systemd.Resolve.Monitor`, method
  `io.systemd.Resolve.Monitor.SubscribeQueryResults`, for each question and
  its answer addresses.
- Connections: `bpftrace` with a probe on `connect` (for example
  `tracepoint:syscalls:sys_enter_connect`), for the pid, `comm`, executable,
  cgroup and destination address and port.

It joins the two by address within the answer's TTL, so a connection is
tied to the host name it was looked up as. A connection with no lookup is
kept with a null host.

### 6.3 The RAM store

Under `/run/black-ops-listen/`, which is tmpfs:

| Path | Mode | What it holds |
|---|---|---|
| `segments/YYYYmmddHH.jsonl` | 0600 root | One line per event, section 6.4 |
| `view/contacts.json` | 0640 root:<account's group> | The aggregate the user side reads, section 6.4 |
| `view/` | 0750 root:<account's group> | |

Segments are hourly. On each hour the listener overwrites with zeros and
then unlinks every segment older than `RetentionHours` (default 72, from
`listen.conf`, 1 to 720), and rebuilds `view/contacts.json` from what is
left. Nothing is written to disk.

### 6.4 Formats

A segment line:

```json
{"t": 1790000000, "src": "resolve", "pid": 1234, "comm": "someapp",
 "exe": "/usr/bin/someapp", "unit": "app-someapp.scope", "uid": 1000,
 "host": "example.com", "addr": "93.184.216.34", "port": 443}
```

`src` is `resolve` or `connect`; fields that are not known are null.

`view/contacts.json`:

```json
{
  "schema": 1,
  "generatedAt": 1790000000,
  "since": 1789740000,
  "retentionHours": 72,
  "contacts": [
    {"program": "someapp", "exe": "/usr/bin/someapp", "unit": "app-someapp.scope",
     "host": "http-intake.logs.us5.datadoghq.com", "signature": "datadog-intake",
     "kind": "telemetry", "firstSeen": 1790000000, "lastSeen": 1790000500, "count": 4}
  ]
}
```

`signature` and `kind` come from the root copy of the signatures file, or
are null when no signature matches.

### 6.5 What listen reports

`report(ctx, api)` reads `view/contacts.json` and returns the `listen`
object of the status JSON:

```json
{
  "enabled": true,
  "serviceActive": true,
  "since": 1789740000,
  "retentionHours": 72,
  "segments": 72,
  "contactCount": 812,
  "hostCount": 140,
  "unknownCount": 131,
  "leakCount": 1
}
```

`unknownCount` is the number of distinct hosts in the window that match no
signature. It is information only and changes no colour. `flagged()` returns
one item per contact whose host matches a signature (section 4.3).

The `listen` row's check: `na` when `bpftrace` or the monitor socket is
missing; `in` when the service is active; `in` with `leak=True` when at
least one item it flags is an unreviewed leak (it reads reviews with
`api.load_reviews(ctx)`); `in` with `attention` when the service is enabled
but not running.

### 6.6 Helper verbs

B adds exactly these to `VERBS` in `system/apply` and in the installer:

| Verb | What it does |
|---|---|
| `listen-on` | `systemctl enable --now omarchy-black-ops-listen.service` |
| `listen-off` | `systemctl disable --now` the service, then what `listen-purge` does |
| `listen-purge` | Overwrite with zeros and unlink every file under `/run/black-ops-listen`, then rebuild an empty view |

No verb takes an argument. The retention is changed only through the
installer: `sudo bin/black-ops-install --listen-retention HOURS`.

## 7. summary.json

Written by the core on every run that takes the lock: the watchdog's
`status --notify`, every switch, and `api.current_report(ctx)`. D reads it
and nothing else. It is already produced by 0.3.0, with `watch` and
`listen` counting zero until A and B are built.

```json
{
  "schema": 1,
  "generatedAt": 1790000000,
  "version": "0.3.0",
  "master": true,
  "overall": "ok",
  "colour": "green",
  "helperState": "current",
  "omarchyChanged": false,
  "protections": {"holding": 12, "slipped": 0, "unapplied": 0, "attention": 0,
                  "off": 5, "notApplicable": 1},
  "registered": {"holding": 3, "notHolding": 0},
  "watch": {"enabled": false, "flagged": 0, "unreviewed": 0, "lastScan": null},
  "listen": {"enabled": false, "leaks": 0, "unknownHosts": 0, "retentionHours": null}
}
```

A summary older than an hour means the watchdog is not running; D should
treat it as unknown rather than as green.

## 8. Signatures

`data/signatures.toml` in the repository. A and B read it; the installer
copies it for the root listener.

```toml
schema = 1

[[signature]]
id = "datadog-intake"          # lower-case, [a-z0-9-], unique
vendor = "Datadog"
kind = "telemetry"             # telemetry | analytics | crash-report | feature-flags | lookup | update-check
hosts = ["http-intake.logs.*.datadoghq.com"]
strings = ["http-intake.logs."] # bytes a static scan looks for; ASCII, at least 8 characters
about = "One plain sentence."
```

A host matches a pattern when `fnmatch.fnmatchcase(host, pattern)` is true
after both are lower-cased and a trailing dot is dropped, so `*` also
matches dots. Only `telemetry`, `analytics` and `crash-report` can make a
contact red. A test in `tests/test_repo.py` checks the file against this
section.

## 9. The review store

`$STATE/black-ops/reviewed.toml`, written only by `black-ops review`, read by
the core:

```toml
schema = 1

[items."3f9c0a1b2c4d5e6f"]
verdict = "allowed"            # allowed | false-positive
at = 1790000600                # epoch seconds
program = "someapp"            # kept so the list reads well after the item has gone
signature = "datadog-intake"
note = "optional, up to 200 characters"
```

A review with another verdict, or a file that is not valid TOML, is ignored.
The writer writes the whole file each time with strings as TOML basic
strings, through `api.atomic_write(path, text, mode=0o600)`.

## 10. rows.d

Already built in 0.3.0. A stack registers rows by writing
`~/.config/omarchy-black-ops/rows.d/<stack>.json`. Rows there report and
never switch. A file is skipped whole, and named in `rowsD.skipped`, when it
or its folder is writable by others or is a link, when it is not valid JSON,
or when anything below does not hold.

```json
{
  "schema": 1,
  "stack": "nightloom",
  "rows": [
    {
      "id": "ollama-block",
      "label": "ollama.com block",
      "about": "Sinks ollama.com in /etc/hosts.",
      "why": "ollama.com is reachable again.",
      "valueIn": "blocked",
      "valueOut": "not blocked",
      "applies": {"file": "~/AI/ollama", "exists": true},
      "check": {"hosts": ["ollama.com"]}
    }
  ]
}
```

`stack` matches the file name and `[a-z0-9-]`, up to 32 characters, and may
not be a Black Ops row id. Each row has an `id` of the same form, a `label`
of up to 60 characters, a `check`, and optionally `applies`, `about`, `why`,
`valueIn` and `valueOut`. A check is exactly one of:

| Check | Holds when |
|---|---|
| `{"hosts": ["a.example"]}` | every name is sunk to `0.0.0.0` and `::` in `/etc/hosts` |
| `{"file": "~/x", "exists": true}` | the path exists, or with `false` does not |
| `{"file": "/etc/x", "contains": "Line=1"}` | some line equals this, spaces trimmed |
| `{"json": "~/x.json", "key": "a.b", "equals": false}` | the dotted key has exactly this JSON value |
| `{"toml": "~/x.toml", "key": "a.b", "equals": 1}` | the same, for TOML |
| `{"env": "NAME", "equals": ""}` | the user session's environment has this value |
| `{"unit": "x.service", "user": true, "state": "masked"}` | `masked`, `enabled`, `disabled`, `active` or `inactive` |
| `{"all": [check, ...]}` | every check holds |

Paths start with `/` or `~/` and contain no `..`. With `applies` false the
row is not applicable. A registered row is `ok` or `warn` while Black Ops is
on and grey while it is off. It is never red.

## 11. The extension modules

bin/black-ops loads `lib/black_ops_watch.py` and `lib/black_ops_listen.py`
by path at start. A module that is missing or fails to import leaves Black
Ops working, and the error goes in `watch.error` or `listen.error`. Each
module may define these functions and nothing else is called:

| Function | Returns | Called |
|---|---|---|
| `make_row(api)` | a subclass instance of `api.Row` with `id` `"watch"` or `"listen"`, `optional = True`; listen also `privileged = True` | once, at load |
| `report(ctx, api)` | the object of section 5.5 or 6.5 | on every status |
| `flagged(ctx, api)` | a list of items, section 4.3 | on every status, only while its row is on |
| `cli(ctx, api, argv)` | an exit status | for the commands in section 12 |

`api` is bin/black-ops itself. Use `api.Row`, `api.result` (which takes
`leak=True` for listen), `api.ActionError`, `api.atomic_write`,
`api.read_text`, `api.load_json`, `api.load_reviews`, `api.current_report`
and `api.Context`. `ctx` has every path in section 3: `ctx.home`,
`ctx.config_home`, `ctx.data_home`, `ctx.watch_dir`, `ctx.state_dir`,
`ctx.user_units`, `ctx.etc`, `ctx.run_dir`, `ctx.environ`, and `ctx.run(cmd,
timeout=...)` for running a command, `ctx.helper(verb)` for the root helper.

Paths outside the home folder come from `ctx`, so the tests can move them:
the listener's view is `ctx.run_dir / "black-ops-listen" / "view"`, and the
spool is `Path(ctx.environ.get("BLACK_OPS_VAR", "/var")) / "lib/omarchy-black-ops/pending"`.
The signatures file is `api.LIB_DIR.parent / "data/signatures.toml"`.

An exception from any of these functions is caught; the report then shows
the extension as unavailable with the message, and the rest of Black Ops
carries on.

## 12. Commands

| Command | Owner | Prints |
|---|---|---|
| `black-ops row watch on` / `off` | core | status JSON |
| `black-ops row listen on` / `off` | core | status JSON |
| `black-ops watch status [--json]` | A | the `watch` object, or text |
| `black-ops watch scan --pending/--changed/--full [--quiet]` | A | a line of text, or nothing with `--quiet` |
| `black-ops watch list [--all] [--json]` | A | flagged items; `--all` includes reviewed |
| `black-ops review <id> allow/false-positive/clear [--note TEXT] [--status]` | A | a line of text, or with `--status` the status JSON |
| `black-ops review --all allow/false-positive [--source watch/listen/any] [--note TEXT] [--status]` | A | reviews every item not reviewed yet, from the watch unless `--source` says otherwise |
| `black-ops watch baseline [--yes]` | A | marks every watch item not reviewed yet as allowed; without `--yes` it only says how many |
| `black-ops listen status [--json]` | B | the `listen` object, or text |
| `black-ops listen report [--hours N] [--json]` | B | contacts per program, for the terminal only |
| `black-ops listen purge [--status]` | B | runs `listen-purge`; with `--status` the status JSON |

Exit status: 0 done, 1 the action failed, 2 a usage error. With `--status`
the command prints `json.dumps(api.current_report(ctx))`, so the panel can
run it through the same process it uses for switching and read back the
new state at once.

## 13. The panel (C)

- Rows: `watch` and `listen` arrive in `rows` like any other and use the
  existing row and switch. Draw a dot for `status` `leak` in `#f85149`.
- A "Flagged" section lists `flagged`, active items first. Each shows the
  dot in the item's `colour`, `program`, `summary`, the host for a listen
  item, when it was last seen and how many times, and two actions: Allow
  (`black-ops review <id> allow --status`) and False positive
  (`black-ops review <id> false-positive --status`). A reviewed item is
  grey and offers Clear (`black-ops review <id> clear --status`).
- A listen row that is on offers Purge now (`black-ops listen purge
  --status`).
- `rowsD.skipped` entries are shown once under the rows as plain text.
- The bar: green, amber, red and grey follow `overall` exactly as
  `BarWidget.qml` does in 0.3.0. Nothing else may make the lock red.

## 14. Security Scan (D)

Read `summary.json` only. Do not run `bin/black-ops`, and do not read any
other Black Ops file. Show counts, never names. Suggested mapping, subject
to the risk register: `overall` `leak` is red, `warn` is amber, `ok` is
green, `off` is grey; a summary older than an hour, or missing, is unknown.

## 15. Tests each piece adds

- A: the hook file and spool writer (in a sandbox `BLACK_OPS_VAR`), unit
  files written and removed byte for byte, a static scan finding a planted
  signature string, ids by section 4.4, the review store round trip, and
  that a static finding is never red.
- B: `listen-on`, `listen-off` and `listen-purge` through the stub sudo,
  that `VERBS` still agree, a canned `view/contacts.json` producing one red
  item, a reviewed one going grey, and that summary.json holds no host.
- C: a test that reads a status JSON fixture with every field in this file
  and checks the panel's property names against it, if the panel is given
  one; otherwise a checklist in the pull request.
- D: its own repository's tests, against a fixture summary.json.

## 16. Changes in version 2

Made while building the software watch, and reported to the coordinator.

1. The core sets an item's `source` itself; an extension no longer has to
   supply it (`FLAG_FIELDS` in `bin/black-ops`).
2. Watch items carry `version`, `ecosystem`, `match`, `optOut` and
   `evidence` (section 4.3).
3. A static item's `signature` is an id from the signatures file or one of
   the watch's own, which start with `watch-` and are listed in
   `lib/black_ops_watch.py`. They stand for signals with no host, such as a
   telemetry switch or a telemetry library, so listen mode never sees them.
4. The inventory's `source` may be `pip`, and its items have `unit`; `sha256`
   may be null (section 5.4).
5. A sixth and seventh user unit watch the user's install folders (section
   5.2).
6. The watch's row asks for attention while a flagged item is not reviewed
   (section 5.5).
7. `review --all` and `watch baseline` (section 12).
8. A scan writes `reviewed.toml` in two cases besides the review command,
   through the same writer: an item whose file moved, such as an AppImage
   renamed for a new version, takes over the review of the item it replaces
   when it found nothing new; and a reviewed item whose program's later
   version adds a string the review did not see loses its review, so it is
   flagged again.
9. Watch items carry `firstScan` (section 4.3). The watch row does not ask
   for attention over first scan items alone, and the headline names them
   as the first scan's findings (section 5.5).
10. A match of a host signature in a small text file that exists to
    block the host is a note with the signature `watch-block-list`, not
    an item.

## 17. Notes from part B (listen mode), for the coordinator

Part B keeps every field, path and verb above. It adds the following, all
of them additions a reader may ignore, except where a line says otherwise.
The contract version is left at 1 for the coordinator to decide.

- `view/contacts.json` has four more top-level fields: `segments` (the
  number of hourly segments held, since the user cannot list the root-only
  segments folder), `probe` (`"kprobe"` or `"tracepoint"`), `probeRunning`
  and `dnsConnected`. A contact with a null `host` also has `addr`, the
  address it connected to.
- The `listen` object of the status JSON has two more fields,
  `probeRunning` and `dnsConnected`. `contactCount` is the number of
  connections seen, the sum of the contacts' counts.
- Each listen item sets `source` to `"listen"` itself, and has one more
  field, `match`: `{"signature", "vendor", "kind", "pattern"}`, where
  `pattern` is the host pattern that matched, or null when only the root
  copy of the signatures knew it.
- The `listen` row raises its own status. `leak` (red) for an unreviewed
  contact whose signature kind is telemetry, analytics or crash-report;
  `in` with `attention` (amber) for an unreviewed contact with any other
  signature kind, and for a running service that has lost bpftrace or the
  resolved monitor. Hosts that match no signature never change a colour.
- An optional store that survives a reboot, off by default:
  `KeepAcrossReboot=yes` in `listen.conf`, set with
  `sudo bin/black-ops-install --listen-keep yes|no`. Segments then go to
  `/var/log/black-ops-listen/segments` (0700 root), in a folder made with
  `chattr +C` while empty. Section 6.3's "Nothing is written to disk" holds
  only while this is off. Switching it off shreds and removes the folder.
- Retention on the hour uses `shred -fuz`, falling back to one pass of
  zeros when shred is missing. `listen-purge` also wipes the disk store,
  and signals a running listener with SIGUSR1 so it forgets what it holds
  in memory; with the listener stopped it writes the empty view itself.
- The join keeps an answer for its TTL, but at least 120 seconds and at
  most 6 hours. A resolve line is written once per host and address per
  hour. Segment names are UTC hours.
- The unit adds hardening beyond section 6.2 (see
  `system/omarchy-black-ops-listen.service`), notably
  `RestrictAddressFamilies=AF_UNIX`, `IPAddressDeny=any`, a capability
  bounding set, `Restart=on-failure`, `ReadWritePaths=-/var/log/black-ops-listen`
  and `ConditionPathExists` on the listener.
- Edits outside B's files, each the smallest that works: the installer's
  option parsing gains `--listen-retention` and `--listen-keep` (outside the
  markers, because section 6.6 names the option); `tests/fake_helper.py`
  points the listen paths into the sandbox; three placeholder tests that
  expected listen mode to be missing now expect it
  (`tests/test_black_ops.py`, `tests/test_rows.py`).
- Not done, because it sits outside the markers: `--uninstall` does not yet
  stop the service or remove the unit, `listen.conf` or the disk store. The
  unit's `ConditionPathExists` keeps a left-behind unit from starting once
  the listener is gone.
