"""
pubmed_api.py
-------------
NCBI E-utilities interface for NeuroLit Miner.

Uses the standard Entrez E-utilities API (no API key required for basic use;
set NCBI_API_KEY env variable for higher rate limits: 10 req/sec vs 3 req/sec).

E-utilities used:
  - esearch: retrieve PMIDs matching a query
  - efetch:  retrieve full records (XML) for a list of PMIDs

NCBI documentation: https://www.ncbi.nlm.nih.gov/books/NBK25499/
"""

import requests
import time
import os
from typing import Optional

# Base URL for all E-utilities calls
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Respect NCBI rate limits: 3 requests/sec without key, 10/sec with key
# We add a small sleep between calls to be a good API citizen
RATE_LIMIT_DELAY = 0.34  # seconds between requests (safe for no-key usage)

# Optional: set NCBI_API_KEY in your environment for higher throughput
API_KEY = os.environ.get("NCBI_API_KEY", None)


def search_pubmed(query: str, max_results: int = 50,
                  year_from: Optional[int] = None,
                  year_to: Optional[int] = None) -> list[str]:
    """
    Search PubMed and return a list of PMIDs.

    Args:
        query:       PubMed search string (supports MeSH terms and Boolean operators)
        max_results: maximum number of PMIDs to retrieve
        year_from:   filter results from this year (inclusive)
        year_to:     filter results to this year (inclusive)

    Returns:
        List of PMID strings

    Example:
        pmids = search_pubmed("glioblastoma machine learning", max_results=100)
    """
    # Build date range filter if specified
    # PubMed date filter format: YYYY/MM/DD[dp]
    date_filter = ""
    if year_from or year_to:
        start = f"{year_from}/01/01" if year_from else "1900/01/01"
        end   = f"{year_to}/12/31"   if year_to   else "3000/12/31"
        date_filter = f" AND ({start}[dp] : {end}[dp])"

    full_query = query + date_filter

    params = {
        "db":       "pubmed",
        "term":     full_query,
        "retmax":   max_results,
        "retmode":  "json",
        "sort":     "relevance",   # most relevant first
    }
    if API_KEY:
        params["api_key"] = API_KEY

    print(f"[PubMed] Searching: '{full_query}' (max {max_results} results)")

    try:
        response = requests.get(f"{EUTILS_BASE}/esearch.fcgi", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        pmids = data.get("esearchresult", {}).get("idlist", [])
        total = data.get("esearchresult", {}).get("count", "unknown")

        print(f"[PubMed] Found {total} total results. Retrieving {len(pmids)} PMIDs.")
        time.sleep(RATE_LIMIT_DELAY)
        return pmids

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] PubMed search failed: {e}")
        return []


def fetch_records(pmids: list[str], batch_size: int = 20) -> str:
    """
    Fetch full XML records for a list of PMIDs using efetch.
    Returns concatenated raw XML string.

    Args:
        pmids:      list of PMID strings from search_pubmed()
        batch_size: number of records per API call (NCBI recommends <= 200)

    Returns:
        Raw XML string containing all fetched records
    """
    if not pmids:
        return ""

    article_chunks = []   # we'll collect <PubmedArticle> blocks, not full documents
    total_batches = (len(pmids) + batch_size - 1) // batch_size

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        batch_num = (i // batch_size) + 1

        params = {
            "db":       "pubmed",
            "id":       ",".join(batch),
            "rettype":  "abstract",
            "retmode":  "xml",
        }
        if API_KEY:
            params["api_key"] = API_KEY

        print(f"[PubMed] Fetching batch {batch_num}/{total_batches} ({len(batch)} records)...")

        try:
            response = requests.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=30)
            response.raise_for_status()

            # Extract only <PubmedArticle> blocks — joining full XML documents
            # causes "junk after document element" due to repeated <?xml?> headers.
            import re
            chunks = re.findall(r'<PubmedArticle>.*?</PubmedArticle>', response.text, re.DOTALL)
            article_chunks.extend(chunks)
            time.sleep(RATE_LIMIT_DELAY)

        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Fetch batch {batch_num} failed: {e}")
            continue

    # Wrap all collected article blocks in one valid XML document
    combined = '<?xml version="1.0" ?>\n<PubmedArticleSet>\n'
    combined += "\n".join(article_chunks)
    combined += "\n</PubmedArticleSet>"
    return combined
