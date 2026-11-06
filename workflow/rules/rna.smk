rule classify_rna_type:
    input:
        biosample=chunk_biosamples,
        sra=chunk_sra,
    output:
        "results/chunks/rna_type/{chunk}.done",
    conda:
        "../envs/llm.yaml"
    params:
        **llm_rule_params("rna_type", decision=True),
        runs=chunk_runs,
        samns=chunk_samns,
        accepted_rna_types=config["rna_type"]["accepted_rna_types"],
        attribute_keys=config["rna_type"]["attribute_keys"],
        min_confidence=config["rna_type"]["min_confidence"],
    script:
        "../scripts/classify_rna_type.py"
