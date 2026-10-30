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
        max_retries=config["ncbi"]["max_retries"],
    script:
        "../scripts/fetch_paper.py"
