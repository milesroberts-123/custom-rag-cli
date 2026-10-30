rule fetch_peco:
    output:
        "resources/peco.owl",
    log:
        "logs/fetch_peco.log",
    conda:
        "../envs/ncbi.yaml"
    params:
        url=config["peco"]["url"],
    shell:
        "curl -fsSL --retry 3 -o {output} '{params.url}'"


rule build_peco_index:
    input:
        "resources/peco.owl",
    output:
        directory("resources/peco_index"),
    log:
        "logs/build_peco_index.log",
    conda:
        "../envs/peco.yaml"
    params:
        embed_model=config["peco"]["embed_model"],
    script:
        "../scripts/build_peco_index.py"
