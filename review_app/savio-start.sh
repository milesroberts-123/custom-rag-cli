#!/bin/bash
# Start the review app on this login node and record its location.
#
# hpc.brc.berkeley.edu round-robins across login nodes, so a plain
# "ssh -L 8501:localhost:8501 savio" tunnel only reaches the app if the app
# happens to run on the node that connection landed on. The laptop command
#
#   ssh -L 8501:localhost:8501 savio \
#     "bash /global/scratch/users/milesroberts/moi_lab_projects/custom-rag-cli/review_app/savio-start.sh"
#
# runs this script and the tunnel in the SAME connection, so the far end of
# the tunnel is always the node running the app.
#
# The app's host:pid are recorded in results/review/app.txt (on scratch).
# On reconnection, a live app on the current node is reused; a stale record
# on another node is killed before a new app starts, so two app processes
# never touch the SQLite database at once.
set -euo pipefail

REPO="/global/scratch/users/milesroberts/moi_lab_projects/custom-rag-cli"
STREAMLIT="/global/home/users/milesroberts/.local/share/mamba/envs/review-app/bin/streamlit"
MARKER="$REPO/results/review/app.txt"
LOG="$REPO/.snakemake/slurm_logs/review-app.log"

cd "$REPO"
mkdir -p "$(dirname "$MARKER")" "$(dirname "$LOG")"

if [[ -f "$MARKER" ]]; then
    read -r OLD_HOST OLD_PID < "$MARKER"
    if [[ "$OLD_HOST" == "$(hostname)" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "review app already running on $(hostname) (pid $OLD_PID)"
    else
        ssh -o BatchMode=yes -o ConnectTimeout=8 \
            "$OLD_HOST" "kill $OLD_PID" 2>/dev/null || true
        rm -f "$MARKER"
        nohup "$STREAMLIT" run review_app/app.py \
            --server.address 127.0.0.1 --server.port 8501 \
            > "$LOG" 2>&1 &
        echo "$(hostname) $!" > "$MARKER"
        echo "restarted review app on $(hostname)"
    fi
else
    nohup "$STREAMLIT" run review_app/app.py \
        --server.address 127.0.0.1 --server.port 8501 \
        > "$LOG" 2>&1 &
    echo "$(hostname) $!" > "$MARKER"
    echo "started review app on $(hostname)"
fi

for _ in $(seq 1 30); do
    curl -sf http://127.0.0.1:8501 >/dev/null && break
    sleep 1
done
curl -s -o /dev/null -w 'health: http://127.0.0.1:8501 -> %{http_code}\n' \
    http://127.0.0.1:8501