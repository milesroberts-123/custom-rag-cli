rule fetch_peco:
    output:
        "results/peco/peco.owl",
    conda:
        "../envs/ncbi.yaml"
    params:
        url=config["peco"]["url"],
    shell:
        "curl -fsSL --retry 3 -o {output} '{params.url}'"


rule build_peco_index:
    input:
        "results/peco/peco.owl",
    output:
        directory("results/peco/peco_index"),
    conda:
        "../envs/peco.yaml"
    params:
        embed_model=config["peco"]["embed_model"],
        exposure_branch=config["peco"]["exposure_branch"],
        study_branch=config["peco"]["study_branch"],
        growth_system_root=config["peco"]["growth_system_root"],
        growth_system_extra_roots=config["peco"]["growth_system_extra_roots"],
    script:
        "../scripts/build_peco_index.py"
