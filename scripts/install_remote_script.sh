#!/usr/bin/env bash
# Installs the ableton-mcp-max Remote Script into Ableton Live 11,
# backing up any existing AbletonMCP script and fixing ownership.
set -u

# Use absolute tool paths / a sane PATH: under some shells `sudo`'s secure_path
# or a clobbered PATH makes `chown`/`mkdir` resolve to "command not found",
# which silently leaves the install root-owned (Live then skips it).
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/remote_script/AbletonMCP"
LIVE_RS="/Applications/Ableton Live 11 Suite.app/Contents/App-Resources/MIDI Remote Scripts"
DEST="$LIVE_RS/AbletonMCP"
# Keep backups OUTSIDE the Remote Scripts dir. Live scans every subfolder there
# as a control surface and tries to `import` it; a backup named
# "AbletonMCP.bak.<timestamp>" is an invalid module name and throws a
# SyntaxError on every launch (and pollutes the Control Surface dropdown).
BACKUP_DIR="$HOME/.ableton-mcp-rs-backups"

if [ ! -d "$LIVE_RS" ]; then
  echo "ERROR: Live MIDI Remote Scripts dir not found: $LIVE_RS" >&2
  exit 1
fi

# Back up an existing install once (timestamped), OUTSIDE the RS dir.
if [ -d "$DEST" ]; then
  /bin/mkdir -p "$BACKUP_DIR"
  BK="$BACKUP_DIR/AbletonMCP.bak.$(date +%Y%m%d-%H%M%S)"
  echo "Backing up existing $DEST -> $BK"
  sudo /bin/cp -R "$DEST" "$BK"
fi

# If older backups were left inside the RS dir by a previous version of this
# script, relocate them so Live stops choking on them.
for stale in "$LIVE_RS"/AbletonMCP.bak.*; do
  [ -d "$stale" ] || continue
  /bin/mkdir -p "$BACKUP_DIR"
  echo "Relocating stray backup out of Remote Scripts dir: $(basename "$stale")"
  sudo /bin/mv "$stale" "$BACKUP_DIR/"
done

echo "Installing Remote Script -> $DEST"
sudo /bin/mkdir -p "$DEST"
sudo /bin/cp "$SRC/__init__.py" "$DEST/__init__.py"
# Drop any stale bytecode so Live recompiles from the new source.
sudo /bin/rm -rf "$DEST/__pycache__"
# CRITICAL: chown to the user. Live (sandboxed) silently skips root-owned
# remote-script folders during its control-surface scan.
sudo /usr/sbin/chown -R "$(/usr/bin/id -un):admin" "$DEST"

echo "Done. Restart Ableton Live, then select 'AbletonMCP' as a Control Surface."
exit 0
