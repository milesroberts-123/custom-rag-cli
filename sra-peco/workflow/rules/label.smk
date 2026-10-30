rule label_tissue:
    input:
        biosample=biosample_file,
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


rule label_peco:
    input:
        biosample=biosample_file,
        summary=summary_file,
        index="resources/peco_index",
    output:
        "results/peco/{run}.json",
    log:
        "logs/peco_{run}.log",
    conda:
        "../envs/peco_llm.yaml"
    params:
        top_k=config["peco"]["top_k"],
        embed_model=config["peco"]["embed_model"],
        model=config["models"]["peco"],
        model_params=config["models"]["peco_params"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/label_peco.py"


rule aggregate:
    input:
        tissue=expand("results/tissue/{run}.json", run=RUNS),
        peco=expand("results/peco/{run}.json", run=RUNS),
        summaries=expand("results/summary/{prjna}.json", prjna=PRJNAS),
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
