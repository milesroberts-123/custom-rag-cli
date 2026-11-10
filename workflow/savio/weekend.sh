#!/bin/bash
# Unattended window driver for Savio.
#
# Runs a sequence of batch windows and retries each one until it completes.
# Snakemake owns the Ollama server job, so a retry also restarts the model
# server: that is what makes an interrupted window resumable instead of a
# multi-day stall. Completed samples, chunks, and row fragments are cached, so
# a retry only redoes the tail.
#
# Usage (inside tmux, on a login node):
#   tmux new -s sra
#   bash workflow/savio/weekend.sh --size 5000 --windows 6
#
# Options:
#   --size N        runs per window (default 5000; keep <= 6000 for the 12 h
#                   Ollama server limit)
#   --windows N     number of consecutive windows (default 6)
#   --start N       first batch_index (default 1)
#   --retries N     attempts per window before giving up (default 3)
#   --retry-delay S seconds between attempts (default 300)
#   --samples PATH  sample sheet (default config/samples_all.tsv)
#   --dry-run       print the windows instead of submitting anything
#   -- ARGS...      extra arguments passed through to snakemake
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

SIZE=5000
WINDOWS=6
START=1
RETRIES=3
RETRY_DELAY=300
SAMPLES=config/samples_all.tsv
EXTRA=()
DRY=0

usage() {
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
    --size) SIZE="$2"; shift 2 ;;
    --windows) WINDOWS="$2"; shift 2 ;;
    --start) START="$2"; shift 2 ;;
    --retries) RETRIES="$2"; shift 2 ;;
    --retry-delay) RETRY_DELAY="$2"; shift 2 ;;
    --samples) SAMPLES="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; EXTRA=("$@"); break ;;
    *)
        echo "unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
done

mkdir -p results
LOG="results/weekend.log"

log() {
    printf '%s %s\n' "$(date '+%F %T')" "$*" | tee -a "$LOG"
}

if [[ -z "${TMUX:-}" ]]; then
    log "warning: not inside tmux; an SSH drop will kill this loop"
fi

log "driver start: size=$SIZE windows=$WINDOWS start=$START retries=$RETRIES"
log "samples=$SAMPLES extra=${EXTRA[*]:-none}"

for ((i = 0; i < WINDOWS; i++)); do
    INDEX=$((START + i))
    ATTEMPT=1
    while :; do
        log "window $INDEX ($SIZE runs): attempt $ATTEMPT/$RETRIES"
        if ((DRY)); then
            log "dry run: run.sh --config samples=$SAMPLES batch_size=$SIZE batch_index=$INDEX --keep-going"
            break
        fi
        if bash workflow/savio/run.sh \
            --config samples="$SAMPLES" batch_size="$SIZE" batch_index="$INDEX" \
            --keep-going "${EXTRA[@]+"${EXTRA[@]}"}"; then
            log "window $INDEX: complete"
            break
        fi
        if ((ATTEMPT >= RETRIES)); then
            log "window $INDEX: failed $RETRIES times; stopping so the failure can be inspected"
            exit 1
        fi
        log "window $INDEX: attempt $ATTEMPT failed; retrying in ${RETRY_DELAY}s"
        sleep "$RETRY_DELAY"
        ATTEMPT=$((ATTEMPT + 1))
    done
    # Give the scheduler a moment to release the GPU before the next window
    # submits its own model server.
    ((DRY)) || sleep 60
done

log "driver done: $WINDOWS window(s) from $START"
