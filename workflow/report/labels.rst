Labels
======

One row per SRA run, with the tissue category, germplasm type, plant exposure
terms, and PECO study condition.

.. csv-table:: Per-sample labels
   :file: ../../results/labels.tsv
   :header-rows: 1
   :delim: tab

The ``review_required`` column marks rows that need a human check.
``review_reasons`` lists the triggers: ``tissue_other``,
``tissue_low_confidence``, ``germplasm_unknown``,
``germplasm_low_confidence``, ``exposure_other``,
``exposure_weak_retrieval``, ``study_other``, ``study_low_confidence``,
``no_paper``, and ``paper_low_confidence``.

``growth_system_ids`` and ``growth_system_labels`` are derived from exposure
terms under PECO:0007147 (plant growth medium exposure), so agar, hydroponic,
soil, and in vitro systems remain visible even though PECO classifies them
under plant exposure rather than plant study condition.
