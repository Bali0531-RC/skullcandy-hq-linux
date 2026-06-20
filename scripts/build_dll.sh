#!/usr/bin/env bash
# Build the bridging hid.dll (x86_64) with MinGW-w64.
# Output: dll/hid_bridge.dll
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CC="${MINGW_CC:-x86_64-w64-mingw32-gcc}"

if ! command -v "$CC" >/dev/null 2>&1; then
    echo "ERROR: $CC not found. Install mingw-w64 (Arch: sudo pacman -S mingw-w64-gcc)." >&2
    exit 1
fi

cd "$HERE/dll"
"$CC" -O2 -shared -o hid_bridge.dll hidbridge_dll.c hid.def -lkernel32 -lws2_32
echo "Built: $HERE/dll/hid_bridge.dll"
