#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
BASHRC="${HOME}/.bashrc"
TOOL="${REPO_DIR}/tools/cinemate-edit-settings.py"

[[ -f "$BASHRC" ]] || exit 0
[[ -f "$TOOL" ]] || {
    echo "warning: safe settings editor not found at $TOOL" >&2
    exit 0
}

if ! grep -q '^alias editsettings=' "$BASHRC"; then
    exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

awk -v replacement="alias editsettings='$TOOL'" '
    /^alias editsettings=/ { print replacement; next }
    { print }
' "$BASHRC" > "$tmp"

if ! cmp -s "$tmp" "$BASHRC"; then
    install -m 644 "$tmp" "$BASHRC"
    echo "Updated editsettings alias to validated atomic editor"
fi
