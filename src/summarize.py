"""
summarize.py
------------
NeuroLit Miner V3 — CLI entry point for evidence synthesis.

This file is intentionally thin. All provider logic lives in summarizer.py.
All database logic lives in database.py.
This file only: parses CLI args, fetches articles, calls the summarizer,
saves outputs.

Usage:
    python src/summarize.py --topic glioblastoma
    python src/summarize.py --keyword "machine learning" --year_from 2020
    python src/summarize.py --topic AI_ML --provider ollama
    python src/summarize.py --topic trauma --provider anthropic
    python src/summarize.py --list_topics
    python src/summarize.py --list_providers
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
SRC_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SRC_DIR)
sys.path.insert(0, SRC_DIR)

DB_PATH     = os.path.join(PROJECT_DIR, "data",    "neurolit.db")
RESULTS_DIR = os.path.join(PROJECT_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

from summarizer import (get_summarizer, PROVIDER_REGISTRY,
                        PROVIDER_DESCRIPTIONS, DEFAULT_PROVIDER,
                        MIN_ARTICLES_WARN)


# ── Database helpers ──────────────────────────────────────────────────────────

def fetch_articles(topic=None, keyword=None, year_from=None,
                   year_to=None, max_articles=20) -> list[dict]:
    if not os.path.exists(DB_PATH):
        print(f"\n[ERROR] Database not found at: {DB_PATH}")
        print("Run a PubMed search first:  python src/app.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions, params = [], []
    if topic:
        conditions.append("topics LIKE ?")
        params.append(f"%{topic}%")
    if keyword:
        conditions.append("(title LIKE ? OR abstract LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if year_from:
        conditions.append("CAST(year AS INTEGER) >= ?")
        params.append(year_from)
    if year_to:
        conditions.append("CAST(year AS INTEGER) <= ?")
        params.append(year_to)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    cursor.execute(f"""
        SELECT pmid, title, authors, journal, year, abstract,
               topics, mesh_terms, url
        FROM articles {where}
        ORDER BY CAST(year AS INTEGER) DESC
        LIMIT ?
    """, params + [min(max_articles, 50)])

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def list_topics() -> list[tuple]:
    if not os.path.exists(DB_PATH):
        return []
    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT topics FROM articles WHERE topics IS NOT NULL")
    counts = Counter()
    for row in cursor.fetchall():
        for t in (row["topics"] or "").split("|"):
            t = t.strip()
            if t and t != "uncategorized":
                counts[t] += 1
    conn.close()
    return counts.most_common()


# ── Output writers ────────────────────────────────────────────────────────────

def build_full_markdown(summary: str, articles: list[dict],
                        filters: dict, provider: str,
                        timestamp: str) -> str:
    n     = len(articles)
    years = sorted(set(
        a["year"] for a in articles if (a.get("year") or "").isdigit()
    ))
    yr    = f"{years[0]}–{years[-1]}" if len(years) > 1 else (
        years[0] if years else "N/A")
    fstr  = " · ".join(
        f"**{k}:** {v}" for k, v in filters.items() if v
    ) or "All stored articles"

    disclaimer = (
        "keyword-frequency analysis in mock mode — not LLM-generated prose"
        if provider == "mock" else
        "AI-assisted narrative synthesis grounded in stored abstracts only"
    )

    header = (
        f"# NeuroLit Miner — Evidence Synthesis Report\n\n"
        f"**Generated:** {timestamp}  \n"
        f"**Tool:** NeuroLit Miner V3  \n"
        f"**Provider:** {provider}  \n"
        f"**Articles:** {n} (years {yr})  \n"
        f"**Filters:** {fstr}  \n\n"
        f"> ⚠️ **Disclaimer:** This is {disclaimer}. "
        f"It is **not** a formal systematic review and does not replace "
        f"full-text review, risk-of-bias assessment, PRISMA methodology, "
        f"or clinical judgment.\n\n---\n\n"
    )
    footer = (
        f"\n\n---\n"
        f"*NeuroLit Miner V3 · "
        f"https://github.com/DrMoumenAI/neurolit-miner · "
        f"Provider: {provider}*\n"
    )
    return header + summary + footer


def save_outputs(markdown: str, articles: list[dict],
                 timestamp: str) -> dict:
    paths = {}

    # 1. Markdown
    md = os.path.join(RESULTS_DIR, f"neurolit_summary_{timestamp}.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(markdown)
    paths["markdown"] = md
    print(f"  ✓ Markdown : {md}")

    # 2. Plain text
    plain = re.sub(r"#{1,6}\s*", "",   markdown)
    plain = re.sub(r"\*\*(.+?)\*\*", r"\1", plain)
    plain = re.sub(r"\*(.+?)\*",     r"\1", plain)
    plain = re.sub(r"`(.+?)`",       r"\1", plain)
    plain = re.sub(r">\s*",          "",    plain)
    plain = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", plain)

    txt = os.path.join(RESULTS_DIR, f"neurolit_summary_{timestamp}.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(plain)
    paths["text"] = txt
    print(f"  ✓ Text     : {txt}")

    # 3. Bibliography CSV
    bib = os.path.join(RESULTS_DIR, f"neurolit_sources_{timestamp}.csv")
    fields = ["pmid","title","authors","year","journal","mesh_terms","url"]
    with open(bib, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(articles)
    paths["csv"] = bib
    print(f"  ✓ Sources  : {bib}")

    return paths


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NeuroLit Miner V3 — Evidence Synthesis CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/summarize.py --topic glioblastoma
  python src/summarize.py --keyword "machine learning" --year_from 2020
  python src/summarize.py --topic AI_ML --provider ollama
  python src/summarize.py --topic trauma --provider anthropic
  python src/summarize.py --list_topics
  python src/summarize.py --list_providers
        """
    )

    parser.add_argument("--topic",        type=str, default=None)
    parser.add_argument("--keyword",      type=str, default=None)
    parser.add_argument("--year_from",    type=int, default=None)
    parser.add_argument("--year_to",      type=int, default=None)
    parser.add_argument("--max_articles", type=int, default=20)
    parser.add_argument("--provider",     type=str, default=DEFAULT_PROVIDER,
                        choices=list(PROVIDER_REGISTRY.keys()))
    parser.add_argument("--ollama_model", type=str, default="llama3",
                        help="Ollama model name (default: llama3)")
    parser.add_argument("--list_topics",    action="store_true")
    parser.add_argument("--list_providers", action="store_true")

    args = parser.parse_args()

    if args.list_providers:
        print(f"\nAvailable providers (default: {DEFAULT_PROVIDER}):\n")
        for name, desc in PROVIDER_DESCRIPTIONS.items():
            marker = " ← default" if name == DEFAULT_PROVIDER else ""
            print(f"  {name:<12}{marker}\n    {desc}\n")
        return

    if args.list_topics:
        print("\nTopics in your database:")
        topics = list_topics()
        if not topics:
            print("  No articles found. Run a PubMed search first.")
        else:
            for t, c in topics:
                print(f"  {t:<25} {c} articles")
        print()
        return

    print("\n" + "═" * 58)
    print("  NeuroLit Miner V3 — Evidence Synthesis")
    print(f"  Provider : {args.provider}")
    print("═" * 58)

    filters = {
        "topic":     args.topic,
        "keyword":   args.keyword,
        "year_from": args.year_from,
        "year_to":   args.year_to,
    }
    for k, v in filters.items():
        if v:
            print(f"  {k:<10}: {v}")
    print(f"  {'max':<10}: {args.max_articles}")

    # Fetch
    articles = fetch_articles(
        topic=args.topic, keyword=args.keyword,
        year_from=args.year_from, year_to=args.year_to,
        max_articles=args.max_articles
    )
    print(f"\n  Found {len(articles)} articles.")

    if len(articles) < MIN_ARTICLES_WARN:
        print(f"\n  ⚠️  Only {len(articles)} article(s) "
              f"(recommended minimum: {MIN_ARTICLES_WARN}).")
        if not articles:
            print("  No articles to synthesize. Exiting.")
            sys.exit(0)
        if input("  Continue? (y/n): ").strip().lower() != "y":
            sys.exit(0)

    # Show article list
    print("\n  Articles:")
    print("  " + "─" * 54)
    for i, a in enumerate(articles, 1):
        t = (a.get("title") or "")[:52]
        print(f"  [{i:>2}] ({a.get('year','?')}) {t}"
              + ("…" if len(a.get("title","")) > 52 else ""))
    print("  " + "─" * 54)

    # Get summarizer and run
    kwargs = {}
    if args.provider == "ollama":
        kwargs["model"] = args.ollama_model
    summarizer = get_summarizer(args.provider, **kwargs)

    print(f"\n  Running synthesis ({args.provider}) ...")
    summary = summarizer.summarize(articles, filters)

    # Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_md   = build_full_markdown(summary, articles, filters,
                                    args.provider, timestamp)
    print("\n  Saving outputs ...")
    paths = save_outputs(full_md, articles, timestamp)

    # Preview
    preview = summary[:600]
    print("\n" + "─" * 58)
    print(preview + ("\n  ...[see full output in results/]"
                     if len(summary) > 600 else ""))
    print("\n" + "═" * 58)
    print(f"  Articles  : {len(articles)}")
    print(f"  Provider  : {args.provider}")
    print(f"  Markdown  : {os.path.basename(paths['markdown'])}")
    print(f"  Text      : {os.path.basename(paths['text'])}")
    print(f"  Sources   : {os.path.basename(paths['csv'])}")
    print("═" * 58 + "\n")


if __name__ == "__main__":
    main()
