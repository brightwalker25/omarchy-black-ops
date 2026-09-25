import QtQuick
import Quickshell

// Loads the plugin's Panel.qml with BLACK_OPS_PANEL_FIXTURE set, so the
// panel reads a fixture through its own collector, then prints every line of
// text the panel shows and the commands its buttons would run. Driven by
// tests/panel-fixtures.sh; every line it prints starts with PROBE.
ShellRoot {
  id: shell

  Loader {
    id: loader
    source: Qt.resolvedUrl("plugin/Panel.qml")
  }

  function texts(item, out) {
    if (!item || item.visible === false) return out
    if (item.text !== undefined && typeof item.text === "string" && item.text !== ""
        && item.font !== undefined)
      out.push(item.text.replace(/\n/g, " / "))
    var kids = item.children || []
    for (var i = 0; i < kids.length; i++) texts(kids[i], out)
    return out
  }

  // The first dump prints every line; later ones print only the lines that
  // were not there before, which is what the step changed.
  property var shown: ({})

  function dump(label) {
    var lines = texts(loader.item, [])
    var seen = {}
    for (var i = 0; i < lines.length; i++) {
      seen[lines[i]] = true
      if (!(lines[i] in shell.shown)) console.log("PROBE " + label + " | " + lines[i])
    }
    if (label === "text") shell.shown = seen
  }

  Timer {
    id: step
    interval: 1200
    running: true
    property int n: 0
    onTriggered: {
      var p = loader.item
      if (!p) { console.log("PROBE FAIL panel did not load"); Qt.quit(); return }
      if (n === 0) {
        console.log("PROBE overall " + p.overall)
        console.log("PROBE tooltip " + p.tooltip.replace(/\n/g, " / "))
        for (var i = 0; i < p.protectionRows.length; i++)
          console.log("PROBE dot " + p.protectionRows[i].id + " " + p.rowStatus(p.protectionRows[i]))
        // Unfold both rows, whatever their default, so their content is drawn.
        var map = {}
        map.watch = true
        map.listen = true
        p.expandedMap = map
        n = 1
        restart()
      } else if (n === 1) {
        dump("text")
        // The two questions the panel asks before acting, where the panel
        // offers them: "Mark all reviewed" with more than one unreviewed
        // watch item, and "Purge log" with listen mode on.
        var active = 0
        for (var j = 0; j < p.watchItems.length; j++) if (p.watchItems[j].active) active++
        if (active > 1) p.confirming = "review-all"
        n = 2
        restart()
      } else if (n === 2) {
        if (p.confirming === "review-all") {
          dump("confirm-review-all")
          p.reviewAll()
        }
        var listen = p.rowById("listen")
        if (listen && listen.intended) p.confirming = "purge"
        n = 3
        restart()
      } else if (n === 3) {
        if (p.confirming === "purge") {
          dump("confirm-purge")
          p.purgeListen()
        }
        if (p.watchItems.length > 0) p.review(p.watchItems[0].id, "allow")
        console.log("PROBE done")
        Qt.quit()
      }
    }
  }
}
