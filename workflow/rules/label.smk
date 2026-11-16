# Label rules process runs in chunks (`label_chunk_size` runs per job) so the
# interpreter and model payloads load once per chunk. Snakemake cannot list
# per-run outputs on a multi-run job, so each chunk declares one marker file;
# the script writes the per-run JSONs beside it, and downstream rules depend
# on the markers. The per-run files stay the aggregation/review contract.


rule label_tissue:
    input:
        rna_type="results/chunks/rna_type/{chunk}.done",
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
    output:
        "results/chunks/tissue/{chunk}.done",
    benchmark:
        benchmark("label_tissue", f"{WINDOW_INDEX}-{{chunk}}")
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("tissue", decision=True),
        samns=chunk_samns,
        runs=chunk_runs,
        prjnas=chunk_prjnas,
        categories=config["tissue"]["categories"],
        keywords=config["tissue"]["keywords"],
        rule_attribute_keys=config["tissue"]["rule_attribute_keys"],
        po_terms=config["tissue"]["po_terms"],
        attribute_keys=config["tissue"]["attribute_keys"],
        other_description=config["tissue"]["other_description"],
    script:
        "../scripts/label_tissue.py"


rule label_germplasm:
    input:
        rna_type="results/chunks/rna_type/{chunk}.done",
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
    output:
        "results/chunks/germplasm/{chunk}.done",
    benchmark:
        benchmark("label_germplasm", f"{WINDOW_INDEX}-{{chunk}}")
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("germplasm", decision=True),
        samns=chunk_samns,
        runs=chunk_runs,
        prjnas=chunk_prjnas,
        categories=config["germplasm"]["categories"],
        attribute_keys=config["germplasm"]["attribute_keys"],
        rule_attribute_keys=config["germplasm"]["rule_attribute_keys"],
        natural_accessions=config["germplasm"]["natural_accessions"],
        inbred_values=config["germplasm"]["inbred_values"],
        hybrid_values=config["germplasm"]["hybrid_values"],
        patterns=config["germplasm"]["patterns"],
        descriptions=config["germplasm"]["descriptions"],
    script:
        "../scripts/label_germplasm.py"


rule label_exposure:
    input:
        rna_type=rna_chunks_for_exposure,
        biosample=exposure_chunk_biosamples,
        sra=exposure_chunk_sra,
        summary=exposure_chunk_summaries,
        index="results/peco/peco_index",
    output:
        "results/chunks/exposure/{echunk}.done",
    benchmark:
        benchmark("label_exposure", f"{WINDOW_INDEX}-{{echunk}}")
    conda:
        "../envs/peco_llm.yaml"
    params:
        **llm_rule_params("exposure"),
        samns=exposure_chunk_samns,
        runs=exposure_chunk_runs,
        prjnas=exposure_chunk_prjnas,
        top_k=config["peco"]["top_k"],
        embed_model=config["peco"]["embed_model"],
    script:
        "../scripts/label_exposure.py"


rule label_study_condition:
    input:
        rna_type="results/chunks/rna_type/{chunk}.done",
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
        index="results/peco/peco_index",
    output:
        "results/chunks/study_condition/{chunk}.done",
    benchmark:
        benchmark("label_study_condition", f"{WINDOW_INDEX}-{{chunk}}")
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("study", decision=True),
        samns=chunk_samns,
        runs=chunk_runs,
        prjnas=chunk_prjnas,
        paper_setting_map=config["paper"]["study_setting_map"],
    script:
        "../scripts/label_study_condition.py"


rule mixed_runs:
    input:
        samples=config["samples"],
        sra=expand("results/metadata/sra/{run}.json", run=RUNS),
    output:
        "results/mixed/{window}.json",
    benchmark:
        benchmark("mixed_runs", "{window}")
    conda:
        "../envs/aggregate.yaml"
    params:
        groups=window_run_groups(),
    script:
        "../scripts/mixed_runs.py"


rule sample_rows:
    input:
        rna_type="results/chunks/rna_type/{chunk}.done",
        tissue="results/chunks/tissue/{chunk}.done",
        germplasm="results/chunks/germplasm/{chunk}.done",
        study="results/chunks/study_condition/{chunk}.done",
        exposure=exposure_chunks_for_sample_rows,
        biosample=chunk_biosamples,
        summaries=chunk_summaries,
        index="results/peco/peco_index",
        mixed="results/mixed/{window}.json",
    output:
        "results/rows/{window}-{chunk}.tsv",
    benchmark:
        benchmark("sample_rows", "{window}-{chunk}")
    conda:
        "../envs/aggregate.yaml"
    params:
        samples=config["samples"],
        samns=chunk_samns,
        runs=chunk_runs,
        review=config["review"],
        tissue_keys=config["tissue"]["rule_attribute_keys"],
        germplasm_keys=config["germplasm"]["rule_attribute_keys"],
        growth_keys=config["metadata"]["growth_keys"],
    script:
        "../scripts/sample_rows.py"


rule aggregate:
    input:
        rows=expand(
            "results/rows/{window}-{chunk}.tsv",
            window=WINDOW_INDEX,
            chunk=CHUNK_IDS,
        ),
        index="results/peco/peco_index",
    output:
        labels=report(
            "results/labels.tsv",
            caption="../report/labels.rst",
            category="Labels",
        ),
        excluded="results/labels.excluded.tsv",
        coverage="results/metadata_coverage.tsv",
    benchmark:
        benchmark("aggregate")
    conda:
        "../envs/aggregate.yaml"
    params:
        samples=config["samples"],
    script:
        "../scripts/aggregate.py"
