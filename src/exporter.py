"""
exporter.py
-----------
Export article records to CSV for use in systematic reviews,
reference managers (Zotero, Mendeley), or spreadsheet analysis.

CSV columns match standard reference manager import formats.
"""

import csv
import os
from datetime import datetime
from typing import Optional


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")


def export_to_csv(articles: list[dict],
                  filename: Optional[str] = None,
                  output_dir: str = RESULTS_DIR) -> str:
    """
    Export a list of article dicts to a CSV file.

    Args:
        articles:   list of dicts from database.query_articles()
        filename:   custom filename (auto-generated if None)
        output_dir: directory to write the file

    Returns:
        Absolute path to the written CSV file
    """
    if not articles:
        print("[Export] No articles to export.")
        return ""

    os.makedirs(output_dir, exist_ok=True)

    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"neurolit_export_{timestamp}.csv"

    filepath = os.path.join(output_dir, filename)

    # Standard fieldnames — maps to most reference managers
    fieldnames = ["pmid", "title", "authors", "journal", "year",
              "abstract", "topics", "mesh_terms", "doi", "url"]

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(articles)

    print(f"[Export] {len(articles)} articles exported to: {os.path.abspath(filepath)}")
    return os.path.abspath(filepath)


def print_summary_table(articles: list[dict], max_rows: int = 20) -> None:
    """
    Print a formatted summary table to the terminal.
    Truncates long titles for readability.
    """
    if not articles:
        print("No articles found.")
        return

    print("\n" + "─" * 100)
    print(f"{'PMID':<12} {'Year':<6} {'Topics':<25} {'Title':<55}")
    print("─" * 100)

    for i, a in enumerate(articles[:max_rows]):
        pmid    = str(a.get("pmid", ""))[:10]
        year    = str(a.get("year", ""))[:5]
        topics  = str(a.get("topics", ""))[:23]
        title   = str(a.get("title", ""))[:53]
        if len(a.get("title", "")) > 53:
            title = title[:50] + "..."
        print(f"{pmid:<12} {year:<6} {topics:<25} {title:<55}")

    if len(articles) > max_rows:
        print(f"\n  ... and {len(articles) - max_rows} more articles.")

    print("─" * 100)
    print(f"Total: {len(articles)} articles\n")
