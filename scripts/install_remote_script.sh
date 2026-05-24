#!/usr/bin/env bash
# Installs the ableton-mcp-max Remote Script into Ableton Live 11,
# backing up any existing AbletonMCP script and fixing ownership.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/remote_script/AbletonMCP"
LIVE_RS="/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts"
DEST="$LIVE_RS/AbletonMCP"

if [ ! -d "$LIVE_RS" ]; then
  echo "ERROR: Live MIDI Remote Scripts dir not found: $LIVE_RS" >&2
  exit 1
fi

# Back up an existing install once (timestamped).
if [ -d "$DEST" ]; then
  BK="$LIVE_RS/AbletonMCP.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing $DEST -> $BK"
  sudo cp -R "$DEST" "$BK"
fi

echo "Installing Remote Script -> $DEST"
sudo mkdir -p "$DEST"
sudo cp "$SRC/__init__.py" "$DEST/__init__.py"
# CRITICAL: chown to the user. Live (sandboxed) silently skips root-owned
# remote-script folders during its control-surface scan.
sudo chown -R "$(id -un):admin" "$DEST"

echo "Done. Restart Ableton Live, then select 'AbletonMCP' as a Control Surface."
exit 0
