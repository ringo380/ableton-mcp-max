#!/usr/bin/env bash
# Installs the ableton-mcp-max Remote Script into every installed Ableton Live
# (Live 11 and Live 12 are both supported), backing up any existing AbletonMCP
# script and fixing ownership.
#
# By default it discovers all /Applications/Ableton*Live*.app bundles that have
# a "MIDI Remote Scripts" dir and installs into each. To target one specific
# install, set LIVE_APP to its .app path, e.g.:
#   LIVE_APP="/Applications/Ableton Live 12 Suite.app" bash scripts/install_remote_script.sh
set -u

# Use absolute tool paths / a sane PATH: under some shells `sudo`'s secure_path
# or a clobbered PATH makes `chown`/`mkdir` resolve to "command not found",
# which silently leaves the install root-owned (Live then skips it).
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_DIR/remote_script/AbletonMCP"
# Keep backups OUTSIDE the Remote Scripts dir. Live scans every subfolder there
# as a control surface and tries to `import` it; a backup named
# "AbletonMCP.bak.<timestamp>" is an invalid module name and throws a
# SyntaxError on every launch (and pollutes the Control Surface dropdown).
BACKUP_DIR="$HOME/.ableton-mcp-rs-backups"

# Install into a single Live bundle's "MIDI Remote Scripts" dir.
install_into() {
  local app="$1"
  local live_rs="$app/Contents/App-Resources/MIDI Remote Scripts"
  local dest="$live_rs/AbletonMCP"

  if [ ! -d "$live_rs" ]; then
    echo "SKIP: no MIDI Remote Scripts dir in $app" >&2
    return 1
  fi

  echo "=== $(basename "$app") ==="

  # Back up an existing install once (timestamped), OUTSIDE the RS dir.
  if [ -d "$dest" ]; then
    /bin/mkdir -p "$BACKUP_DIR"
    local bk="$BACKUP_DIR/AbletonMCP.$(basename "$app" .app).bak.$(date +%Y%m%d-%H%M%S)"
    echo "Backing up existing $dest -> $bk"
    sudo /bin/cp -R "$dest" "$bk"
  fi

  # If older backups were left inside the RS dir by a previous version of this
  # script, relocate them so Live stops choking on them.
  for stale in "$live_rs"/AbletonMCP.bak.*; do
    [ -d "$stale" ] || continue
    /bin/mkdir -p "$BACKUP_DIR"
    echo "Relocating stray backup out of Remote Scripts dir: $(basename "$stale")"
    sudo /bin/mv "$stale" "$BACKUP_DIR/"
  done

  echo "Installing Remote Script -> $dest"
  sudo /bin/mkdir -p "$dest"
  sudo /bin/cp "$SRC/__init__.py" "$dest/__init__.py"
  # Drop any stale bytecode so Live recompiles from the new source.
  sudo /bin/rm -rf "$dest/__pycache__"
  # CRITICAL: chown to the user. Live (sandboxed) silently skips root-owned
  # remote-script folders during its control-surface scan.
  sudo /usr/sbin/chown -R "$(/usr/bin/id -un):admin" "$dest"
  return 0
}

# Collect target bundles: explicit LIVE_APP override, else every installed Live.
APPS=()
if [ "${LIVE_APP:-}" != "" ]; then
  APPS+=("$LIVE_APP")
else
  for app in /Applications/Ableton*Live*.app; do
    [ -d "$app/Contents/App-Resources/MIDI Remote Scripts" ] || continue
    APPS+=("$app")
  done
fi

if [ "${#APPS[@]}" -eq 0 ]; then
  echo "ERROR: no Ableton Live install found under /Applications with a" >&2
  echo "       'MIDI Remote Scripts' dir. Is Ableton Live 11 or 12 installed?" >&2
  exit 1
fi

installed=0
for app in "${APPS[@]}"; do
  if install_into "$app"; then
    installed=$((installed + 1))
  fi
done

if [ "$installed" -eq 0 ]; then
  echo "ERROR: nothing installed." >&2
  exit 1
fi

echo
echo "Done ($installed install(s)). Restart Ableton Live, then select 'AbletonMCP' as a Control Surface."
exit 0
