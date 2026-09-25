import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The panel scaffolding here, the open/close and IPC contract, is derived from
// Omarchy's `omarchy.weather` and `omarchy.agents` plugins
// (https://github.com/basecamp/omarchy, MIT, Copyright (c) David Heinemeier
// Hansson). See LICENSE for the full notice.

// The panel behind the bar glyph. One switch at the top turns every
// protection on or off together, and each protection has a row underneath
// with a dot for whether it is holding, what it is doing now, and a switch of
// its own.
//
// It renders whatever `bin/black-ops` reports and decides nothing itself.
// What counts as in place, what has slipped, and what switching off would
// undo are all worked out in that script, which runs the same from a terminal.
//
// The software watch and listen mode are rows like the others. Each can be
// unfolded to show what it has flagged, with a way to review every item, so
// that nothing that turns the scope amber or red is out of reach here.
//
// The panel also owns the watchdog. The script is re-run on a timer whether
// or not the panel is open, because a slip that is only noticed when someone
// happens to look is the thing the watchdog exists to prevent. Each run reads
// local files and touches no network.
Panel {
  id: root
  moduleName: "brightwalker25.black-ops"
  ipcTarget: "brightwalker25.black-ops"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Fixed rather than drawn from the theme, as in the other brightwalker25
  // panels: a theme is free to make its urgent colour a soft pink, and a
  // warning drawn in a decorative colour does not read as a warning.
  readonly property color okColor: "#3fb950"
  readonly property color warnColor: "#d29922"
  // Red is kept for one thing: listen mode saw a program contact a telemetry
  // host. It is the red Security Scan uses.
  readonly property color leakColor: "#f85149"

  readonly property int refreshMs: Math.max(1, Number(setting("refreshMinutes", 10))) * 60000
  readonly property bool notifyOnSlip: setting("notifyOnSlip", true) !== false

  readonly property string cli: String(Qt.resolvedUrl("bin/black-ops")).replace(/^file:\/\//, "")

  // For tests only: with BLACK_OPS_PANEL_FIXTURE naming a status JSON file,
  // the panel reads that file through the same collector instead of running
  // the script, and logs the commands it would run instead of running them.
  // tests/panel-fixtures.sh uses it. The running shell never has it set.
  readonly property string fixture: String(Quickshell.env("BLACK_OPS_PANEL_FIXTURE") || "")

  property var rep: null
  property string error: ""
  property bool busy: false

  // Held from the moment the main switch is thrown until the script reports
  // back, so the switch does not visibly snap back during the round trip.
  // -1 means nothing is pending.
  property int pendingMaster: -1

  readonly property bool master: pendingMaster >= 0 ? pendingMaster === 1 : (rep ? rep.master === true : false)
  readonly property string overall: rep ? String(rep.overall || "") : ""
  // The headline, then what is red and what is amber by name.
  readonly property string tooltip: Model.tooltip(rep)

  readonly property var protectionRows: rep && rep.rows ? rep.rows : []

  // Set by the script when the root helper is missing, or when the installed
  // copy is from another version and has to be installed again.
  readonly property string helperNote: rep && rep.helperNote ? String(rep.helperNote) : ""

  readonly property var watchItems: Model.itemsFor(rep, "watch")
  readonly property var listenItems: Model.itemsFor(rep, "listen")
  readonly property string extensionErrors: Model.extensionErrors(rep)
  readonly property var skippedFiles: rep && rep.rowsD && rep.rowsD.skipped ? rep.rowsD.skipped : []

  // Which in-panel question is showing: "review-all", "purge", or none. The
  // viewer has no dialogs, so anything that cannot be undone asks here first.
  property string confirming: ""

  // Commands still to run after the current one, for "Mark all reviewed".
  property var queue: []

  function statusColor(status) {
    if (status === "ok") return root.okColor
    if (status === "warn") return root.warnColor
    if (status === "leak") return root.leakColor
    return root.dim
  }

  // A row's dot. For watch and listen it also carries the colour of what
  // they have flagged; see Model.rowStatus.
  function rowStatus(row) {
    return Model.rowStatus(row, root.rep)
  }

  function rowById(id) {
    for (var i = 0; i < root.protectionRows.length; i++)
      if (root.protectionRows[i].id === id) return root.protectionRows[i]
    return null
  }

  function fmtWhen(epoch) {
    if (!epoch) return ""
    var d = new Date(epoch * 1000)
    if (d.toDateString() === new Date().toDateString()) return Qt.formatTime(d, "HH:mm")
    return Qt.formatDateTime(d, "d MMM HH:mm")
  }

  function privilegedLabels() {
    var out = []
    for (var i = 0; i < root.protectionRows.length; i++)
      if (root.protectionRows[i].privileged) out.push(root.protectionRows[i].label)
    return out.join(", ")
  }

  function pair() {
    root.act(["pair"])
  }

  // ------------------------------------------------------------- the script

  function poll() {
    if (reader.running || writer.running || root.queue.length > 0) return
    reader.running = true
  }

  function ingest(text) {
    var parsed = null
    try {
      parsed = JSON.parse(String(text))
    } catch (e) {
      root.error = "Could not read the output of black-ops"
      return
    }
    if (!parsed || typeof parsed !== "object") return
    root.error = parsed.error ? String(parsed.error) : ""
    root.rep = parsed
    root.pendingMaster = -1
  }

  function act(argv) {
    if (writer.running) return
    root.confirming = ""
    if (root.fixture !== "") {
      console.log("black-ops panel fixture: would run black-ops " + argv.join(" "))
      if (root.queue.length > 0) root.runNext()
      return
    }
    root.busy = true
    writer.argv = argv
    writer.running = true
  }

  // Runs several commands one after another, stopping at the first that fails.
  function actAll(list) {
    if (writer.running || list.length === 0) return
    root.queue = list.slice(1)
    root.act(list[0])
  }

  function runNext() {
    var next = root.queue[0]
    root.queue = root.queue.slice(1)
    root.act(next)
  }

  function review(id, verdict) {
    root.act(["review", id, verdict, "--status"])
  }

  function reviewAll() {
    root.actAll(Model.reviewAllCommands(root.watchItems))
  }

  function purgeListen() {
    root.act(["listen", "purge", "--status"])
  }

  function isExpanded(id, map) {
    if (id in map) return map[id] === true
    // A row nobody has touched is unfolded when it has something to review.
    return Model.activeItems(Model.itemsFor(root.rep, id)).length > 0
  }

  function toggleExpanded(id) {
    var next = Object.assign({}, root.expandedMap)
    next[id] = !root.isExpanded(id, root.expandedMap)
    root.expandedMap = next
  }

  // Keyed by row id so the choice survives each re-read, which replaces the
  // whole report and rebuilds every delegate.
  property var expandedMap: ({})

  function setMaster(on) {
    root.pendingMaster = on ? 1 : 0
    root.act([on ? "on" : "off"])
  }

  function setRow(id, on) {
    root.act(["row", id, on ? "on" : "off"])
  }

  Process {
    id: reader
    command: root.fixture !== "" ? ["cat", root.fixture]
      : (root.notifyOnSlip ? [root.cli, "status", "--notify"] : [root.cli, "status"])
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.ingest(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var t = String(text || "").trim()
        if (t !== "") root.error = t
      }
    }
  }

  Process {
    id: writer
    property var argv: []
    // Every action prints a fresh status when it is done, so a change and the
    // reading that follows it are one process, and the panel never draws the
    // state from before its own change.
    command: [root.cli].concat(writer.argv)
    running: false
    stdout: StdioCollector {
      waitForEnd: true
      // A review in the middle of "Mark all reviewed" prints a line of text
      // rather than the status; only the last one asks for the status back.
      onStreamFinished: if (Model.printsStatus(writer.argv)) root.ingest(text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var t = String(text || "").trim()
        if (t !== "") root.error = t
      }
    }
    onExited: function(exitCode) {
      root.busy = false
      root.pendingMaster = -1
      if (exitCode !== 0) {
        root.queue = []
        if (root.error === "") root.error = "black-ops exited " + exitCode
      }
      if (root.queue.length > 0) Qt.callLater(root.runNext)
      else if (!Model.printsStatus(writer.argv)) Qt.callLater(root.poll)
    }
  }

  // The watchdog. It runs with the panel closed, at the interval set in the
  // widget's settings, ten minutes by default.
  Timer {
    running: true
    interval: root.refreshMs
    repeat: true
    onTriggered: root.poll()
  }

  // While a pair window is open, the count on its button is kept fresh.
  Timer {
    running: !!root.rep && root.rep.pairSecondsLeft > 0
    interval: 5000
    repeat: true
    onTriggered: root.poll()
  }

  Component.onCompleted: root.poll()

  function fmtChecked() {
    if (!root.rep || !root.rep.generatedAt) return ""
    var d = new Date(root.rep.generatedAt * 1000)
    return "checked " + Qt.formatTime(d, "HH:mm")
  }

  // ------------------------------------------------------- open/close contract

  property bool openedFromHotkey: false

  function open() {
    openedFromHotkey = false
    root.controller.show()
    root.poll()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
    root.poll()
  }

  function close() {
    root.confirming = ""
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      root.bar.switchPanelFrom(root.barIdentity, direction)
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.openFromHotkey() }
    function close(): void { root.close() }
    function show(): void { root.openFromHotkey() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.poll() }
    // So a keybinding can throw the main switch without opening anything:
    // `omarchy-shell brightwalker25.black-ops switchOn`.
    function switchOn(): void { root.setMaster(true) }
    function switchOff(): void { root.setMaster(false) }
  }

  // ------------------------------------------------------------- components

  component StatusDot: Rectangle {
    property string status: "off"
    implicitWidth: Style.space(9)
    implicitHeight: Style.space(9)
    radius: width / 2
    color: root.statusColor(status)
    Behavior on color { ColorAnimation { duration: 180 } }
  }

  // One protection: dot, name, what it is doing now, and its own switch. The
  // explanation sits underneath so the line above stays easy to scan.
  component ProtectionRow: Column {
    id: prow
    property var item: null
    spacing: Style.spacing.xxs

    // Rows other stacks register in rows.d only report, so they have no switch.
    readonly property bool hasSwitch: !!item && item.status !== "na" && !item.registered
    // The software watch and listen mode unfold to show what they flagged.
    readonly property bool expandable: !!item && (item.id === "watch" || item.id === "listen")
    readonly property bool expanded: expandable && root.isExpanded(item.id, root.expandedMap)
    readonly property real textIndent: Style.space(9) + Style.spacing.sm

    Item {
      width: prow.width
      implicitHeight: Math.max(dot.height, rowLabel.implicitHeight, rowSwitch.visible ? rowSwitch.height : 0)

      StatusDot {
        id: dot
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        status: root.rowStatus(prow.item)
      }

      Text {
        id: rowLabel
        textFormat: Text.PlainText
        anchors.left: dot.right
        anchors.leftMargin: Style.spacing.sm
        anchors.verticalCenter: parent.verticalCenter
        text: prow.item ? prow.item.label : ""
        color: prow.item && prow.item.intended ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        id: rowChevron
        visible: prow.expandable
        anchors.left: rowLabel.right
        anchors.leftMargin: Style.spacing.xs
        anchors.verticalCenter: parent.verticalCenter
        // nf-md-chevron_down and nf-md-chevron_right, as in Security Scan.
        text: prow.expanded ? "󰅀" : "󰅂"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }

      Text {
        id: rowValue
        textFormat: Text.PlainText
        anchors.left: rowChevron.visible ? rowChevron.right : rowLabel.right
        anchors.leftMargin: Style.spacing.controlGap
        anchors.right: rowSwitch.visible ? rowSwitch.left : parent.right
        anchors.rightMargin: rowSwitch.visible ? Style.spacing.sm : 0
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideRight
        text: prow.item ? prow.item.value : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }

      ToggleSwitch {
        id: rowSwitch
        visible: prow.hasSwitch
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        checked: !!prow.item && prow.item.intended
        busy: root.busy
        interactive: !!prow.item && prow.item.switchable && !root.busy
        opacity: interactive ? 1.0 : 0.4
        foreground: root.foreground
        onToggled: root.setRow(prow.item.id, !prow.item.intended)
      }

      // Everything left of the switch folds and unfolds the row.
      MouseArea {
        visible: prow.expandable
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: rowSwitch.visible ? rowSwitch.left : parent.right
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggleExpanded(prow.item.id)
      }
    }

    Text {
      textFormat: Text.PlainText
      width: prow.width - Style.space(9) - Style.spacing.sm
      x: Style.space(9) + Style.spacing.sm
      visible: text !== ""
      text: prow.item && prow.item.detail ? prow.item.detail : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    Text {
      textFormat: Text.PlainText
      width: prow.width - Style.space(9) - Style.spacing.sm
      x: Style.space(9) + Style.spacing.sm
      visible: text !== ""
      // The helper note is shown once, at the foot of the panel, rather than
      // under every row that needs root.
      text: prow.item && prow.item.error && prow.item.error !== root.helperNote ? prow.item.error : ""
      color: root.warnColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    Text {
      textFormat: Text.PlainText
      width: prow.width - prow.textIndent
      x: prow.textIndent
      visible: !!prow.item && prow.item.id === "listen" && (prow.item.status === "na" || !prow.item.intended)
      text: visible ? Model.listenOffNote(prow.item) : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    Loader {
      width: prow.width - prow.textIndent
      x: prow.textIndent
      active: prow.expanded
      visible: active
      sourceComponent: prow.item && prow.item.id === "watch" ? watchDetail : listenDetail
    }
  }

  Component { id: watchDetail; WatchDetail {} }
  Component { id: listenDetail; ListenDetail {} }

  // A small bordered button for the actions inside an unfolded row.
  component SmallButton: Button {
    bordered: true
    enabled: !root.busy
    opacity: enabled ? 1.0 : 0.45
    fontSize: Style.font.caption
    foreground: root.foreground
    accent: root.foreground
    background: root.bar ? root.bar.background : Color.background
    fontFamily: root.fontFamily
  }

  // The review actions for one flagged item. An item nobody has reviewed can
  // be allowed or marked a false positive; a reviewed one can be cleared,
  // which makes it count again.
  component ItemActions: Row {
    id: actions
    property var item: null
    readonly property bool active: !!item && item.active === true
    spacing: Style.spacing.xs

    SmallButton {
      visible: actions.active
      text: "Allow"
      onClicked: root.review(actions.item.id, "allow")
    }
    SmallButton {
      visible: actions.active
      text: "False positive"
      onClicked: root.review(actions.item.id, "false-positive")
    }
    SmallButton {
      visible: !!actions.item && !actions.active
      text: "Clear review"
      onClicked: root.review(actions.item.id, "clear")
    }
  }

  // A question asked in the panel itself, with the action and Cancel.
  component ConfirmLine: Column {
    id: confirm
    property string key: ""
    property string question: ""
    property string actionText: ""
    signal confirmed()
    visible: root.confirming === key
    spacing: Style.spacing.xs

    Text {
      textFormat: Text.PlainText
      width: confirm.width
      text: confirm.question
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }

    Row {
      spacing: Style.spacing.xs
      SmallButton {
        text: confirm.actionText
        foreground: root.warnColor
        accent: root.warnColor
        onClicked: confirm.confirmed()
      }
      SmallButton {
        text: "Cancel"
        enabled: true
        opacity: 1.0
        onClicked: root.confirming = ""
      }
    }
  }

  component DetailText: Text {
    textFormat: Text.PlainText
    visible: text !== ""
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    // Paths and host names can be long with no spaces in them, so they break
    // wherever they must rather than running off the panel.
    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
  }

  // One file the software watch flagged: what it is, why, and the evidence.
  component WatchItem: Item {
    id: witem
    property var item: null
    readonly property bool active: !!item && item.active === true
    readonly property real textIndent: Style.space(9) + Style.spacing.sm
    implicitHeight: witemText.implicitHeight

    StatusDot {
      x: 0
      y: Math.max(0, (witemName.implicitHeight - height) / 2)
      status: witem.item ? Model.statusOfColour(witem.item.colour) : "off"
    }

    Column {
      id: witemText
      x: witem.textIndent
      width: witem.width - witem.textIndent
      spacing: Style.spacing.xxs

      Text {
        id: witemName
        textFormat: Text.PlainText
        width: parent.width
        text: witem.item ? String(witem.item.program || witem.item.package || "") : ""
        color: witem.active ? root.foreground : root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
      }

      DetailText {
        width: parent.width
        text: witem.item && witem.item.summary ? witem.item.summary : ""
        color: witem.active ? root.foreground : root.dim
      }

      Repeater {
        model: witem.item ? Model.watchEvidence(witem.item) : []
        delegate: DetailText {
          required property var modelData
          width: witemText.width
          text: modelData
        }
      }

      DetailText {
        width: parent.width
        text: witem.item && witem.item.firstSeen ? "Found " + root.fmtWhen(witem.item.firstSeen) : ""
      }

      DetailText {
        width: parent.width
        text: witem.item && witem.item.reviewed
          ? "Reviewed: " + (witem.item.verdict === "false-positive" ? "a false positive" : "allowed") : ""
      }

      ItemActions { item: witem.item }
    }
  }

  // One program listen mode saw, with each host it contacted.
  component ListenGroup: Item {
    id: lgroup
    property var group: null
    readonly property real textIndent: Style.space(9) + Style.spacing.sm
    implicitHeight: lgroupText.implicitHeight

    StatusDot {
      x: 0
      y: Math.max(0, (lgroupName.implicitHeight - height) / 2)
      status: lgroup.group ? Model.statusOfColour(lgroup.group.colour) : "off"
    }

    Column {
      id: lgroupText
      x: lgroup.textIndent
      width: lgroup.width - lgroup.textIndent
      spacing: Style.spacing.xs

      Column {
        width: parent.width
        spacing: Style.spacing.xxs

        Text {
          id: lgroupName
          textFormat: Text.PlainText
          width: parent.width
          text: lgroup.group ? lgroup.group.program : ""
          color: lgroup.group && lgroup.group.active > 0 ? root.foreground : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          wrapMode: Text.WrapAtWordBoundaryOrAnywhere
        }

        DetailText {
          width: parent.width
          text: lgroup.group
            ? Model.plural(lgroup.group.items.length, "host") + ", " + Model.seenText(lgroup.group, root.fmtWhen)
            : ""
        }
      }

      Repeater {
        model: lgroup.group ? lgroup.group.items : []
        delegate: Column {
          id: contact
          required property var modelData
          readonly property bool active: modelData.active === true
          width: lgroupText.width
          spacing: Style.spacing.xxs

          Text {
            textFormat: Text.PlainText
            width: contact.width
            // The colour of the host name is the item's own, since one
            // program can have a red host and an amber one.
            text: String(contact.modelData.host || "no host name")
            color: contact.modelData.colour === "red" && contact.active ? root.leakColor
              : (contact.modelData.colour === "amber" && contact.active ? root.warnColor : root.dim)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
          }

          DetailText {
            width: contact.width
            text: Model.signatureText(contact.modelData)
              + (contact.modelData.summary ? ". " + contact.modelData.summary : "")
          }

          DetailText {
            width: contact.width
            text: Model.seenText(contact.modelData, root.fmtWhen)
          }

          DetailText {
            width: contact.width
            text: contact.modelData.reviewed
              ? "Reviewed: " + (contact.modelData.verdict === "false-positive" ? "a false positive" : "allowed") : ""
          }

          ItemActions { item: contact.modelData }
        }
      }
    }
  }

  // The software watch unfolded: when it last scanned, then every item it
  // flagged, unreviewed first.
  component WatchDetail: Column {
    id: wdetail
    readonly property var watch: root.rep && root.rep.watch ? root.rep.watch : ({})
    readonly property var row: root.rowById("watch")
    readonly property int activeCount: Model.activeItems(root.watchItems).length
    spacing: Style.spacing.sm
    topPadding: Style.spacing.xs

    DetailText {
      width: wdetail.width
      text: Model.watchSummary(wdetail.watch, root.fmtWhen)
    }

    DetailText {
      width: wdetail.width
      text: String(wdetail.watch.lastScanError || "")
      color: root.warnColor
    }

    DetailText {
      width: wdetail.width
      text: wdetail.row && wdetail.row.intended && wdetail.watch.available === true
        && root.watchItems.length === 0 ? "Nothing flagged." : ""
    }

    // For the first scan, which flags everything already installed that
    // carries a signature. Reviewing each one by hand would be the only
    // other way to reach green.
    SmallButton {
      visible: wdetail.activeCount > 1 && root.confirming !== "review-all"
      text: "Mark all reviewed"
      onClicked: root.confirming = "review-all"
    }

    ConfirmLine {
      width: wdetail.width
      key: "review-all"
      question: "Mark all " + Model.plural(wdetail.activeCount, "unreviewed item") + " as allowed? This is meant for "
        + "the first scan, to accept what is already installed. Each can be cleared again here."
      actionText: "Mark " + wdetail.activeCount + " reviewed"
      onConfirmed: root.reviewAll()
    }

    Repeater {
      model: root.watchItems
      delegate: WatchItem {
        required property var modelData
        width: wdetail.width
        item: modelData
      }
    }
  }

  // Listen mode unfolded: how long it keeps what it sees, every program it
  // flagged with the hosts it contacted, red first, and the log's controls.
  component ListenDetail: Column {
    id: ldetail
    readonly property var listen: root.rep && root.rep.listen ? root.rep.listen : ({})
    readonly property var row: root.rowById("listen")
    readonly property bool isOn: !!row && row.intended === true
    spacing: Style.spacing.sm
    topPadding: Style.spacing.xs

    DetailText {
      width: ldetail.width
      text: Model.listenSummary(ldetail.listen, root.fmtWhen)
    }

    DetailText {
      width: ldetail.width
      text: ldetail.isOn && ldetail.listen.available === true && root.listenItems.length === 0
        ? "No program has contacted a known telemetry host in this window." : ""
    }

    Repeater {
      model: Model.listenGroups(root.listenItems)
      delegate: ListenGroup {
        required property var modelData
        width: ldetail.width
        group: modelData
      }
    }

    Row {
      spacing: Style.spacing.xs

      // The same as the row's switch, spelled out where the log is.
      SmallButton {
        visible: !!ldetail.row && ldetail.row.switchable && ldetail.row.status !== "na"
        text: ldetail.isOn ? "Turn listen mode off" : "Turn listen mode on"
        onClicked: root.setRow("listen", !ldetail.isOn)
      }

      SmallButton {
        visible: ldetail.isOn && root.confirming !== "purge"
        text: "Purge log"
        onClicked: root.confirming = "purge"
      }
    }

    ConfirmLine {
      width: ldetail.width
      key: "purge"
      question: "Purge the listen log now? Everything listen mode has seen so far is overwritten "
        + "and removed from RAM. Reviews are kept. This cannot be undone."
      actionText: "Purge"
      onConfirmed: root.purgeListen()
    }
  }

  component SectionHeading: Column {
    id: heading
    property string title: ""
    spacing: Style.spacing.sm
    PanelSeparator { width: heading.width; foreground: root.foreground }
    PanelSectionHeader {
      text: heading.title
      foreground: root.foreground
      fontFamily: root.fontFamily
    }
  }

  // ------------------------------------------------------------------ layout

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: false
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(860))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: column
          width: flick.width
          spacing: Style.spacing.lg

          // ---- Hero: the main switch, and one line saying whether what it
          // promises is holding.
          Column {
            width: parent.width
            spacing: Style.spacing.xxs

            Text {
              textFormat: Text.PlainText
              text: "BLACK OPS"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
            }

            Item {
              width: parent.width
              implicitHeight: Math.max(heroText.implicitHeight, masterSwitch.height)

              Text {
                id: heroText
                textFormat: Text.PlainText
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: root.rep ? (root.master ? "ON" : "OFF") : "..."
                color: root.overall === "leak" ? root.leakColor
                  : (root.overall === "warn" ? root.warnColor
                    : (root.master ? root.foreground : root.dim))
                font.family: root.fontFamily
                // Hero read-out, deliberately outside the Style.font.* scale.
                font.pixelSize: 34
                font.bold: true
              }

              ToggleSwitch {
                id: masterSwitch
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                checked: root.master
                busy: root.busy
                interactive: !!root.rep && !root.busy
                foreground: root.foreground
                onToggled: root.setMaster(!root.master)
              }
            }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: text !== ""
              text: root.rep ? root.rep.headline + "." : (root.busy ? "Working" : "")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              textFormat: Text.PlainText
              visible: text !== ""
              text: root.busy ? "working…" : root.fmtChecked()
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // Offered only when something has slipped or is not applied yet.
          // Switching on again is safe to repeat: what is in place is left
          // alone and only what is missing is put in place.
          Button {
            width: parent.width
            visible: root.master && !!root.rep
              && ((root.rep.slipped && root.rep.slipped.length > 0)
                || (root.rep.unapplied && root.rep.unapplied.length > 0))
            enabled: !root.busy
            opacity: enabled ? 1.0 : 0.45
            bordered: true
            text: root.rep && root.rep.slipped && root.rep.slipped.length > 0
              ? "Put back what has slipped" : "Apply what is new"
            foreground: root.warnColor
            accent: root.warnColor
            background: root.bar ? root.bar.background : Color.background
            fontFamily: root.fontFamily
            onClicked: root.setMaster(true)
          }

          // Bluetooth pairing is kept off while Black Ops is on, so a new
          // device is paired through a 60-second window opened here.
          Button {
            width: parent.width
            visible: !!root.rep && root.rep.canPair === true
            enabled: !root.busy && !!root.rep && !(root.rep.pairSecondsLeft > 0)
            opacity: enabled ? 1.0 : 0.45
            bordered: true
            text: root.rep && root.rep.pairSecondsLeft > 0
              ? "Open for pairing, " + root.rep.pairSecondsLeft + " s left"
              : "Pair a Bluetooth device for 60 seconds"
            foreground: root.foreground
            accent: root.foreground
            background: root.bar ? root.bar.background : Color.background
            fontFamily: root.fontFamily
            onClicked: root.pair()
          }

          Column {
            width: parent.width
            spacing: Style.spacing.lg
            visible: root.protectionRows.length > 0

            SectionHeading { width: parent.width; title: "Protections" }

            Column {
              width: parent.width
              spacing: Style.spacing.md

              Repeater {
                model: root.protectionRows
                delegate: ProtectionRow {
                  required property var modelData
                  width: parent.width
                  item: modelData
                }
              }
            }

            // Files in rows.d that were not read, each named once with why.
            Repeater {
              model: root.skippedFiles
              delegate: Text {
                required property var modelData
                textFormat: Text.PlainText
                width: parent.width
                text: "Skipped rows.d/" + modelData.file + ": " + modelData.why
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WrapAtWordBoundaryOrAnywhere
              }
            }
          }

          // Failures are shown rather than swallowed. A panel that draws a
          // protection as holding when the script could not say is the one
          // failure worth avoiding here.
          Column {
            width: parent.width
            spacing: Style.spacing.xs
            visible: root.error !== "" || root.helperNote !== "" || root.extensionErrors !== ""

            PanelSeparator { width: parent.width; foreground: root.foreground }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: text !== ""
              text: root.error
              color: root.warnColor
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: text !== ""
              text: root.extensionErrors
              color: root.warnColor
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Text {
              textFormat: Text.PlainText
              width: parent.width
              visible: text !== ""
              text: root.helperNote === "" ? ""
                : root.helperNote + " Rows that need root: " + root.privilegedLabels() + "."
              color: root.rep && root.rep.helperState === "outdated" ? root.warnColor : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
        }
      }
    }
  }
}
