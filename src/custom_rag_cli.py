#!/global/scratch/users/milesroberts/envs/ollama/bin/python
print("Importing modules...")
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.core.agent.workflow import AgentWorkflow
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
import asyncio
import os
import click

#async def search_documents(query: str) -> str:
#    """Useful for answering natural language questions about documents."""
#    response = await query_engine.aquery(query)
#    return str(response)

@click.command()
@click.option('--files', default="papers", help='Path to directory of files')
@click.option('--query', default="What is the main theme of the documents?", help='Prompt for lmm')
@click.option('--model', default="gemma3:1b", help='Model to run')
#def cli(files, query, model):
    #main(files, query, model)
    #asyncio.run(main(files, query))

# Now we can ask questions about the documents or do calculations
# https://developers.llamaindex.ai/python/framework/getting_started/starter_example_local/#adding-rag-capabilities
def main(files, query, model):
    # print params
    click.echo(f"Input parameters received:")
    click.echo(f"  files: {files}")
    click.echo(f"  query: {query}")
    click.echo(f"  model: {model}")
    click.echo("-" * 20)

    # Settings control global defaults
    print("Setting embeddings...")
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-base-en-v1.5")

    print("Setting llm...")
    Settings.llm = Ollama(
        model=model,
        request_timeout=600.0,
        # Manually set the context window to limit memory usage
        context_window=1024,
    )

    # Create a RAG tool using LlamaIndex
    print("Loading files...")
    documents = SimpleDirectoryReader(files).load_data()
    print("Creating vector store...")
    index = VectorStoreIndex.from_documents(documents)
    print("Creating query engine...")
    query_engine = index.as_query_engine(streaming=True)

    print("Generating response...")
    response = query_engine.query(query)
    response.print_response_stream()

# Run the agent
if __name__ == "__main__":
    #asyncio.run(main())
    main()
    #cli()
