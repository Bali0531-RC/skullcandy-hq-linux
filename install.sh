#!/usr/bin/env bash
#
# Skullcandy HQ on Linux — one-command installer.
#
# Sets up a dedicated Wine prefix, installs Skull-HQ (you provide the official
# installer), patches it for Linux device detection, builds/installs the native
# HID bridge, and wires up the udev rule, helper service, launcher and desktop
# entry.
#
# Usage:
#   ./install.sh --installer /path/to/Skull-HQ-Setup.exe
#   ./install.sh                 # if the app is already installed in the prefix
#
# Useful overrides (env):
#   WINEPREFIX   (default ~/.wine-skullhq)
#   INSTALL_DIR  (default ~/.local/share/skullcandy-hq)
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/00-common.sh
source "$HERE/scripts/00-common.sh"

INSTALLER=""
SKIP_DEPS=0
while [ $# -gt 0 ]; do
    case "$1" in
        --installer) INSTALLER="$2"; shift 2 ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# 0. Prerequisites
# ---------------------------------------------------------------------------
log "Checking prerequisites…"
command -v wine        >/dev/null || die "wine not found. Install system Wine (Arch: sudo pacman -S wine)."
command -v winetricks  >/dev/null || die "winetricks not found (Arch: sudo pacman -S winetricks)."
command -v python3     >/dev/null || die "python3 not found."
WINE_HID_DLL="$(find_wine_hid_dll || true)"
[ -n "$WINE_HID_DLL" ] || die "Could not find Wine's builtin hid.dll (x86_64-windows). Is system Wine installed?"
HAVE_MINGW=0; command -v x86_64-w64-mingw32-gcc >/dev/null && HAVE_MINGW=1
log "Wine hid.dll: $WINE_HID_DLL ; mingw: $([ $HAVE_MINGW = 1 ] && echo yes || echo 'no (will use prebuilt DLL)')"

# ---------------------------------------------------------------------------
# 1. Wine prefix + dependencies
# ---------------------------------------------------------------------------
if [ ! -d "$WINEPREFIX" ]; then
    log "Creating Wine prefix at $WINEPREFIX…"
    WINEDEBUG=-all wineboot -u >/dev/null 2>&1 || true
    wineserver -w 2>/dev/null || true
fi
if [ "$SKIP_DEPS" = 0 ]; then
    log "Installing Wine dependencies (vcrun2022, dotnet48) — this can take a while…"
    WINEDEBUG=-all winetricks -q vcrun2022 dotnet48 >/dev/null 2>&1 || \
        warn "winetricks reported issues; continuing (deps may already be present)."
fi

# ---------------------------------------------------------------------------
# 2. Install the app (if not already present)
# ---------------------------------------------------------------------------
ASAR="$(find_app_asar || true)"
if [ -z "$ASAR" ]; then
    [ -n "$INSTALLER" ] || die "Skull-HQ not found in the prefix. Re-run with --installer /path/to/Skull-HQ-Setup.exe"
    [ -f "$INSTALLER" ] || die "installer not found: $INSTALLER"
    log "Running the Skull-HQ installer under Wine…"
    log "(complete any installer prompts; this script waits until it finishes)"
    WINEDEBUG=-all wine "$INSTALLER" || true
    wineserver -w 2>/dev/null || true
    ASAR="$(find_app_asar || true)"
    [ -n "$ASAR" ] || die "Could not locate resources/app.asar after install. Did the installer finish?"
fi
log "App archive: $ASAR"
APP_EXE="$(find "$WINEPREFIX/drive_c" -type f -iname 'Skull-HQ.exe' 2>/dev/null | head -n1)"
[ -n "$APP_EXE" ] || die "Skull-HQ.exe not found in the prefix."
# Convert the unix path to a Windows path Wine understands.
APP_EXE_WIN="$(WINEDEBUG=-all winepath -w "$APP_EXE" 2>/dev/null || echo "$APP_EXE")"

