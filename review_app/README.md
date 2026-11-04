# Annotation review app

Streamlit app for reviewing the SRA annotation table produced by the Snakemake
workflow. It groups runs by BioProject, shows the linked paper and metadata, and
records every human edit in SQLite.

The app never modifies `results/labels.tsv`. It writes:

- `results/review/review.db` — base snapshots, edits, review status, and notes
- `results/labels.reviewed.csv` — final annotations plus provenance
- `results/labels.reviewed.tsv` — the same table in TSV form

## Data requirements

Run the workflow first so these exist:

```text
results/labels.tsv
results/labels.excluded.tsv
results/rna_type/{run}.json
results/tissue/{run}.json
results/germplasm/{run}.json
results/exposure/{run}.json
results/study_condition/{run}.json
results/summary/{prjna}.json
results/metadata/sra/{run}.json
results/metadata/biosample/{samn}.json
results/metadata/bioproject/{prjna}.json
results/metadata/paper/{prjna}.json
results/metadata/athrdb/{run}.json
results/peco/peco_index/terms.json
```

Missing metadata files are shown as empty sections. The PECO index is required
for editing; if it is absent, run the workflow index rule first.

## Setup

Any Python environment manager works — the app is pure Python with no
compiled extensions. Two options:

```bash
# venv
cd /path/to/custom-rag-cli
python3 -m venv .venv
. .venv/bin/activate
pip install -r review_app/requirements.txt
```

```bash
# conda (all three runtime packages exist on conda-forge; pip is optional)
mamba create -y -n review-app -c conda-forge \
    python=3.12 streamlit=1.66.1 pandas=2.2.3 pyyaml=6.0.2
mamba activate review-app

# or keep the requirements file as the single source of pins:
# mamba create -y -n review-app python=3.12
# mamba activate review-app
# pip install -r review_app/requirements.txt
```

`review_app/run.sh` only needs `streamlit` on `PATH`, so no script changes
are required for either method.

## Run

```bash
bash review_app/run.sh
```

Open <http://127.0.0.1:8501>.

### Running on Savio

`hpc.brc.berkeley.edu` round-robins across several login nodes (`ln000`–
`ln003`), and the SSH tunnel and the app must be on the **same node** for
`localhost:8501` to resolve. So start the app and the tunnel in a single
SSH command, using `review_app/savio-start.sh` — the tunnel's far end is
then guaranteed to be the node the app runs on:

```bash
# on your laptop — leave this terminal open; it IS the tunnel
ssh -L 8501:localhost:8501 savio \
  "bash /global/scratch/users/milesroberts/moi_lab_projects/custom-rag-cli/review_app/savio-start.sh; \
   echo 'app is up — leave this window open, Ctrl-C to close the tunnel'; \
   sleep infinity"
```

Then open <http://localhost:8501>.

`savio-start.sh` records the app's host and PID in
`results/review/app.txt` (on scratch). Reconnecting with the same command
reuses a live app on the current node, or kills a stale app left on another
node before starting a new one — so two app processes never touch the
SQLite database at once. The app's own log is
`.snakemake/slurm_logs/review-app.log`.

Why the login node: the app needs no GPU or Ollama, `/global/scratch` is
mounted there so all workflow outputs are readable, and compute nodes are
needlessly awkward to reach (double-hop tunnels) and vanish when the job
ends.

Notes:

- Do **not** run `bash review_app/run.sh` in one SSH session and tunnel from
  another `ssh savio` connection: the two connections can land on different
  login nodes, and `localhost:8501` in the tunnel will hit the wrong node.
- The app binds to `127.0.0.1` by design. Do not set `HOST=0.0.0.0` to skip
  the tunnel; the review database should not be network-visible, and BRC's
  network won't make it reliably reachable anyway.
- Do not run multiple app processes against the same SQLite file on a shared
  filesystem. Multiple reviewers should tunnel to the same login-node
  process; if you ever need independent app hosts, move to Postgres.

