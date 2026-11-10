rule fetch_biosamples:
    input:
        samples=config["samples"],
    output:
        expand("results/metadata/biosample/{samn}.json", samn=SAMNS),
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
        expand("results/metadata/sra/{run}.json", run=RUNS),
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
        sra=expand("results/metadata/sra/{run}.json", run=RUNS),
    output:
        expand("results/metadata/athrdb/{run}.json", run=RUNS),
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
        expand("results/metadata/paper/{prjna}.json", prjna=PRJNAS),
    conda:
        "../envs/ncbi.yaml"
    params:
        prjnas=PRJNAS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        discover_by_accession=config["paper"]["discover_by_accession"],
        max_pmids=config["paper"]["max_pmids"],
    script:
        "../scripts/fetch_paper.py"


rule fetch_bioprojects:
    input:
        samples=config["samples"],
    output:
        expand("results/metadata/bioproject/{prjna}.json", prjna=PRJNAS),
    conda:
        "../envs/ncbi.yaml"
    params:
        prjnas=PRJNAS,
        email=config["ncbi"]["email"],
        api_key_env=config["ncbi"]["api_key_env"],
        max_retries=config["ncbi"]["max_retries"],
    script:
        "../scripts/fetch_bioproject.py"
