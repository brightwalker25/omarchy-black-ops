// The panel's reading of the status JSON, kept apart from the drawing so it
// can be tested without a running shell (tests/test_panel_model.py runs it
// under node against the fixtures in tests/panel-fixtures).
//
// Nothing here decides whether something is a problem. bin/black-ops does
// that, and docs/contract.md fixes the shape it prints. These functions only
// sort, group and word what it said. The one exception is rowStatus(), which
// lets a watch or listen row show the colour of the items it has flagged, so
// that the row agrees with the lock in the bar.

function list(value) {
  return Array.isArray(value) ? value : []
}

function plural(n, one, many) {
  return n + " " + (n === 1 ? one : (many || one + "s"))
}

// The status a colour name stands for, so a flagged item's dot can be drawn
// with the same component and the same fixed colours as a row's.
function statusOfColour(colour) {
  if (colour === "red") return "leak"
  if (colour === "amber") return "warn"
  if (colour === "green") return "ok"
  return "off"
}

function colourRank(colour) {
  if (colour === "red") return 2
  if (colour === "amber") return 1
  return 0
}

function itemsFor(rep, source) {
  var out = []
  var items = rep ? list(rep.flagged) : []
  for (var i = 0; i < items.length; i++)
    if (items[i] && items[i].source === source) out.push(items[i])
  return out
}

function activeItems(items) {
  var out = []
  for (var i = 0; i < items.length; i++)
    if (items[i].active === true) out.push(items[i])
  return out
}

function labelOf(rep, id) {
  var rows = rep ? list(rep.rows) : []
  for (var i = 0; i < rows.length; i++)
    if (rows[i].id === id) return String(rows[i].label || id)
  return String(id)
}

// The status a row's dot is drawn in. For every row but watch and listen it
// is the status the script gave. The watch and listen checks only say
// whether the row itself is in place, so an item the row has flagged that
// nobody has reviewed raises it to amber, or to red for a confirmed leak.
// These are the same items that turn the bar amber or red.
function rowStatus(row, rep) {
  if (!row) return "off"
  var status = String(row.status || "off")
  if (row.id !== "watch" && row.id !== "listen") return status
  if (status === "off" || status === "na" || status === "leak" || row.intended !== true)
    return status
  var items = activeItems(itemsFor(rep, row.id))
  for (var i = 0; i < items.length; i++) {
    if (items[i].colour === "red") return "leak"
    if (items[i].colour === "amber") status = "warn"
  }
  return status
}

// Whether the output of `black-ops <argv>` is a status JSON the panel should
// read. Switching always prints one. The extension commands print one only
// with --status; without it they print a line of text meant for a terminal.
function printsStatus(argv) {
  var verb = argv.length > 0 ? argv[0] : ""
  if (verb === "review" || verb === "watch" || verb === "listen")
    return argv.indexOf("--status") >= 0
  return true
}

// The commands behind "Mark all reviewed": one review per unreviewed watch
// item, run one after another. The contract has no command that reviews
// several at once, so only the last asks for the status back.
function reviewAllCommands(items) {
  var active = activeItems(items)
  var out = []
  for (var i = 0; i < active.length; i++) {
    var argv = ["review", String(active[i].id), "allow"]
    if (i === active.length - 1) argv.push("--status")
    out.push(argv)
  }
  return out
}

// Listen items grouped by program: red programs first, then amber, then
// reviewed. Within a program the items keep the order the script gave them,
// which is active first, red first, newest first.
function listenGroups(items) {
  var groups = []
  var byName = {}
  for (var i = 0; i < items.length; i++) {
    var item = items[i]
    var name = String(item.program || item.exe || "unknown program")
    var g = byName[name]
    if (!g) {
      g = { program: name, colour: "grey", items: [], firstSeen: 0, lastSeen: 0, count: 0, active: 0 }
      byName[name] = g
      groups.push(g)
    }
    g.items.push(item)
    if (colourRank(item.colour) > colourRank(g.colour)) g.colour = item.colour
    if (item.active === true) g.active++
    var first = Number(item.firstSeen || 0)
    var last = Number(item.lastSeen || 0)
    if (first > 0 && (g.firstSeen === 0 || first < g.firstSeen)) g.firstSeen = first
    if (last > g.lastSeen) g.lastSeen = last
    g.count += Number(item.count || 0)
  }
  // Put together rank by rank rather than with sort(), so the order within a
  // rank never depends on how stable the engine's sort is.
  var out = []
  for (var rank = 2; rank >= 0; rank--)
    for (var j = 0; j < groups.length; j++)
      if (colourRank(groups[j].colour) === rank) out.push(groups[j])
  return out
}

// "first seen 09:12, last seen 14:05, 4 times". `fmt` turns epoch seconds
// into text; the panel passes one built on Qt's date formatting.
function seenText(item, fmt) {
  var parts = []
  if (item.firstSeen) parts.push("first seen " + fmt(item.firstSeen))
  if (item.lastSeen && item.lastSeen !== item.firstSeen) parts.push("last seen " + fmt(item.lastSeen))
  var n = Number(item.count || 0)
  if (n > 0) parts.push(n === 1 ? "once" : n + " times")
  return parts.join(", ")
}

function signatureText(item) {
  var sig = String(item.signature || "")
  var vendor = String(item.vendor || "")
  if (vendor !== "" && sig !== "") return vendor + " (" + sig + ")"
  return vendor || sig
}

