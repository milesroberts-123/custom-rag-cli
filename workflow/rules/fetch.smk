rule fetch_biosamples:
    input:
        samples=config["samples"],
    output:
        expand("resources/biosample/{samn}.json", samn=SAMNS),
    log:
        "logs/fetch_biosamples.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        samns=SAMNS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        batch_size=config["ncbi"]["batch_size"],
        max_retries=config["ncbi"]["max_retries"],
    script:
        "../scripts/fetch_biosample.py"


rule fetch_sra_metadata:
    input:
        samples=config["samples"],
    output:
        expand("resources/sra/{run}.json", run=RUNS),
    log:
        "logs/fetch_sra_metadata.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        runs=RUNS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        batch_size=config["ncbi"]["sra_batch_size"],
        max_retries=config["ncbi"]["max_retries"],
    script:
        "../scripts/fetch_sra_metadata.py"


rule fetch_athrdb:
    input:
        samples=config["samples"],
        sra=expand("resources/sra/{run}.json", run=RUNS),
    output:
        expand("resources/athrdb/{run}.json", run=RUNS),
    log:
        "logs/fetch_athrdb.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        runs=RUNS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        max_retries=config["ncbi"]["max_retries"],
        athrdb=config["athrdb"],
    script:
        "../scripts/fetch_athrdb.py"


rule fetch_papers:
    input:
        samples=config["samples"],
    output:
        expand("resources/paper/{prjna}.json", prjna=PRJNAS),
    log:
        "logs/fetch_papers.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        prjnas=PRJNAS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
    script:
        "../scripts/fetch_paper.py"


rule fetch_bioprojects:
    input:
        samples=config["samples"],
    output:
        expand("resources/bioproject/{prjna}.json", prjna=PRJNAS),
    log:
        "logs/fetch_bioprojects.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        prjnas=PRJNAS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        max_retries=config["ncbi"]["max_retries"],
    script:
        "../scripts/fetch_bioproject.py"
