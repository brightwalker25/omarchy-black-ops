import QtQuick

// Stands in for Omarchy's KeyboardPanel, which is a layer-shell window and
// cannot be made without a Wayland compositor. This one is a plain item of
// the same size with the same properties, so the panel's content is built,
// laid out and bound exactly as in the bar, with no window on any screen.
Item {
  property Item anchorItem: null
  property QtObject bar: null
  property var owner: null
  property bool centerOnBar: false
  property bool open: false
  property Item focusTarget: null
  property int contentWidth: 440
  property int contentHeight: 860
  default property alias contentItem: holder.data

  width: contentWidth
  height: contentHeight

  function fittedContentWidth(w) { return w }
  function fittedContentHeight(h, most) { return Math.min(h, most) }

  Item {
    id: holder
    anchors.fill: parent
  }
}
