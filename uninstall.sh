#!/usr/bin/env bash
# Remove the Skullcandy HQ Linux integration (does NOT delete the Wine prefix
# or the app itself unless you pass --purge-prefix).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/scripts/00-common.sh"

PURGE_PREFIX=0
[ "${1:-}" = "--purge-prefix" ] && PURGE_PREFIX=1

log "Stopping and disabling the helper service…"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now hidbridge.service 2>/dev/null || true
fi
rm -f "$HOME/.config/systemd/user/hidbridge.service"
systemctl --user daemon-reload 2>/dev/null || true

log "Reverting the app.asar patch…"
ASAR="$(find_app_asar || true)"
[ -n "$ASAR" ] && python3 "$HERE/scripts/patch_asar.py" --revert "$ASAR" 2>/dev/null || true

log "Removing bridge DLLs from the app…"
AIROHA_DIR="$(find_airoha_dir || true)"
if [ -n "$AIROHA_DIR" ]; then
    rm -f "$AIROHA_DIR/hid.dll" "$AIROHA_DIR/hidwine.dll"
fi

log "Removing launcher, desktop entry and helper files…"
rm -f "$HOME/.local/share/applications/skullcandy-hq.desktop"
rm -rf "$INSTALL_DIR"

log "Removing udev rule (needs sudo)…"
sudo rm -f /etc/udev/rules.d/99-skullcandy.rules 2>/dev/null || \
    warn "Could not remove udev rule; do it manually: sudo rm /etc/udev/rules.d/99-skullcandy.rules"
sudo udevadm control --reload-rules 2>/dev/null || true

if [ "$PURGE_PREFIX" = 1 ]; then
    warn "Deleting Wine prefix $WINEPREFIX…"
    rm -rf "$WINEPREFIX"
fi
log "Uninstalled."
