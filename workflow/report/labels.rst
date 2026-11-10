Labels
======

One row per mRNA-eligible SRA run, with the RNA type, tissue category, and
PECO terms. Runs classified as total RNA, small RNA, other RNA, non-RNA, or
unknown are listed in ``results/labels.excluded.tsv`` instead.

.. csv-table:: Per-sample labels
   :file: ../../results/labels.tsv
   :header-rows: 1
   :delim: tab

The ``rna_type`` column records ``mrna`` or
``ribo_depleted_total_rna`` for included runs. ``rna_type_evidence`` records
the metadata field that drove the call.

The ``review_required`` column marks rows that need a human check;
``review_reasons`` lists the triggers. Review is gated on model uncertainty
only: ``rna_type_low_confidence``, ``tissue_low_confidence``,
``germplasm_low_confidence``, ``exposure_weak_retrieval``,
``study_low_confidence``, ``athrdb_disagreement``, and
``mixed_run_context``. An ``OTHER``/``unknown`` label is a result, not a
review trigger, even though it is reported in its own column.

The ``metadata_tier`` column separates records that carry no biological
metadata (``empty``) from ``partial`` and ``annotated`` ones, and
``metadata_missing`` lists which evidence families are absent, so label-quality
statistics can be read per tier instead of being dominated by bare submissions.
