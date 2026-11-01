rule summarize_paper:
    input:
        paper="resources/paper/{prjna}.json",
    output:
        "results/summary/{prjna}.json",
    log:
        "logs/summarize_{prjna}.log",
    conda:
        "../envs/llm.yaml"
    params:
        model=config["models"]["summary"],
        model_params=config["models"]["summary_params"],
        max_chars=config["paper"]["max_chars"],
        server_url=config["ollama"]["server_url"],
        api_key=config["ollama"]["api_key"],
    script:
        "../scripts/summarize_paper.py"