### Troubleshooting the tunnel

- **`ssh: connect to host savio port 22: No route to host`** — the command is
  running on the wrong machine or network. It must run in a local terminal
  on your laptop, *not* inside an SSH session to Savio: login nodes have no
  route back to the gateway's public IPs, so the tunnel can never be
  established from there. If you're off-campus, connect the BRC VPN first —
  with it down you get exactly this error. Check with
  `ssh savio hostname`, then rerun the tunnel command.
- **The tunnel connects but the browser can't open the page** — verify the
  app is healthy on the tunnel's node. In the tunnel's terminal window run
  `curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8501`; `200`
  means the app is up and the tunnel is correct. If that reports `000`, the
  app failed to start — read `.snakemake/slurm_logs/review-app.log` on the
  login node and rerun the tunnel command.
- **The app won't start (500 or blank page)** — the workflow outputs may be
  missing or incomplete. The app reads `results/labels.tsv`, the per-run
  label JSONs, `results/metadata/`, and
  `results/peco/peco_index/terms.json`; run the workflow first (or at least
  `build_peco_index`) so they exist.

The app reviews only the mRNA-eligible runs in `results/labels.tsv`. Runs
excluded by the RNA-type filter are listed in `results/labels.excluded.tsv` and
are not shown in the review queue.

## Review flow

- The sidebar filters projects and runs by review status.
- A run counts as reviewed only after **Mark reviewed without changes** or
  **Save and mark reviewed**.
- **Save** records edits but leaves the run pending. Editing an annotation on a
  reviewed run returns it to pending unless you use **Save and mark reviewed**.
- **Mark reviewed without changes** records only the review action; unsaved
  form edits are ignored.
- **Undo last edit** appends the inverse edit. Events are never deleted.
- **No condition** and **Other exposure** are mutually exclusive; no-condition
  runs cannot also carry specific PECO terms.

Reviewer names are self-declared and stored with every event. This is an audit
trail for lab use, not authenticated attribution.

## Export

Use the sidebar button, or run:

```bash
python -m review_app.export
```

Options:

```bash
python -m review_app.export \
  --root . \
  --db results/review/review.db \
  --csv results/labels.reviewed.csv \
  --tsv results/labels.reviewed.tsv
```

`--no-tsv` writes only the CSV.

## Reviewed table columns

The final annotation columns contain human values where edited. Provenance
columns preserve the model output:

- `model_tissue`
- `model_germplasm_type`
- `model_peco_exposure_ids`
- `model_peco_study_id`
- `model_review_required`
- `model_review_reasons`

Additional exposure fields:

- `peco_exposure_no_condition`
- `peco_exposure_suggested_label`

Review columns:

- `review_status` — `pending` or `reviewed`
- `reviewed` — boolean
- `reviewed_by`
- `reviewed_at`
- `review_notes`
- `review_required` — true only while the model flagged the run and it is still
  pending
- `review_reasons` — original model reasons

Derived columns are recomputed from the final values:

- `is_natural_accession`
- `peco_exposure_labels`
- `peco_study_label`
- `growth_system_ids`
- `growth_system_labels`

## Conflict handling

On startup the app hashes `results/labels.tsv`. A changed file creates a new
base snapshot and keeps all events. If runs were added, removed, or their model
labels changed, the app shows a warning and leaves those runs pending for
re-review. Events for removed runs stay in the database but are excluded from
the export.

## Tests

```bash
pip install -r review_app/requirements-dev.txt
pytest -q review_app/tests workflow/tests
ruff check review_app workflow/scripts workflow/tests
ruff format --check review_app workflow/scripts workflow/tests
```

## Limitations

- One shared app process and one SQLite database; use Postgres if you need
  multiple app hosts.
- Reviewer names are not authenticated.
- The paper link prefers Europe PMC when a PMCID exists, then PubMed, then
  shows “no linked publication.”
- The app does not display full-text PDFs. Use the paper link.
