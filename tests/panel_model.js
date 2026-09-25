// Runs the panel's Model.js under node against one status JSON fixture and
// prints what the panel would draw from it, as JSON, for
// tests/test_panel_model.py. Model.js is plain JavaScript with no Qt in it,
// so it runs here as it does in the shell.
//
//   node tests/panel_model.js tests/panel-fixtures/listen-red.json
"use strict"
const fs = require("fs")
const path = require("path")
const vm = require("vm")

const model = {}
vm.createContext(model)
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "Model.js"), "utf8"), model)

const rep = JSON.parse(fs.readFileSync(process.argv[2], "utf8"))
const fmt = (t) => "@" + t
const rows = {}
for (const r of rep.rows || []) rows[r.id] = model.rowStatus(r, rep)

const watch = model.itemsFor(rep, "watch")
const listen = model.itemsFor(rep, "listen")
process.stdout.write(JSON.stringify({
  rowStatus: rows,
  tooltip: model.tooltip(rep),
  watchSummary: model.watchSummary(rep.watch, fmt),
  listenSummary: model.listenSummary(rep.listen, fmt),
  extensionErrors: model.extensionErrors(rep),
  listenOffNote: rows.listen !== undefined
    ? model.listenOffNote((rep.rows || []).find((r) => r.id === "listen")) : "",
  watchEvidence: watch.map((i) => model.watchEvidence(i)),
  reviewAll: model.reviewAllCommands(watch),
  groups: model.listenGroups(listen).map((g) => ({
    program: g.program, colour: g.colour, hosts: g.items.map((i) => i.host),
    count: g.count, seen: model.seenText(g, fmt),
  })),
}))
