#!/usr/bin/env bash
# Render the Lutris installer YAML from lutris/skullcandy-hq.yaml.in, baking in
# the absolute path to this cloned repo (Lutris needs it to call install.sh).
#
# Usage:
#   ./scripts/make_lutris_script.sh [OUTPUT.yaml]
#
# Default output: ./skullcandy-hq.lutris.yaml
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/00-common.sh
source "$HERE/00-common.sh"

TEMPLATE="$SCQ_ROOT/lutris/skullcandy-hq.yaml.in"
OUT="${1:-$SCQ_ROOT/skullcandy-hq.lutris.yaml}"

[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"

sed -e "s|@SCQ_ROOT@|$(sed_rhs "$SCQ_ROOT")|g" \
    -e "s|@INSTALL_DIR@|$(sed_rhs "$INSTALL_DIR")|g" \
    "$TEMPLATE" > "$OUT"

log "Wrote Lutris installer: $OUT"
if command -v lutris >/dev/null 2>&1; then
    log "Import it with:"
    printf '    lutris --install %q\n' "$OUT"
else
    warn "Lutris not found on PATH. Install it, then run: lutris --install '$OUT'"
fi
log "You'll be asked to pick the official Skull-HQ installer (.exe) during install."
