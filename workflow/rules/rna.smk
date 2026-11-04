rule classify_rna_type:
    input:
        biosample=biosample_file,
        sra=sra_file,
    output:
        "results/rna_type/{run}.json",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("rna_type", decision=True),
        accepted_rna_types=config["rna_type"]["accepted_rna_types"],
        attribute_keys=config["rna_type"]["attribute_keys"],
        min_confidence=config["rna_type"]["min_confidence"],
    script:
        "../scripts/classify_rna_type.py"