// What the software watch found for one item, one line each. The contract
// gives the package, the file and the signature. The version, the ecosystem,
// the matched string and a suggested opt-out are shown when the item carries
// them as `version`, `ecosystem`, `match` and `optOut`, which contract
// version 1 does not yet define.
function watchEvidence(item) {
  var lines = []
  var pkg = String(item.package || "")
  if (pkg !== "") {
    lines.push("Package " + pkg + (item.version ? " " + item.version : "")
      + (item.ecosystem ? " (" + item.ecosystem + ")" : ""))
  } else if (item.ecosystem) {
    lines.push("Installed through " + item.ecosystem + (item.version ? ", version " + item.version : ""))
  }
  if (item.path) lines.push("File: " + item.path)
  var sig = signatureText(item)
  if (item.match) lines.push("Matched \"" + item.match + "\"" + (sig !== "" ? ", " + sig : ""))
  else if (sig !== "") lines.push("Signature: " + sig)
  var n = Number(item.count || 0)
  if (n > 1) lines.push(n + " matching strings")
  if (item.optOut) lines.push("To opt out: " + item.optOut)
  return lines
}

function watchSummary(watch, fmt) {
  if (!watch || watch.available !== true)
    return watch && watch.error ? "" : "The software watch is not part of this build."
  var parts = []
  if (watch.scanning === true) parts.push("Scanning now.")
  if (watch.lastScan) {
    var s = "Last scan " + fmt(watch.lastScan)
    if (watch.lastScanKind) s += ", " + watch.lastScanKind
    parts.push(s + ".")
  } else if (watch.enabled === true && watch.scanning !== true) {
    parts.push("No scan has finished yet.")
  }
  if (watch.inventoryCount > 0) parts.push(plural(Number(watch.inventoryCount), "file") + " known.")
  if (watch.pendingCount > 0)
    parts.push(plural(Number(watch.pendingCount), "package") + " waiting to be scanned.")
  if (watch.enabled === true && watch.hookInstalled === false)
    parts.push("The pacman hook is not installed, so new packages wait for the daily scan.")
  return parts.join(" ")
}

function listenSummary(listen, fmt) {
  if (!listen || listen.available !== true)
    return listen && listen.error ? "" : "Listen mode is not part of this build."
  var parts = []
  if (listen.retentionHours) {
    var s = "Kept in RAM for " + plural(Number(listen.retentionHours), "hour")
    if (listen.since) s += ", since " + fmt(listen.since)
    parts.push(s + ".")
  }
  if (listen.contactCount > 0 || listen.hostCount > 0)
    parts.push(plural(Number(listen.contactCount || 0), "contact") + " with "
      + plural(Number(listen.hostCount || 0), "host") + ".")
  if (listen.unknownCount > 0)
    parts.push(plural(Number(listen.unknownCount), "host") + " matched no signature.")
  if (listen.enabled === true && listen.serviceActive === false)
    parts.push("The service is switched on but not running.")
  return parts.join(" ")
}

// Shown under the listen row while it is off. It is the only row whose
// switch does nothing until something outside the panel is installed.
function listenOffNote(row) {
  var base = "Listen mode needs the root installer (sudo bin/black-ops-install) and bpftrace."
  if (row && row.status === "na") return base + " One of them is missing, so it cannot be switched on."
  return base + " It is off by default, and keeps what it sees in RAM only."
}

// The bar's tooltip: the headline, then what is red and what is amber by
// name, so the colour of the lock can be explained without opening the
// panel.
function tooltip(rep) {
  if (!rep) return "Black Ops"
  var lines = ["Black Ops: " + String(rep.headline || "")]
  var red = []
  var amber = []
  var i

  var seen = {}
  var leaksWithItems = {}
  var flagged = list(rep.flagged)
  for (i = 0; i < flagged.length; i++) {
    var it = flagged[i]
    if (it.active !== true || it.colour !== "red") continue
    leaksWithItems[it.source] = true
    var who = String(it.program || "a program") + " to " + String(it.vendor || it.signature || "a telemetry host")
    if (!seen[who]) { seen[who] = true; red.push(who) }
  }
  var leaks = list(rep.leaks)
  for (i = 0; i < leaks.length; i++)
    if (!leaksWithItems[leaks[i]]) red.push(labelOf(rep, leaks[i]))

  var groups = [["slipped", " has slipped"], ["unapplied", " is not applied yet"],
                ["attention", " needs attention"], ["pending", " could not be removed"]]
  for (var g = 0; g < groups.length; g++) {
    var ids = list(rep[groups[g][0]])
    for (i = 0; i < ids.length; i++) amber.push(labelOf(rep, ids[i]) + groups[g][1])
  }
  var watchAmber = 0
  var listenAmber = {}
  var listenAmberCount = 0
  for (i = 0; i < flagged.length; i++) {
    if (flagged[i].active !== true || flagged[i].colour !== "amber") continue
    if (flagged[i].source === "watch") watchAmber++
    else if (!listenAmber[flagged[i].program]) { listenAmber[flagged[i].program] = true; listenAmberCount++ }
  }
  if (watchAmber > 0) amber.push(plural(watchAmber, "software watch item") + " to review")
  if (listenAmberCount > 0) amber.push(plural(listenAmberCount, "program") + " seen by listen mode to review")
  if (rep.master === true && rep.helperState === "outdated") amber.push("the root helper needs reinstalling")

  if (red.length > 0) lines.push("Red: " + red.join(", "))
  if (amber.length > 0) lines.push("Amber: " + amber.join("; "))
  return lines.join("\n")
}

// An extension that could not be loaded, or whose report failed, says why in
// its own object. Shown once at the foot of the panel, since its row may be
// missing altogether.
function extensionErrors(rep) {
  var out = []
  var names = [["watch", "Software watch"], ["listen", "Listen mode"]]
  for (var i = 0; i < names.length; i++) {
    var obj = rep ? rep[names[i][0]] : null
    if (obj && obj.available !== true && obj.error) out.push(names[i][1] + ": " + obj.error)
  }
  return out.join("\n")
}
