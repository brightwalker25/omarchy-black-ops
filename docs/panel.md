# The panel and the bar in 0.3.0

This covers what the panel shows for the software watch and listen mode,
and how the scope in the bar is coloured. The panel draws what
`bin/black-ops status` prints and decides nothing itself; docs/contract.md
fixes that output.

## The scope

The scope follows the overall state the script reports, and nothing else.

| Scope | Colour | When |
|---|---|---|
| Filled centre | Green, #3fb950 | On, and everything holding |
| Filled centre | Amber, #d29922 | On, but a protection has slipped, is not applied yet or needs attention, or an item the software watch or listen mode flagged has not been reviewed |
| Filled centre | Red, #f85149 | On, and listen mode saw a program contact a telemetry, analytics or crash report host, and nobody has reviewed it |
| Empty, dimmed | None | Off |

Red wins over amber, and amber wins over green. The tooltip gives the
headline and then names what is red and what is amber, for example:

```
Black Ops: On, but someapp contacted a telemetry host
Red: someapp to Datadog
Amber: Claude Code telemetry host has slipped; 1 software watch item to review
```

## The software watch row

The dot is green while the watch is on and holding, grey while it is off,
and amber when the watch itself needs attention (its pacman hook is
missing, its last scan failed, or no scan has finished for eight days) or
when it has flagged an item nobody has reviewed.

Click the row to unfold it. It shows when the last scan ran and how many
files are known, then each flagged item, unreviewed first:

- the program's name and the one-sentence summary
- the package, and its version and where it came from when the watch
  reports them
- the file that matched, the signature and its vendor, and the matched
  string when the watch reports it
- a suggested way to opt out, when the watch reports one
- Allow and False positive, which run `black-ops review <id> allow` or
  `false-positive`. A reviewed item is grey and offers Clear review, which
  makes it count again.

The first scan flags everything already installed that carries a signature.
With more than one item unreviewed, Mark all reviewed allows every one of
them, after asking in the panel. Each can be cleared again afterwards.

## The listen mode row

| Dot | When |
|---|---|
| Grey | Off, or not available on this machine |
| Green | On, and nothing flagged |
| Amber | On, and a program contacted a host that matches a signature which is not telemetry, such as an update check, and nobody has reviewed it |
| Red | On, and a program contacted a telemetry, analytics or crash report host, and nobody has reviewed it |

While it is off the row says that listen mode needs the root installer
(`sudo bin/black-ops-install`) and bpftrace.

Unfolded, it shows how long listen mode keeps what it sees (72 hours unless
the installer was given another figure) and how much it has seen, then each
program it flagged, red programs first. Under each program is every host it
contacted, with the signature, when it was first and last seen, and how
many times, and the same Allow, False positive and Clear review actions.

Turn listen mode on or off is the same as the row's switch. Purge log
overwrites and removes everything listen mode has kept so far, after asking
in the panel. Reviews are kept.

## Testing the panel

- `pytest tests/test_panel_model.py` runs the panel's `Model.js` under node
  against the fixtures in `tests/panel-fixtures`, one per state above.
- `pytest tests/test_panel_contract.py` checks the fixtures against the
  contract and against what the script really prints.
- `tests/panel-fixtures.sh` loads `Panel.qml` in a separate quickshell on
  Qt's offscreen platform, feeds it each fixture through its own collector,
  and prints every line of text it shows and the commands its buttons would
  run. It draws nothing on screen, does not touch the running shell, and
  runs no command. `tests/panel-fixtures/make.py` writes the fixtures.
