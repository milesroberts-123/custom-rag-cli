#!/global/home/users/milesroberts/.local/share/mamba/envs/pypaperretriver/bin/python
from pypaperretriever import PubMedSearcher

search_query = """("k-mer"[Title/Abstract] OR "kmer"[Title/Abstract])"""

searcher = PubMedSearcher(search_string=search_query, email="milesroberts@berkeley.edu")

results = searcher.search(
    count=50,
    order_by='chronological',  # or 'chronological'
    only_open_access=True,
    only_case_reports=False
)

# Download found articles
searcher.download_articles(download_directory='PDFs', allow_scihub=False)

# Extract images from downloaded articles
searcher.extract_images()