# ---------------------------------------------------------------------------
# 3. Patch the asar for Linux device detection
# ---------------------------------------------------------------------------
log "Patching app.asar (Linux USB detection fallback)…"
python3 "$HERE/scripts/patch_asar.py" "$ASAR"

# ---------------------------------------------------------------------------
# 4. Install the HID bridge DLL next to AirohaHidCoreLib.dll
# ---------------------------------------------------------------------------
AIROHA_DIR="$(find_airoha_dir || true)"
[ -n "$AIROHA_DIR" ] || die "Could not find AirohaHidCoreLib.dll directory in the app."
log "Airoha native dir: $AIROHA_DIR"
if [ "$HAVE_MINGW" = 1 ]; then
    log "Building hid_bridge.dll with mingw…"
    bash "$HERE/scripts/build_dll.sh"
fi
[ -f "$HERE/dll/hid_bridge.dll" ] || die "hid_bridge.dll missing and mingw unavailable to build it."
cp "$WINE_HID_DLL"            "$AIROHA_DIR/hidwine.dll"   # the real Wine HID, renamed
cp "$HERE/dll/hid_bridge.dll" "$AIROHA_DIR/hid.dll"       # our shim takes the HID.DLL name

# ---------------------------------------------------------------------------
# 5. Install the bridge helper + enable the user service
# ---------------------------------------------------------------------------
log "Installing HID bridge helper to $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"
cp "$HERE/bridge/hidbridge.py" "$INSTALL_DIR/hidbridge.py"
cp "$HERE/dll/hid_bridge.dll"  "$INSTALL_DIR/hid_bridge.dll"
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/systemd/hidbridge.service" "$HOME/.config/systemd/user/hidbridge.service"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now hidbridge.service 2>/dev/null || \
        warn "Could not enable the user service (no systemd --user session?). The launcher will start the helper instead."
fi

# ---------------------------------------------------------------------------
# 6. Render and install the launcher + desktop entry
# ---------------------------------------------------------------------------
log "Installing launcher and desktop entry…"
sed -e "s|@WINEPREFIX@|$WINEPREFIX|g" \
    -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@APP_EXE@|$APP_EXE_WIN|g" \
    -e "s|@AIROHA_DIR@|$AIROHA_DIR|g" \
    -e "s|@WINE_HID_DLL@|$WINE_HID_DLL|g" \
    "$HERE/launcher/launch-skullhq.sh.in" > "$INSTALL_DIR/launch-skullhq.sh"
chmod +x "$INSTALL_DIR/launch-skullhq.sh"
mkdir -p "$HOME/.local/share/applications"
sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    "$HERE/desktop/skullcandy-hq.desktop.in" > "$HOME/.local/share/applications/skullcandy-hq.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 7. udev rule (needs root) — do it last so everything else is already done
# ---------------------------------------------------------------------------
log "Installing udev rule (needs sudo) so the device is usable without root…"
if sudo -n true 2>/dev/null || sudo -v 2>/dev/null; then
    sudo cp "$HERE/udev/99-skullcandy.rules" /etc/udev/rules.d/99-skullcandy.rules
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    log "udev rule installed."
else
    warn "Could not get sudo. Install the udev rule manually:"
    warn "  sudo cp '$HERE/udev/99-skullcandy.rules' /etc/udev/rules.d/99-skullcandy.rules"
    warn "  sudo udevadm control --reload-rules && sudo udevadm trigger"
fi

cat <<EOF

$(log "Done!")
Launch from your app menu ("Skullcandy HQ (SLYR Pro)") or run:
    $INSTALL_DIR/launch-skullhq.sh

Notes:
  * Plug the headset in via USB before launching.
  * Uses your SYSTEM Wine (not Proton/GE-Proton) — that's required for HID.
  * If the device was just plugged in, the udev rule sets permissions
    automatically; otherwise the launcher best-effort chmods the hidraw node.
EOF
