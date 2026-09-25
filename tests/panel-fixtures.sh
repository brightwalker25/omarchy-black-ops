#!/usr/bin/env bash
# Feeds each status JSON fixture in tests/panel-fixtures to Panel.qml through
# the panel's own collector, and prints what the panel then shows.
#
# It runs a separate quickshell with its own config folder in a temporary
# directory, on Qt's offscreen platform, with no Wayland or Hyprland
# connection, so it cannot draw on a screen, and it cannot be reached by
# omarchy-shell, which addresses the running shell by its own path. The
# panel's commands are logged rather than run while BLACK_OPS_PANEL_FIXTURE
# is set, so nothing is switched and nothing is reviewed.
#
#   tests/panel-fixtures.sh              every fixture
#   tests/panel-fixtures.sh listen-red   one
#
# Exits nonzero if a fixture fails to load or the QML engine reports an error.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
shell_dir=${OMARCHY_PATH:-/usr/share/omarchy}/shell
command -v quickshell >/dev/null || { echo "quickshell is not installed" >&2; exit 2; }
[[ -d $shell_dir/Ui ]] || { echo "no Omarchy shell at $shell_dir" >&2; exit 2; }

work=$(mktemp -d "${TMPDIR:-/tmp}/black-ops-panel.XXXXXX")
trap 'rm -rf "$work"' EXIT

# The Omarchy modules the panel imports, with KeyboardPanel swapped for a
# plain item, since a layer-shell window cannot be made offscreen.
ln -s "$shell_dir/Commons" "$work/Commons"
mkdir "$work/Ui"
for f in "$shell_dir"/Ui/*; do
  [[ $(basename "$f") == KeyboardPanel.qml ]] || ln -s "$f" "$work/Ui/"
done
cp "$repo/tests/panel-probe/KeyboardPanel.qml" "$work/Ui/"
ln -s "$repo" "$work/plugin"
cp "$repo/tests/panel-probe/shell.qml" "$work/shell.qml"

if (($#)); then names=("$@"); else
  names=()
  for f in "$repo"/tests/panel-fixtures/*.json; do names+=("$(basename "$f" .json)"); done
fi

status=0
for name in "${names[@]}"; do
  fixture=$repo/tests/panel-fixtures/$name.json
  echo "==== $name"
  out=$(cd "$work" && env -u WAYLAND_DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE \
    QT_QPA_PLATFORM=offscreen BLACK_OPS_PANEL_FIXTURE="$fixture" \
    timeout 30 quickshell -p "$work/shell.qml" 2>&1) || true
  # Strip the colour codes quickshell puts in its log lines.
  out=$(sed 's/\x1b\[[0-9;]*m//g' <<<"$out")
  grep -oE '(PROBE |black-ops panel fixture: ).*' <<<"$out" \
    | sed -e 's/^PROBE //' -e 's/^black-ops panel fixture: /action | /' || true
  errors=$(grep -v 'PROBE ' <<<"$out" \
    | grep -E 'TypeError|ReferenceError|SyntaxError|is not a type|unavailable|Cannot assign|Unable to assign|Error:' || true)
  if [[ -n $errors ]] || ! grep -q 'PROBE done' <<<"$out"; then
    echo "!!!! $name failed"
    [[ -n $errors ]] && echo "$errors"
    status=1
  fi
done
exit $status
