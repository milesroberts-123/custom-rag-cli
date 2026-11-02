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
``review_reasons`` lists the triggers (``rna_type_low_confidence``,
``tissue_other``, ``tissue_low_confidence``, ``germplasm_unknown``,
``germplasm_low_confidence``, ``exposure_other``, ``exposure_weak_retrieval``,
``study_other``, ``study_low_confidence``, ``no_paper``,
``paper_low_confidence``).
