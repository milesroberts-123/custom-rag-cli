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
results/tissue/{run}.json
results/germplasm/{run}.json
results/exposure/{run}.json
results/study_condition/{run}.json
results/summary/{prjna}.json
resources/sra/{run}.json
resources/biosample/{samn}.json
resources/bioproject/{prjna}.json
resources/paper/{prjna}.json
resources/peco_index/terms.json
```

Missing metadata files are shown as empty sections. The PECO index is required
for editing; if it is absent, run the workflow index rule first.

## Setup

```bash
cd /path/to/custom-rag-cli
python3 -m venv .venv
. .venv/bin/activate
pip install -r review_app/requirements.txt
```

## Run

```bash
bash review_app/run.sh
```

Open <http://127.0.0.1:8501>.

On Savio, run one Streamlit process on a single login node and connect through
an SSH tunnel:

```bash
ssh -L 8501:localhost:8501 <savio-login-host>
```

Then open <http://127.0.0.1:8501> locally. Do not run multiple app processes
against the same SQLite file on a shared filesystem.

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
