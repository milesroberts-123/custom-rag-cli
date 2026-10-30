Labels
======

One row per SRA run, with the assigned tissue category and PECO terms.

.. csv-table:: Per-sample labels
   :file: ../../results/labels.tsv
   :header-rows: 1
   :delim: tab

The ``review_required`` column marks rows that need a human check;
``review_reasons`` lists the triggers (``tissue_other``,
``tissue_low_confidence``, ``peco_other``, ``peco_weak_retrieval``,
``no_paper``, ``paper_low_confidence``).
