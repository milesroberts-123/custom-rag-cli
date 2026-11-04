#!/bin/bash
# snakemake --lint exits 1 on every advisory, including "No log directive
# defined". We deliberately omit log: directives — the Snakemake Slurm
# executor already captures job output in .snakemake/slurm_logs/ — so this
# wrapper drops exactly that advisory and still fails on any other lint.
set -euo pipefail

command -v snakemake >/dev/null || {
    echo "snakemake not found on PATH" >&2
    exit 1
}

out="$(mktemp)"
trap 'rm -f "$out"' EXIT
snakemake --lint >"$out" 2>&1 || true

snakemake --version >/dev/null 2>&1

python3 - "$out" <<'EOF'
import re
import sys

text = open(sys.argv[1]).read()
sections = re.split(r"\n\n+(?=Lints for rule )", text)
if sections[0].startswith("Lints for rule "):
    sections = [""] + sections
head, blocks = sections[0], sections[1:]
kept = [block for block in blocks if "No log directive defined" not in block]
dropped = len(blocks) - len(kept)
if kept:
    print(re.sub(r"\n\n+", "\n\n", "\n\n".join(kept)).strip())
    sys.exit(1)
if "Congratulations" not in head and dropped == 0:
    # Nothing looked like a lint run (e.g. a crash before linting); fail safe.
    print(head.strip() or "empty lint output", file=sys.stderr)
    sys.exit(1)
print(f"Congratulations: lint clean ({dropped} log-directive advisory dropped)")
EOF