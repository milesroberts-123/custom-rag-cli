rule label_tissue:
    input:
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
    output:
        "results/tissue/{run}.json",
    log:
        "logs/tissue_{run}.log",
    conda:
        "../envs/llm.yaml"
    params:
        categories=config["tissue"]["categories"],
        keywords=config["tissue"]["keywords"],
        attribute_keys=config["tissue"]["attribute_keys"],
        other_description=config["tissue"]["other_description"],
        backend=config["models"]["tissue_backend"],
        model=config["models"]["tissue"],
        decision_model=config["models"]["tissue_decision"],
        model_params=config["models"]["tissue_params"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/label_tissue.py"


rule label_germplasm:
    input:
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
    output:
        "results/germplasm/{run}.json",
    log:
        "logs/germplasm_{run}.log",
    conda:
        "../envs/llm.yaml"
    params:
        categories=config["germplasm"]["categories"],
        attribute_keys=config["germplasm"]["attribute_keys"],
        natural_accessions=config["germplasm"]["natural_accessions"],
        patterns=config["germplasm"]["patterns"],
        descriptions=config["germplasm"]["descriptions"],
        other_description=config["germplasm"]["other_description"],
        backend=config["models"]["germplasm_backend"],
        model=config["models"]["germplasm"],
        decision_model=config["models"]["germplasm_decision"],
        model_params=config["models"]["germplasm_params"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/label_germplasm.py"


rule label_exposure:
    input:
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        index="resources/peco_index",
    output:
        "results/exposure/{run}.json",
    log:
        "logs/exposure_{run}.log",
    conda:
        "../envs/peco_llm.yaml"
    params:
        top_k=config["peco"]["top_k"],
        embed_model=config["peco"]["embed_model"],
        model=config["models"]["exposure"],
        model_params=config["models"]["exposure_params"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/label_exposure.py"


rule label_study_condition:
    input:
        biosample=biosample_file,
        sra=sra_file,
        summary=summary_file,
        index="resources/peco_index",
    output:
        "results/study_condition/{run}.json",
    log:
        "logs/study_condition_{run}.log",
    conda:
        "../envs/llm.yaml"
    params:
        backend=config["models"]["study_backend"],
        model=config["models"]["study"],
        decision_model=config["models"]["study_decision"],
        model_params=config["models"]["study_params"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/label_study_condition.py"


rule aggregate:
    input:
        tissue=expand("results/tissue/{run}.json", run=RUNS),
        germplasm=expand("results/germplasm/{run}.json", run=RUNS),
        exposure=expand("results/exposure/{run}.json", run=RUNS),
        study=expand("results/study_condition/{run}.json", run=RUNS),
        summaries=expand("results/summary/{prjna}.json", prjna=PRJNAS),
        index="resources/peco_index",
    output:
        report(
            "results/labels.tsv",
            caption="../report/labels.rst",
            category="Labels",
        ),
    log:
        "logs/aggregate.log",
    conda:
        "../envs/aggregate.yaml"
    params:
        samples=config["samples"],
        review=config["review"],
    script:
        "../scripts/aggregate.py"
