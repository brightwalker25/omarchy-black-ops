import QtQuick
import qs.Commons
import qs.Ui

// Derived from Omarchy's own `omarchy.weather` bar widget
// (https://github.com/basecamp/omarchy, MIT, Copyright (c) David Heinemeier
// Hansson). The injectPanel / open / close / closeForPopoutSwitch contract
// below is what the bar requires of any widget hosting a panel, and this file
// follows that implementation closely. See LICENSE for the full notice.

// One scope in the bar, and the switch and every protection behind it.
//
// The glyph carries the state in four ways and no more:
//
// - On, and everything holding: a rifle scope with its centre filled, in the same
//   fixed green as the panel's lights, so the bar and the panel agree.
// - On, but something has slipped or needs attention, or the software watch
//   or listen mode has flagged an item nobody has reviewed: the same scope in
//   amber. The colours are fixed rather than taken from the theme, for the
//   reason the panel gives.
// - On, and listen mode saw a program contact a telemetry host: the same
//   scope in red, the red Security Scan uses. Nothing else is red.
// - Off: an empty scope, dimmed the way the bar dims anything inactive, so the
//   difference reads from the shape as well as the colour.
//
// The panel owns the script and its readings, so the bar and the panel can
// never disagree about what the script said.
BarWidget {
  id: root
  moduleName: "brightwalker25.black-ops"

  // nf-md-crosshairs_gps and nf-md-crosshairs, from JetBrainsMono Nerd Font,
  // which is what the bar uses. A scope rather than a lock, so it cannot be
  // mistaken for Security Scan's lock, which usually sits beside it.
  readonly property string glyphOn: "󰆤"
  readonly property string glyphOff: "󰆣"

  readonly property var panelItem: panelLoader.item
  readonly property bool master: panelItem ? panelItem.master === true : false
  readonly property string overall: panelItem ? String(panelItem.overall || "") : ""
  readonly property bool failed: panelItem ? String(panelItem.error || "") !== "" && !panelItem.rep : false
  readonly property bool slipped: overall === "warn"
  readonly property bool leak: overall === "leak"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  function refresh() {
    if (panelLoader.item && panelLoader.item.poll) panelLoader.item.poll()
  }

  // Shape contract for shell.summon/hide/toggle routing: Bar.findPanelWidget
  // needs open/close/opened on the bar-widget root, not on the nested panel.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  // The bar prefers closeForPopoutSwitch over close when handing one panel
  // over to another, and reads popoutSwitchClosing back off the owner.
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.master ? root.glyphOn : root.glyphOff
    slotSize: Style.bar.iconSlot

    // The active colour is how the bar tints a glyph. It is red for a
    // confirmed telemetry contact, amber for a slip, or when the script could
    // not be read, since a silent failure would otherwise look the same as
    // all being well, and green when on and holding.
    useActiveColor: true
    active: root.master || root.slipped || root.leak || root.failed
    activeColor: root.leak ? "#f85149"
      : ((root.slipped || root.failed) ? "#d29922" : "#3fb950")
    dimmed: !root.master && !root.slipped && !root.leak && !root.failed

    // The headline, then what is red and what is amber by name, so the
    // colour can be explained without opening the panel.
    tooltipText: panelLoader.item ? String(panelLoader.item.tooltip || "") : ""

    onPressed: function(b) {
      if (b === Qt.MiddleButton) root.refresh()
      else root.togglePanel()
    }
  }
}
