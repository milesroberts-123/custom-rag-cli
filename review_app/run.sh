#!/bin/bash
# Start the review app on localhost. Use an SSH tunnel when running remotely.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

exec streamlit run review_app/app.py \
    --server.address "${HOST:-127.0.0.1}" \
    --server.port "${PORT:-8501}"
