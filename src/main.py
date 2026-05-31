"""
main.py
-------
NeuroLit Miner — CLI entry point.

Usage examples:
    python src/main.py --query "glioblastoma machine learning" --max 50
    python src/main.py --query "AI neurosurgery" --max 100 --year_from 2020
    python src/main.py --query "global neurosurgery workforce" --max 30 --export
    python src/main.py --search_db --topic AI_ML --year_from 2021
    python src/main.py --stats
"""

import argparse
import sys
import os

# Allow running from project root: python src/main.py
sys.path.insert(0, os.path.dirname(__file__))

from pubmed_api import search_pubmed, fetch_records
from parser     import parse_xml
from database   import (initialize_db, insert_articles, log_search,
                         query_articles, get_stats, backfill_taxonomy)
from exporter   import export_to_csv, print_summary_table


def run_search(args):
    """Full pipeline: search PubMed → fetch XML → parse → store → optionally export."""

    # 1. Initialize database (creates tables if first run)
    initialize_db()

    # 2. Search PubMed for PMIDs
    pmids = search_pubmed(
        query      = args.query,
        max_results= args.max,
        year_from  = args.year_from,
        year_to    = args.year_to,
    )

    if not pmids:
        print("[Main] No results found. Try a different query.")
        return

    # 3. Fetch full XML records
    xml_data = fetch_records(pmids)

    # 4. Parse XML → list of dicts
    articles = parse_xml(xml_data)

    if not articles:
        print("[Main] Parsing returned no articles. Check XML response.")
        return

    # 5. Store in SQLite (deduplicates automatically)
    inserted = insert_articles(articles)

    # 6. Log this search for reproducibility
    log_search(
        query        = args.query,
        max_results  = args.max,
        year_from    = args.year_from,
        year_to      = args.year_to,
        results_count= inserted,
    )

    # 7. Display summary table
    print_summary_table(articles)

    # 8. Optionally export to CSV
    if args.export:
        export_to_csv(articles)


def run_db_search(args):
    """Query already-stored articles in the local database."""
    initialize_db()

    results = query_articles(
        topic     = args.topic,
        year_from = args.year_from,
        year_to   = args.year_to,
        keyword   = args.keyword,
    )

    print_summary_table(results)

    if args.export:
        export_to_csv(results)


def run_stats(args):
    """Print database statistics."""
    initialize_db()
    stats = get_stats()

    print("\n" + "═" * 50)
    print("  NEUROLIT MINER — DATABASE STATISTICS")
    print("═" * 50)
    print(f"  Total articles stored : {stats['total_articles']}")
    print(f"  Total searches run    : {stats['total_searches']}")

    if stats.get("articles_by_year"):
        print("\n  Articles by year (recent 10):")
        for year, count in stats["articles_by_year"].items():
            bar = "█" * min(count, 40)
            print(f"    {year:>5}  {bar} {count}")

    if stats.get("topic_distribution"):
        print("\n  Topic distribution:")
        for topic, count in list(stats["topic_distribution"].items())[:10]:
            bar = "█" * min(count, 30)
            print(f"    {topic:<25}  {bar} {count}")

    print("═" * 50 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="NeuroLit Miner — Automated neurosurgical literature surveillance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py --query "glioblastoma machine learning" --max 50
  python src/main.py --query "AI neurosurgery" --max 100 --year_from 2020 --export
  python src/main.py --search_db --topic AI_ML --year_from 2021
  python src/main.py --stats
        """
    )

    # ── Mutually exclusive modes ──────────────────────────────────────────
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--search_db", action="store_true",
                      help="Search already-stored articles (no PubMed call)")
    mode.add_argument("--stats",     action="store_true",
                      help="Show database statistics")

    # ── PubMed search args ────────────────────────────────────────────────
    parser.add_argument("--query",     type=str,  default=None,
                        help="PubMed search query string")
    parser.add_argument("--max",       type=int,  default=50,
                        help="Maximum results to retrieve (default: 50)")
    parser.add_argument("--year_from", type=int,  default=None,
                        help="Filter results from this year (e.g. 2020)")
    parser.add_argument("--year_to",   type=int,  default=None,
                        help="Filter results to this year (e.g. 2024)")

    # ── DB search / export args ───────────────────────────────────────────
    parser.add_argument("--topic",   type=str, default=None,
                        help="Filter stored articles by topic tag (e.g. AI_ML, glioblastoma)")
    parser.add_argument("--keyword", type=str, default=None,
                        help="Search title/abstract in stored articles")
    parser.add_argument("--export",  action="store_true",
                        help="Export results to CSV in results/")

    # ── V3.1 taxonomy backfill ────────────────────────────────────────────
    parser.add_argument("--backfill_taxonomy", action="store_true",
                        help="V3.1: Re-tag UNVERIFIED articles with "
                             "three-axis taxonomy and confidence scores")
    parser.add_argument("--force_backfill", action="store_true",
                        help="V3.1: Force re-tag ALL articles (including "
                             "already-tagged ones)")

    args = parser.parse_args()

    # ── Route to correct handler ──────────────────────────────────────────
    if args.backfill_taxonomy or args.force_backfill:
        initialize_db()
        backfill_taxonomy(force=args.force_backfill)
    elif args.stats:
        run_stats(args)
    elif args.search_db:
        run_db_search(args)
    elif args.query:
        run_search(args)
    else:
        parser.print_help()
        print("\n[Main] No action specified. Use --query, --search_db, or --stats.")


if __name__ == "__main__":
    main()
