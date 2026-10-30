#!/bin/bash
# Export the current OpenCode session to transcripts/<name>-<session>.json.xz.
set -euo pipefail

usage() {
    echo "usage: $0 <session-name> [--sanitize]" >&2
    exit 2
}

if [[ $# -lt 1 || $# -gt 2 ]]; then
    usage
fi

name="$1"
sanitize=()
if [[ $# -eq 2 ]]; then
    if [[ "$2" != "--sanitize" ]]; then
        usage
    fi
    sanitize=(--sanitize)
fi

session="${OPENCODE_SESSION_ID:?OPENCODE_SESSION_ID is not set}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$root/transcripts"

slug="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"
out="$root/transcripts/${slug:-session}-${session}.json.xz"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

opencode session export "${sanitize[@]}" "$session" > "$tmp"
xz -9 -c "$tmp" > "$out"

echo "$out"
