# Label rules process runs in chunks (`label_chunk_size` runs per job) so the
# interpreter and model payloads load once per chunk. Snakemake cannot list
# per-run outputs on a multi-run job, so each chunk declares one marker file;
# the script writes the per-run JSONs beside it, and downstream rules depend
# on the markers. The per-run files stay the aggregation/review contract.


rule label_tissue:
    input:
        rna_type=chunk_rna_types,
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
    output:
        "results/chunks/tissue/{chunk}.done",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("tissue", decision=True),
        runs=chunk_runs,
        samns=chunk_samns,
        prjnas=chunk_prjnas,
        categories=config["tissue"]["categories"],
        keywords=config["tissue"]["keywords"],
        attribute_keys=config["tissue"]["attribute_keys"],
        other_description=config["tissue"]["other_description"],
    script:
        "../scripts/label_tissue.py"


rule label_germplasm:
    input:
        rna_type=chunk_rna_types,
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
    output:
        "results/chunks/germplasm/{chunk}.done",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("germplasm", decision=True),
        runs=chunk_runs,
        samns=chunk_samns,
        prjnas=chunk_prjnas,
        categories=config["germplasm"]["categories"],
        attribute_keys=config["germplasm"]["attribute_keys"],
        natural_accessions=config["germplasm"]["natural_accessions"],
        patterns=config["germplasm"]["patterns"],
        descriptions=config["germplasm"]["descriptions"],
    script:
        "../scripts/label_germplasm.py"


rule label_exposure:
    input:
        rna_type=chunk_rna_types,
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
        index="results/peco/peco_index",
    output:
        "results/chunks/exposure/{chunk}.done",
    conda:
        "../envs/peco_llm.yaml"
    params:
        **llm_rule_params("exposure"),
        runs=chunk_runs,
        samns=chunk_samns,
        prjnas=chunk_prjnas,
        top_k=config["peco"]["top_k"],
        embed_model=config["peco"]["embed_model"],
    script:
        "../scripts/label_exposure.py"


rule label_study_condition:
    input:
        rna_type=chunk_rna_types,
        biosample=chunk_biosamples,
        sra=chunk_sra,
        summary=chunk_summaries,
        index="results/peco/peco_index",
    output:
        "results/chunks/study_condition/{chunk}.done",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("study", decision=True),
        runs=chunk_runs,
        samns=chunk_samns,
        prjnas=chunk_prjnas,
    script:
        "../scripts/label_study_condition.py"


rule aggregate:
    input:
        rna_type=expand("results/rna_type/{run}.json", run=RUNS),
        tissue=expand("results/chunks/tissue/{chunk}.done", chunk=CHUNK_IDS),
        germplasm=expand("results/chunks/germplasm/{chunk}.done", chunk=CHUNK_IDS),
        exposure=expand("results/chunks/exposure/{chunk}.done", chunk=CHUNK_IDS),
        study=expand("results/chunks/study_condition/{chunk}.done", chunk=CHUNK_IDS),
        athrdb=expand("results/metadata/athrdb/{run}.json", run=RUNS),
        summaries=expand("results/summary/{prjna}.json", prjna=PRJNAS),
        index="results/peco/peco_index",
    output:
        labels=report(
            "results/labels.tsv",
            caption="../report/labels.rst",
            category="Labels",
        ),
        excluded="results/labels.excluded.tsv",
    conda:
        "../envs/aggregate.yaml"
    params:
        samples=config["samples"],
        review=config["review"],
    script:
        "../scripts/aggregate.py"
