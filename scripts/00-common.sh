#!/usr/bin/env bash
# Shared configuration and helpers for the Skullcandy HQ Linux scripts.
# Override any of these by exporting them before running install.sh.

# Wine prefix dedicated to Skull-HQ (kept separate from your default prefix).
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-skullhq}"
export WINEARCH="${WINEARCH:-win64}"

# Where the bridge helper, DLL and launcher get installed.
export INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/share/skullcandy-hq}"

# Skullcandy USB vendor id (all Skullcandy headsets). Product id optional.
export SKDY_VENDOR="${SKDY_VENDOR:-34f0}"
export SKDY_PRODUCT="${SKDY_PRODUCT:-2220}"   # SLYR Pro (tested). Used only for the udev rule.

# Repo root (directory that contains this script's parent).
SCQ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SCQ_ROOT

log()  { printf '\033[1;36m[skullcandy-hq]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[skullcandy-hq] WARN:\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[skullcandy-hq] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Escape a string for safe use as the replacement (RHS) of a sed `s|…|…|`.
# Needed for Windows paths (backslashes), the `|` delimiter, and `&`.
sed_rhs() { printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'; }

# Find resources/app.asar inside the prefix (after the app is installed).
find_app_asar() {
    find "$WINEPREFIX/drive_c" -type f -path '*/resources/app.asar' 2>/dev/null | head -n1
}

# Find the directory that holds AirohaHidCoreLib.dll (where the hid.dll bridge goes).
# NB: capture into a quoted variable instead of `xargs dirname`, which would
# word-split paths containing spaces (e.g. "…/drive_c/Program Files/Skull-HQ/…").
find_airoha_dir() {
    local asar; asar="$(find_app_asar)"
    [ -n "$asar" ] || return 1
    local res; res="$(dirname "$asar")"
    local dll
    dll="$(find "$res/app.asar.unpacked" -type f -name 'AirohaHidCoreLib.dll' 2>/dev/null | head -n1)"
    [ -n "$dll" ] || return 1
    dirname "$dll"
}

# Locate the system Wine's builtin hid.dll (PE build).
find_wine_hid_dll() {
    for p in \
        /usr/lib/wine/x86_64-windows/hid.dll \
        /usr/lib64/wine/x86_64-windows/hid.dll \
        /opt/wine*/lib*/wine/x86_64-windows/hid.dll; do
        [ -f "$p" ] && { echo "$p"; return 0; }
    done
    return 1
}
