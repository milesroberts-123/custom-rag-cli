rule label_tissue:
    input:
        rna_type=rna_type_file,
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        athrdb=athrdb_file,
    output:
        "results/tissue/{run}.json",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("tissue", decision=True),
        categories=config["tissue"]["categories"],
        keywords=config["tissue"]["keywords"],
        attribute_keys=config["tissue"]["attribute_keys"],
        other_description=config["tissue"]["other_description"],
    script:
        "../scripts/label_tissue.py"


rule label_germplasm:
    input:
        rna_type=rna_type_file,
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        athrdb=athrdb_file,
    output:
        "results/germplasm/{run}.json",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("germplasm", decision=True),
        categories=config["germplasm"]["categories"],
        attribute_keys=config["germplasm"]["attribute_keys"],
        natural_accessions=config["germplasm"]["natural_accessions"],
        patterns=config["germplasm"]["patterns"],
        descriptions=config["germplasm"]["descriptions"],
    script:
        "../scripts/label_germplasm.py"


rule label_exposure:
    input:
        rna_type=rna_type_file,
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        index="results/peco/peco_index",
    output:
        "results/exposure/{run}.json",
    conda:
        "../envs/peco_llm.yaml"
    params:
        **llm_rule_params("exposure"),
        top_k=config["peco"]["top_k"],
        embed_model=config["peco"]["embed_model"],
    script:
        "../scripts/label_exposure.py"


rule label_study_condition:
    input:
        rna_type=rna_type_file,
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        index="results/peco/peco_index",
    output:
        "results/study_condition/{run}.json",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("study", decision=True),
    script:
        "../scripts/label_study_condition.py"


rule aggregate:
    input:
        rna_type=expand("results/rna_type/{run}.json", run=RUNS),
        tissue=expand("results/tissue/{run}.json", run=RUNS),
        germplasm=expand("results/germplasm/{run}.json", run=RUNS),
        exposure=expand("results/exposure/{run}.json", run=RUNS),
        study=expand("results/study_condition/{run}.json", run=RUNS),
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
