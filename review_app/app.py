"""Streamlit app for human review of SRA annotation labels."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_app import db, export, loaders

REVIEW_VIEWS = ("Needs review", "All", "Reviewed")
SRA_FIELDS = (
    ("experiment_accession", "Experiment accession"),
    ("experiment_title", "Experiment title"),
    ("library_name", "Library name"),
    ("library_strategy", "Library strategy"),
    ("library_selection", "Library selection"),
    ("library_source", "Library source"),
    ("library_construction_protocol", "Library construction protocol"),
    ("sample_accession", "SRA sample accession"),
    ("sample_name", "Sample name"),
    ("study_accession", "Study accession"),
    ("study_title", "Study title"),
    ("study_abstract", "Study abstract"),
)


def _signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


@st.cache_data(show_spinner=False)
def _cached_labels(path: str, signature: str) -> pd.DataFrame:
    del signature
    return loaders.load_labels(Path(path))


@st.cache_data(show_spinner=False)
def _cached_terms(index_dir: str, signature: str) -> list[dict]:
    del signature
    return loaders.load_terms(Path(index_dir))


@st.cache_data(show_spinner=False)
def _cached_config(root: str, signature: str) -> dict:
    del signature
    return loaders.load_config(Path(root))


def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    return [item.strip() for item in str(value).split(";") if item.strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _term_label(term_id: str, terms_by_id: dict[str, dict]) -> str:
    if not term_id:
        return ""
    return terms_by_id.get(term_id, {}).get("label", term_id)


def _with_current(options: list[str], current: str) -> list[str]:
    values = list(dict.fromkeys(options))
    if current not in values:
        values.append(current)
    return values


def _paper_card(bundle: dict) -> None:
    paper = bundle["paper"]
    url = loaders.paper_url(paper)
    with st.expander("Linked paper", expanded=True):
        if not paper or paper.get("status") == "none":
            st.info("No linked publication for this BioProject.")
            return
        title = paper.get("title") or "Untitled paper"
        st.markdown(f"**{title}**")
        details = " · ".join(
            str(value) for value in (paper.get("journal"), paper.get("year")) if value
        )
        if details:
            st.caption(details)
        conditions = (bundle.get("summary") or {}).get("conditions") or {}
        reported = []
        day_length = conditions.get("day_length_hours")
        if isinstance(day_length, (int, float)):
            reported.append(f"day length: {_fmt_hours(day_length)} h light")
        temperature = conditions.get("growth_temperature_c")
        if isinstance(temperature, (int, float)):
            reported.append(f"temperature: {_fmt_number(temperature)} °C")
        if reported:
            st.caption("Reported: " + " · ".join(reported))
        if url:
            st.link_button("Open paper", url)
        if paper.get("abstract"):
            st.markdown(paper["abstract"])


def _fmt_hours(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _fmt_number(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _project_panel(project: str, bundle: dict, sample: pd.Series) -> None:
    bioproject = bundle["bioproject"]
    title = bioproject.get("title") or f"BioProject {project}"
    st.subheader(title)
    st.caption(f"{project} · {sample['species']} · {sample['run']}")
    if bioproject.get("description"):
        st.write(bioproject["description"])
    links = st.columns(2)
    with links[0]:
        st.link_button(
            "NCBI BioProject",
            f"https://www.ncbi.nlm.nih.gov/bioproject/{project}",
        )
    with links[1]:
        st.link_button(
            "NCBI SRA run",
            f"https://www.ncbi.nlm.nih.gov/sra/{sample['run']}",
        )
    _paper_card(bundle)


def _key_value_table(rows: list[tuple[str, Any]]) -> None:
    frame = pd.DataFrame(rows, columns=["field", "value"])
    st.dataframe(frame, hide_index=True)


def _metadata_tabs(
    bundle: dict, sample: pd.Series, status: dict, history: list[dict]
) -> None:
    tabs = st.tabs(
        [
            "Annotations",
            "SRA metadata",
            "BioSample",
            "BioProject",
            "AthRDB",
            "Model evidence",
            "History",
        ]
    )
    with tabs[1]:
        sra = bundle["sra"]
        _key_value_table([(label, sra.get(key, "")) for key, label in SRA_FIELDS])
        attributes = sra.get("sample_attributes") or {}
        if attributes:
            st.markdown("**SRA sample attributes**")
            st.dataframe(
                pd.DataFrame(
                    sorted(attributes.items()), columns=["attribute", "value"]
                ),
                hide_index=True,
            )
    with tabs[2]:
        biosample = bundle["biosample"]
        _key_value_table(
            [
                ("BioSample accession", sample["biosample"]),
                ("Organism", biosample.get("organism", "")),
            ]
        )
        attributes = biosample.get("attributes") or {}
        if attributes:
            st.markdown("**BioSample attributes**")
            st.dataframe(
                pd.DataFrame(
                    sorted(attributes.items()), columns=["attribute", "value"]
                ),
                hide_index=True,
            )
    with tabs[3]:
        bioproject = bundle["bioproject"]
        if not bioproject:
            st.info("BioProject metadata is not downloaded yet.")
        else:
            _key_value_table(
                [
                    ("Accession", bioproject.get("accession", "")),
                    ("UID", bioproject.get("uid", "")),
                    ("Organism", bioproject.get("organism", "")),
                    ("Status", bioproject.get("status", "")),
                    (
                        "Submission",
                        (bioproject.get("submission") or {}).get("submission_id", ""),
                    ),
                    (
                        "Last update",
                        (bioproject.get("submission") or {}).get("last_update", ""),
                    ),
                    (
                        "Organization",
                        (bioproject.get("submission") or {}).get("organization", ""),
                    ),
                    (
                        "Access",
                        (bioproject.get("submission") or {}).get("access", ""),
                    ),
                ]
            )
            st.json(bioproject.get("project_type") or {})
    with tabs[4]:
        athrdb = bundle["athrdb"] or {}
        if not athrdb.get("athrdb_hit"):
            note = athrdb.get("athrdb_note") or "no ATHRDB record"
            st.info(f"No curated PlantRNADB record ({note}).")
        else:
            gsm = athrdb.get("gsm")
            _key_value_table(
                [
                    ("GSM accession", gsm),
                    ("Tissue", athrdb.get("athrdb_tissue")),
                    ("Genotype", athrdb.get("athrdb_genotype")),
                    ("Ecotype", athrdb.get("athrdb_ecotype")),
                    ("Project", athrdb.get("athrdb_project")),
                    ("Release date", athrdb.get("athrdb_release_date")),
                    ("Title", athrdb.get("athrdb_title")),
                    ("Total reads", athrdb.get("athrdb_total_reads")),
                    ("Mapped rate", athrdb.get("athrdb_mapped_rate")),
                    ("Queried at", athrdb.get("queried_at")),
                ]
            )
            if gsm:
                st.link_button(
                    "Open GEO record",
                    f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={gsm}",
                )
    with tabs[5]:
        st.markdown("**RNA type**")
        st.json(bundle["rna_type"])
        st.markdown("**Tissue**")
        st.json(bundle["tissue"])
        st.markdown("**Germplasm**")
        st.json(bundle["germplasm"])
        st.markdown("**Exposure**")
        st.json(bundle["exposure"])
        st.markdown("**Study condition**")
        st.json(bundle["study"])
        if bundle["summary"]:
            st.markdown("**Paper condition summary**")
            st.json(bundle["summary"])
    with tabs[6]:
        if status.get("event_type"):
            st.caption(
                f"Review status: {status['event_type']} by "
                f"{status.get('reviewer', '')} at {status.get('ts', '')}"
            )
        if not history:
            st.info("No review events yet.")
        else:
            st.dataframe(
                pd.DataFrame(history)[
                    [
                        "ts",
                        "reviewer",
                        "event_type",
                        "field",
                        "old_value",
                        "new_value",
                        "note",
                    ]
                ],
                hide_index=True,
            )


def _save_edits(
    connection,
    reviewer: str,
    run: str,
    current: dict[str, Any],
    values: dict[str, Any],
) -> int:
    changes = 0
    for field, new_value in values.items():
        if field == "notes":
            if new_value != current["notes"]:
                db.record_event(
                    connection,
                    reviewer,
                    run,
                    "note",
                    field="notes",
                    new_value=new_value,
                )
                changes += 1
            continue
        old_value = current[field]
        if new_value != old_value:
            db.record_event(
                connection,
                reviewer,
                run,
                "edit",
                field=field,
                old_value=old_value,
                new_value=new_value,
            )
            changes += 1
    return changes


def _annotation_form(
    connection,
    reviewer: str,
    sample: pd.Series,
    edits: dict[tuple[str, str], Any],
    notes: dict[str, str],
    terms: list[dict],
    config: dict,
) -> None:
    run = sample["run"]
    terms_by_id = {term["id"]: term for term in terms}
    current = {
        "tissue": edits.get((run, "tissue"), sample.get("tissue") or ""),
        "germplasm_type": edits.get(
            (run, "germplasm_type"), sample.get("germplasm_type") or ""
        ),
        "peco_exposure_ids": edits.get(
            (run, "peco_exposure_ids"), sample.get("peco_exposure_ids") or ""
        ),
        "peco_exposure_other": _as_bool(
            edits.get(
                (run, "peco_exposure_other"),
                sample.get("peco_exposure_other"),
            )
        ),
        "peco_exposure_no_condition": _as_bool(
            edits.get(
                (run, "peco_exposure_no_condition"),
                sample.get("peco_exposure_no_condition"),
            )
        ),
        "peco_exposure_suggested_label": edits.get(
            (run, "peco_exposure_suggested_label"),
            sample.get("peco_exposure_suggested_label") or "",
        )
        or "",
        "peco_study_id": edits.get(
            (run, "peco_study_id"), sample.get("peco_study_id") or ""
        ),
        "notes": notes.get(run, ""),
    }

    tissue_options = _with_current(
        list(config["tissue"]["categories"]) + ["OTHER"],
        current["tissue"] or "OTHER",
    )
    current["tissue"] = current["tissue"] or "OTHER"
    germplasm_options = _with_current(
        list(config["germplasm"]["categories"]),
        current["germplasm_type"] or "unknown",
    )
    current["germplasm_type"] = current["germplasm_type"] or "unknown"
    exposure_terms = [term for term in terms if term.get("branch") == "exposure"]
    study_terms = [term for term in terms if term.get("branch") == "study_condition"]
    study_labels = [term["label"] for term in study_terms] + ["OTHER"]
    study_label_to_id = {term["label"]: term["id"] for term in study_terms}
    current_study_label = _term_label(current["peco_study_id"], terms_by_id)
    current_study_label = current_study_label or "OTHER"
    if current["peco_study_id"]:
        study_label_to_id.setdefault(current_study_label, current["peco_study_id"])
    study_label_to_id.setdefault("OTHER", "OTHER")
    study_labels = _with_current(study_labels, current_study_label)

    selected_exposure = list(dict.fromkeys(_split_ids(current["peco_exposure_ids"])))
    search = st.text_input(
        "Search PECO exposure terms",
        key=f"peco-search-{run}",
        placeholder="label, PECO ID, synonym, or definition",
    )

    def matches(term: dict) -> bool:
        query = search.strip().lower()
        if not query:
            return True
        haystack = " ".join(
            [
                term.get("id", ""),
                term.get("label", ""),
                term.get("definition", ""),
                " ".join(term.get("synonyms", [])),
            ]
        ).lower()
        return query in haystack

    filtered = [term for term in exposure_terms if matches(term)]
    option_ids = selected_exposure + [
        term["id"] for term in filtered if term["id"] not in selected_exposure
    ]

    with st.form(f"annotation-form-{run}"):
        columns = st.columns(2)
        with columns[0]:
            tissue = st.selectbox(
                "Tissue",
                tissue_options,
                index=tissue_options.index(current["tissue"]),
                key=f"tissue-{run}",
            )
            germplasm = st.selectbox(
                "Germplasm",
                germplasm_options,
                index=germplasm_options.index(current["germplasm_type"]),
                key=f"germplasm-{run}",
            )
        with columns[1]:
            study = st.selectbox(
                "PECO study condition",
                study_labels,
                index=study_labels.index(current_study_label),
                key=f"study-{run}",
            )
            no_condition = st.checkbox(
                "No condition to annotate",
                value=current["peco_exposure_no_condition"],
                key=f"no-condition-{run}",
            )
        exposure_ids = st.multiselect(
            "PECO exposure terms",
            option_ids,
            default=selected_exposure,
            format_func=lambda term_id: (
                f"{terms_by_id.get(term_id, {}).get('label', term_id)} — {term_id}"
            ),
            key=f"exposure-{run}",
        )
        other = st.checkbox(
            "Other exposure (no matching PECO term)",
            value=current["peco_exposure_other"],
            key=f"other-{run}",
        )
        suggested_label = st.text_input(
            "Other exposure description",
            value=current["peco_exposure_suggested_label"],
            key=f"suggested-{run}",
        )
        review_notes = st.text_area(
            "Review notes",
            value=current["notes"],
            key=f"notes-{run}",
        )
        st.caption(
            "Mark reviewed without changes records only the review status; "
            "unsaved form edits are ignored."
        )
        buttons = st.columns(3)
        with buttons[0]:
            save = st.form_submit_button("Save", disabled=not reviewer.strip())
        with buttons[1]:
            save_review = st.form_submit_button(
                "Save and mark reviewed", disabled=not reviewer.strip()
            )
        with buttons[2]:
            mark_review = st.form_submit_button(
                "Mark reviewed without changes", disabled=not reviewer.strip()
            )

    if save or save_review:
        if no_condition and other:
            st.error("Choose either no condition or other exposure, not both.")
        elif no_condition and exposure_ids:
            st.error("No condition cannot include specific PECO exposure terms.")
        else:
            values = {
                "tissue": tissue,
                "germplasm_type": germplasm,
                "peco_exposure_ids": ";".join(exposure_ids),
                "peco_exposure_other": other,
                "peco_exposure_no_condition": no_condition,
                "peco_exposure_suggested_label": suggested_label.strip(),
                "peco_study_id": study_label_to_id.get(study, "OTHER"),
                "notes": review_notes.strip(),
            }
            annotation_changed = any(
                values[field] != current[field] for field in values if field != "notes"
            )
            changes = _save_edits(connection, reviewer, run, current, values)
            if save_review:
                db.record_event(connection, reviewer, run, "reviewed")
            elif annotation_changed:
                current_status = db.review_status(connection).get(run, {})
                if current_status.get("event_type") == "reviewed":
                    db.record_event(
                        connection,
                        reviewer,
                        run,
                        "unreviewed",
                        note="edited after review",
                    )
            if changes or save_review:
                st.toast(
                    f"Saved {changes} change(s)"
                    + (" and marked reviewed" if save_review else "")
                )
                st.rerun()

    if mark_review:
        db.record_event(connection, reviewer, run, "reviewed")
        st.toast("Marked reviewed")
        st.rerun()

    last = db.last_edit(connection, run)
    if last is not None:
        if st.button(
            "Undo last edit",
            key=f"undo-{run}",
            disabled=not reviewer.strip(),
        ):
            db.record_event(
                connection,
                reviewer,
                run,
                "edit",
                field=last["field"],
                old_value=last["new_value"],
                new_value=last["old_value"],
                note="undo",
            )
            st.toast("Undid the last edit")
            st.rerun()


def _sidebar_export(root: Path, db_path: Path) -> None:
    st.sidebar.caption("Reviewer names are self-declared.")
    if st.sidebar.button("Export reviewed CSV + TSV"):
        try:
            result = export.export_reviewed(root=root, db_path=db_path)
            st.sidebar.success(f"Wrote {result['csv']}")
        except Exception as error:  # noqa: BLE001
            st.sidebar.error(str(error))
    csv_path = root / "results" / "labels.reviewed.csv"
    if csv_path.exists():
        st.sidebar.download_button(
            "Download reviewed CSV",
            data=csv_path.read_bytes(),
            file_name="labels.reviewed.csv",
            mime="text/csv",
        )


def _render() -> None:
    st.set_page_config(
        page_title="SRA annotation review",
        page_icon="🌱",
        layout="wide",
    )
    root = Path(os.environ.get("REVIEW_APP_ROOT", ROOT))
    labels_path = root / "results" / "labels.tsv"
    index_dir = root / "resources" / "peco_index"
    config_path = root / "config" / "config.yaml"
    if not labels_path.exists():
        st.error(f"Missing annotation table: {labels_path}")
        st.stop()
    if not index_dir.exists() or not (index_dir / "terms.json").exists():
        st.error(f"Missing PECO index: {index_dir}")
        st.stop()
    if not config_path.exists():
        st.error(f"Missing configuration: {config_path}")
        st.stop()

    labels = _cached_labels(str(labels_path), _signature(labels_path))
    terms = _cached_terms(str(index_dir), _signature(index_dir / "terms.json"))
    config = _cached_config(str(root), _signature(config_path))
    terms_by_id = {term["id"]: term for term in terms}

    db_path = Path(
        os.environ.get("REVIEW_APP_DB", root / "results" / "review" / "review.db")
    )
    connection = db.connect(db_path)
    try:
        previous_import = db.latest_import_id(connection)
        source_sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
        import_id, imported = db.import_base(
            connection,
            labels.to_dict("records"),
            labels_path,
            source_sha,
        )
        if imported and previous_import is not None:
            changes = db.compare_imports(connection, previous_import, import_id)
            if any(changes.values()):
                st.warning(
                    "labels.tsv changed since the last import: "
                    f"{len(changes['added'])} added, "
                    f"{len(changes['removed'])} removed, "
                    f"{len(changes['changed'])} changed. "
                    "Review changed runs again."
                )

        statuses = db.review_status(connection)
        reviewed_runs = {
            run
            for run, status in statuses.items()
            if status.get("event_type") == "reviewed"
        }
        counts = db.counts(connection, import_id)
        edits = db.latest_edits(connection)
        notes = db.latest_notes(connection)
        labels = labels.copy()
        labels["_reviewed"] = labels["run"].isin(reviewed_runs)

        st.sidebar.title("Review queue")
        reviewer = st.sidebar.text_input(
            "Reviewer", key="reviewer", placeholder="your name"
        )
        st.sidebar.caption(
            f"{counts['reviewed']} reviewed · {counts['remaining']} remaining"
        )
        if counts["total"]:
            st.sidebar.progress(counts["reviewed"] / counts["total"])
        view = st.sidebar.radio("Show", REVIEW_VIEWS, index=0)
        if view == "Needs review":
            visible = labels[~labels["_reviewed"]]
        elif view == "Reviewed":
            visible = labels[labels["_reviewed"]]
        else:
            visible = labels

        _sidebar_export(root, db_path)

        if visible.empty:
            st.info("No runs match the current filter.")
            return

        project_stats = (
            visible.groupby("bioproject", dropna=False)
            .agg(total=("run", "size"), reviewed=("_reviewed", "sum"))
            .reset_index()
        )
        project_stats["remaining"] = project_stats["total"] - project_stats["reviewed"]
        project_stats = project_stats.sort_values(
            ["remaining", "bioproject"], ascending=[False, True]
        )
        project_labels = {
            row.bioproject: (f"{row.bioproject} · {row.reviewed}/{row.total} reviewed")
            for row in project_stats.itertuples()
        }
        project = st.sidebar.selectbox(
            "BioProject",
            project_stats["bioproject"].tolist(),
            format_func=lambda value: project_labels[value],
        )
        project_runs = visible[visible["bioproject"] == project].copy()
        project_runs = project_runs.sort_values(
            ["_reviewed", "run"], ascending=[True, True]
        )
        run_labels = {
            row["run"]: (
                f"{row['run']} · {'reviewed' if row['_reviewed'] else 'pending'}"
            )
            for row in project_runs.to_dict("records")
        }
        run = st.sidebar.selectbox(
            "Run",
            project_runs["run"].tolist(),
            format_func=lambda value: run_labels[value],
        )

        sample = labels[labels["run"] == run].iloc[0]
        bundle = loaders.load_run_bundle(root, sample)
        status = statuses.get(run, {})
        history = db.event_history(connection, run)

        st.title("SRA annotation review")
        if status.get("event_type") == "reviewed":
            st.success(
                f"Reviewed by {status.get('reviewer', '')} at {status.get('ts', '')}"
            )
        elif sample.get("review_required") == "True":
            st.warning("Model review reasons: " + (sample.get("review_reasons") or ""))
        else:
            st.info("The model did not flag this run.")

        _project_panel(project, bundle, sample)
        st.markdown("**Runs in this BioProject**")
        project_table = labels[labels["bioproject"] == project][
            ["run", "biosample", "tissue", "germplasm_type", "_reviewed"]
        ].copy()
        project_table["tissue"] = [
            edits.get((run_value, "tissue"), tissue_value)
            for run_value, tissue_value in zip(
                project_table["run"], project_table["tissue"]
            )
        ]
        project_table["germplasm_type"] = [
            edits.get((run_value, "germplasm_type"), germplasm_value)
            for run_value, germplasm_value in zip(
                project_table["run"], project_table["germplasm_type"]
            )
        ]
        project_table["status"] = project_table["_reviewed"].map(
            {True: "reviewed", False: "pending"}
        )
        st.dataframe(
            project_table[["run", "biosample", "tissue", "germplasm_type", "status"]],
            hide_index=True,
        )
        _metadata_tabs(bundle, sample, status, history)
        with st.expander("Annotation", expanded=True):
            _annotation_form(
                connection,
                reviewer,
                sample,
                edits,
                notes,
                terms,
                config,
            )
        if db.orphan_runs(connection, import_id):
            st.warning(
                "Some review events refer to runs that are no longer in "
                "labels.tsv; they are retained in the audit log but excluded "
                "from the export."
            )
        if terms_by_id:
            st.caption(f"PECO index: {len(terms)} terms loaded from {index_dir}")
    finally:
        connection.close()


def main() -> None:
    _render()


if __name__ == "__main__":
    main()
