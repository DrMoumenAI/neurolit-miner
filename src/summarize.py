"""
summarize.py
------------
NeuroLit Miner V3.1 — CLI entry point for evidence synthesis.

This file is intentionally thin. All provider logic lives in summarizer.py.
All database logic lives in database.py.
This file only: parses CLI args, fetches articles, computes corpus metadata,
calls the synthesizer, saves outputs.

V3.1 additions:
  --clinical_topic  filter by Axis 1 (e.g. glioblastoma, trauma)
  --method          filter by Axis 2 (e.g. ML_AI, retrospective_cohort)
  --domain          filter by Axis 3 (e.g. surgical_outcomes, diagnosis_biomarker)
  --min_confidence  filter by minimum confidence (HIGH, MEDIUM, LOW)

  Output header now includes:
    - clinical topic distribution of the corpus
    - method distribution
    - domain distribution
    - confidence breakdown

Backward compatible:
  --topic still works (legacy flat taxonomy)
  All V3 providers (mock, ollama, anthropic, openai, openrouter) unchanged
  All existing exports unchanged

Usage:
  python src/summarize.py --topic glioblastoma
  python src/summarize.py --clinical_topic glioblastoma --min_confidence HIGH
  python src/summarize.py --clinical_topic glioblastoma --method retrospective_cohort
  python src/summarize.py --domain surgical_outcomes --year_from 2020
  python src/summarize.py --keyword "machine learning" --year_from 2020
  python src/summarize.py --list_topics
  python src/summarize.py --list_taxonomy
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

def fetch_articles(topic=None, keyword=None, year_from=None, year_to=None,
                   clinical_topic=None, method=None, domain=None,
                   min_confidence=None, max_articles=20) -> list[dict]:
    """
    Fetch articles with combined V1–V3 and V3.1 filters.
    All parameters are optional and additive (AND logic).
    Returns new axis columns if they exist, empty strings if not.
    """
    if not os.path.exists(DB_PATH):
        print(f"\n[ERROR] Database not found at: {DB_PATH}")
        print("Run a PubMed search first:  python src/app.py")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check which columns exist — graceful degradation if DB not yet migrated
    cursor.execute("PRAGMA table_info(articles)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    has_v31 = "clinical_topic_tags" in existing_cols

    conditions, params = [], []

    # Legacy filter (V1–V3) — flat topics column
    if topic:
        conditions.append("topics LIKE ?")
        params.append(f"%{topic}%")

    # V3.1 axis filters — only applied if columns exist
    if has_v31:
        if clinical_topic:
            conditions.append("clinical_topic_tags LIKE ?")
            params.append(f"%{clinical_topic}%")
        if method:
            conditions.append("method_tags LIKE ?")
            params.append(f"%{method}%")
        if domain:
            conditions.append("domain_tags LIKE ?")
            params.append(f"%{domain}%")
        if min_confidence:
            # Confidence hierarchy: HIGH > MEDIUM > LOW > UNVERIFIED
            conf_map = {"HIGH": ["HIGH"],
                        "MEDIUM": ["HIGH", "MEDIUM"],
                        "LOW": ["HIGH", "MEDIUM", "LOW"]}
            allowed = conf_map.get(min_confidence.upper(), ["HIGH", "MEDIUM", "LOW"])
            placeholders = ",".join("?" * len(allowed))
            conditions.append(f"topic_confidence IN ({placeholders})")
            params.extend(allowed)

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

    # Select V3.1 columns if they exist, otherwise pad with empty strings
    if has_v31:
        select_cols = """pmid, title, authors, journal, year, abstract,
                         topics, mesh_terms, url,
                         clinical_topic_tags, method_tags, domain_tags,
                         topic_confidence"""
    else:
        select_cols = """pmid, title, authors, journal, year, abstract,
                         topics, mesh_terms, url"""

    cursor.execute(f"""
        SELECT {select_cols}
        FROM articles {where}
        ORDER BY CAST(year AS INTEGER) DESC
        LIMIT ?
    """, params + [min(max_articles, 50)])

    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        # Pad V3.1 fields for databases not yet migrated
        d.setdefault("clinical_topic_tags", "")
        d.setdefault("method_tags",         "")
        d.setdefault("domain_tags",         "")
        d.setdefault("topic_confidence",    "UNVERIFIED")
        rows.append(d)

    conn.close()
    return rows


def list_topics() -> list[tuple]:
    """List legacy flat topics (V1–V3 backward compatibility)."""
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
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


def list_taxonomy() -> dict:
    """List V3.1 three-axis taxonomy distribution from database."""
    if not os.path.exists(DB_PATH):
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check columns exist
    cursor.execute("PRAGMA table_info(articles)")
    cols = {row["name"] for row in cursor.fetchall()}
    if "clinical_topic_tags" not in cols:
        conn.close()
        return {}

    result = {}
    for axis, col in [("clinical_topic", "clinical_topic_tags"),
                      ("method",         "method_tags"),
                      ("domain",         "domain_tags")]:
        cursor.execute(f"SELECT {col} FROM articles WHERE {col} != ''")
        counts = Counter()
        for row in cursor.fetchall():
            for t in (row[col] or "").split("|"):
                t = t.strip()
                if t and t != "uncategorized":
                    counts[t] += 1
        result[axis] = counts.most_common()

    cursor.execute("""
        SELECT topic_confidence, COUNT(*) as n
        FROM articles GROUP BY topic_confidence
    """)
    result["confidence"] = {
        row["topic_confidence"]: row["n"] for row in cursor.fetchall()
    }
    conn.close()
    return result


# ── Corpus metadata ───────────────────────────────────────────────────────────

def compute_corpus_metadata(articles: list[dict]) -> dict:
    """
    Compute V3.1 taxonomy distributions for a fetched article set.
    Used to populate the synthesis output header and terminal display.

    Returns distributions for all three axes plus confidence breakdown,
    giving a corpus quality snapshot before the synthesis begins.
    """
    clinical_counts = Counter()
    method_counts   = Counter()
    domain_counts   = Counter()
    conf_counts     = Counter()

    for a in articles:
        for t in (a.get("clinical_topic_tags") or "").split("|"):
            t = t.strip()
            if t and t != "uncategorized":
                clinical_counts[t] += 1

        for t in (a.get("method_tags") or "").split("|"):
            t = t.strip()
            if t and t != "uncategorized":
                method_counts[t] += 1

        for t in (a.get("domain_tags") or "").split("|"):
            t = t.strip()
            if t and t != "uncategorized":
                domain_counts[t] += 1

        conf = a.get("topic_confidence") or "UNVERIFIED"
        conf_counts[conf] += 1

    n = len(articles)
    tagged = sum(v for k, v in conf_counts.items() if k != "UNVERIFIED")
    coverage = round(tagged / n * 100, 1) if n > 0 else 0.0

    return {
        "clinical_topic": clinical_counts.most_common(),
        "method":         method_counts.most_common(),
        "domain":         domain_counts.most_common(),
        "confidence":     dict(conf_counts),
        "taxonomy_coverage": coverage,
        "high_count":     conf_counts.get("HIGH", 0),
    }


def format_corpus_metadata_block(meta: dict, n: int) -> str:
    """
    Format corpus metadata as a markdown table block for the output header.
    Inserted between the header and the synthesis sections.
    """
    def axis_table(items, label):
        if not items:
            return f"*No {label} tags assigned.*\n"
        rows = "\n".join(
            f"| `{tag}` | {count} |"
            for tag, count in items[:8]
        )
        suffix = (f"\n| *...and {len(items)-8} more* | |"
                  if len(items) > 8 else "")
        return (f"| {label} Tag | Articles |\n"
                f"|---|---|\n"
                f"{rows}{suffix}\n")

    conf = meta["confidence"]
    high   = conf.get("HIGH",       0)
    medium = conf.get("MEDIUM",     0)
    low    = conf.get("LOW",        0)
    unverf = conf.get("UNVERIFIED", 0)
    coverage = meta["taxonomy_coverage"]

    block = (
        f"## Corpus Taxonomy Profile\n\n"
        f"*V3.1 three-axis classification · MeSH-first confidence scoring*\n\n"
        f"**Taxonomy coverage:** {coverage}% of {n} articles classified  \n"
        f"**Confidence breakdown:** "
        f"HIGH {high} · MEDIUM {medium} · LOW {low} · UNVERIFIED {unverf}\n\n"
        f"### Axis 1 — Clinical Topic\n\n"
        f"{axis_table(meta['clinical_topic'], 'Clinical Topic')}\n"
        f"### Axis 2 — Methodology\n\n"
        f"{axis_table(meta['method'], 'Method')}\n"
        f"### Axis 3 — Domain\n\n"
        f"{axis_table(meta['domain'], 'Domain')}\n"
        f"---\n\n"
    )
    return block


# ── Output writers ────────────────────────────────────────────────────────────

def build_full_markdown(summary: str, articles: list[dict],
                        filters: dict, provider: str,
                        timestamp: str, meta: dict) -> str:
    """
    Build the complete markdown document.
    V3.1: corpus taxonomy profile block inserted between header and synthesis.
    """
    n     = len(articles)
    years = sorted(set(
        a["year"] for a in articles if (a.get("year") or "").isdigit()
    ))
    yr  = f"{years[0]}–{years[-1]}" if len(years) > 1 else (
          years[0] if years else "N/A")

    # Build filter string — includes V3.1 axis filters
    fparts = []
    for k, v in filters.items():
        if v:
            fparts.append(f"**{k}:** {v}")
    fstr = " · ".join(fparts) if fparts else "All stored articles"

    disclaimer = (
        "keyword-frequency analysis in mock mode — not LLM-generated prose"
        if provider == "mock" else
        "AI-assisted narrative synthesis grounded in stored abstracts only"
    )

    header = (
        f"# NeuroLit Miner — Evidence Synthesis Report\n\n"
        f"**Generated:** {timestamp}  \n"
        f"**Tool:** NeuroLit Miner V3.1  \n"
        f"**Provider:** {provider}  \n"
        f"**Articles:** {n} (years {yr})  \n"
        f"**Filters:** {fstr}  \n\n"
        f"> ⚠️ **Disclaimer:** This is {disclaimer}. "
        f"It is **not** a formal systematic review and does not replace "
        f"full-text review, risk-of-bias assessment, PRISMA methodology, "
        f"or clinical judgment.\n\n---\n\n"
    )

    taxonomy_block = format_corpus_metadata_block(meta, n)

    footer = (
        f"\n\n---\n"
        f"*NeuroLit Miner V3.1 · "
        f"https://github.com/DrMoumenAI/neurolit-miner · "
        f"Provider: {provider}*\n"
    )

    # Structure: header → taxonomy profile → synthesis sections → footer
    return header + taxonomy_block + summary + footer


def save_outputs(markdown: str, articles: list[dict],
                 timestamp: str) -> dict:
    """Save markdown, plain text, and bibliography CSV. Unchanged from V3."""
    paths = {}

    md = os.path.join(RESULTS_DIR, f"neurolit_summary_{timestamp}.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(markdown)
    paths["markdown"] = md
    print(f"  ✓ Markdown : {md}")

    plain = re.sub(r"#{1,6}\s*",        "",    markdown)
    plain = re.sub(r"\*\*(.+?)\*\*",    r"\1", plain)
    plain = re.sub(r"\*(.+?)\*",        r"\1", plain)
    plain = re.sub(r"`(.+?)`",          r"\1", plain)
    plain = re.sub(r">\s*",             "",    plain)
    plain = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", plain)

    txt = os.path.join(RESULTS_DIR, f"neurolit_summary_{timestamp}.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write(plain)
    paths["text"] = txt
    print(f"  ✓ Text     : {txt}")

    # V3.1: bibliography includes new axis columns when present
    bib = os.path.join(RESULTS_DIR, f"neurolit_sources_{timestamp}.csv")
    fields = ["pmid", "title", "authors", "year", "journal",
              "mesh_terms", "clinical_topic_tags", "method_tags",
              "domain_tags", "topic_confidence", "url"]
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
        description="NeuroLit Miner V3.1 — Evidence Synthesis CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
V3 filters (legacy, still work):
  --topic glioblastoma
  --keyword "machine learning"

V3.1 filters (three-axis taxonomy):
  --clinical_topic glioblastoma
  --clinical_topic trauma --min_confidence HIGH
  --method retrospective_cohort
  --domain surgical_outcomes
  --clinical_topic glioblastoma --method ML_AI

Combined:
  --clinical_topic glioblastoma --domain oncologic_outcomes --year_from 2020

Examples:
  python src/summarize.py --clinical_topic glioblastoma
  python src/summarize.py --clinical_topic glioblastoma --min_confidence HIGH
  python src/summarize.py --clinical_topic trauma --method ML_AI
  python src/summarize.py --domain surgical_outcomes --year_from 2021
  python src/summarize.py --topic glioblastoma --provider ollama
  python src/summarize.py --list_taxonomy
  python src/summarize.py --list_providers
        """
    )

    # ── V1–V3 filters (preserved) ─────────────────────────────────────────
    parser.add_argument("--topic",        type=str, default=None,
                        help="Legacy flat topic filter (V1–V3 backward compat)")
    parser.add_argument("--keyword",      type=str, default=None,
                        help="Keyword search in title and abstract")
    parser.add_argument("--year_from",    type=int, default=None)
    parser.add_argument("--year_to",      type=int, default=None)
    parser.add_argument("--max_articles", type=int, default=20)
    parser.add_argument("--provider",     type=str, default=DEFAULT_PROVIDER,
                        choices=list(PROVIDER_REGISTRY.keys()))
    parser.add_argument("--ollama_model", type=str, default="llama3")

    # ── V3.1 filters (new) ────────────────────────────────────────────────
    parser.add_argument("--clinical_topic", type=str, default=None,
                        help="V3.1 Axis 1 filter: clinical topic "
                             "(e.g. glioblastoma, trauma, spine)")
    parser.add_argument("--method",         type=str, default=None,
                        help="V3.1 Axis 2 filter: methodology "
                             "(e.g. ML_AI, retrospective_cohort, randomized_trial)")
    parser.add_argument("--domain",         type=str, default=None,
                        help="V3.1 Axis 3 filter: clinical domain "
                             "(e.g. surgical_outcomes, diagnosis_biomarker)")
    parser.add_argument("--min_confidence", type=str, default=None,
                        choices=["HIGH", "MEDIUM", "LOW"],
                        help="V3.1 minimum confidence filter "
                             "(HIGH=MeSH-confirmed only, MEDIUM=title+MeSH, "
                             "LOW=any match)")

    # ── Discovery flags ───────────────────────────────────────────────────
    parser.add_argument("--list_topics",    action="store_true",
                        help="List legacy flat topics and counts")
    parser.add_argument("--list_taxonomy",  action="store_true",
                        help="V3.1: List three-axis taxonomy distributions")
    parser.add_argument("--list_providers", action="store_true",
                        help="List available LLM providers")

    args = parser.parse_args()

    # ── Discovery modes ───────────────────────────────────────────────────
    if args.list_providers:
        print(f"\nAvailable providers (default: {DEFAULT_PROVIDER}):\n")
        for name, desc in PROVIDER_DESCRIPTIONS.items():
            marker = " ← default" if name == DEFAULT_PROVIDER else ""
            print(f"  {name:<12}{marker}\n    {desc}\n")
        return

    if args.list_topics:
        print("\nLegacy flat topics (V1–V3):")
        for t, c in list_topics():
            print(f"  {t:<28} {c} articles")
        print()
        return

    if args.list_taxonomy:
        print("\nV3.1 Three-axis taxonomy distribution:\n")
        taxonomy = list_taxonomy()
        if not taxonomy:
            print("  V3.1 columns not found. Run: python src/main.py --backfill_taxonomy")
            return
        for axis in ["clinical_topic", "method", "domain"]:
            label = {"clinical_topic": "Axis 1 — Clinical Topic",
                     "method":         "Axis 2 — Methodology",
                     "domain":         "Axis 3 — Domain"}[axis]
            print(f"  {label}:")
            for tag, count in (taxonomy.get(axis) or []):
                print(f"    {tag:<30} {count} articles")
            print()
        if taxonomy.get("confidence"):
            print("  Confidence breakdown:")
            for level in ["HIGH", "MEDIUM", "LOW", "UNVERIFIED"]:
                c = taxonomy["confidence"].get(level, 0)
                print(f"    {level:<12} {c} articles")
        print()
        return

    # ── Synthesis mode ────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  NeuroLit Miner V3.1 — Evidence Synthesis")
    print(f"  Provider : {args.provider}")
    print("═" * 60)

    # Build complete filter dict — includes both V3 and V3.1 params
    filters = {
        "topic":          args.topic,
        "keyword":        args.keyword,
        "year_from":      args.year_from,
        "year_to":        args.year_to,
        "clinical_topic": args.clinical_topic,
        "method":         args.method,
        "domain":         args.domain,
        "min_confidence": args.min_confidence,
    }
    active_filters = {k: v for k, v in filters.items() if v}
    for k, v in active_filters.items():
        print(f"  {k:<16}: {v}")
    print(f"  {'max_articles':<16}: {args.max_articles}")

    if not active_filters:
        print("\n  ⚠️  No filters specified — fetching most recent articles.")

    # Fetch articles
    articles = fetch_articles(
        topic           = args.topic,
        keyword         = args.keyword,
        year_from       = args.year_from,
        year_to         = args.year_to,
        clinical_topic  = args.clinical_topic,
        method          = args.method,
        domain          = args.domain,
        min_confidence  = args.min_confidence,
        max_articles    = args.max_articles,
    )
    print(f"\n  Found {len(articles)} articles matching filters.")

    if len(articles) < MIN_ARTICLES_WARN:
        print(f"\n  ⚠️  Only {len(articles)} article(s) "
              f"(recommended minimum: {MIN_ARTICLES_WARN}).")
        if not articles:
            print("  No articles to synthesize. Exiting.")
            sys.exit(0)
        if input("  Continue? (y/n): ").strip().lower() != "y":
            sys.exit(0)

    # Compute and display corpus metadata
    meta = compute_corpus_metadata(articles)

    print(f"\n  Corpus taxonomy profile:")
    print(f"  {'Coverage':<20}: {meta['taxonomy_coverage']}% classified")
    print(f"  {'Confidence':<20}: "
          f"HIGH={meta['confidence'].get('HIGH',0)} · "
          f"MEDIUM={meta['confidence'].get('MEDIUM',0)} · "
          f"LOW={meta['confidence'].get('LOW',0)} · "
          f"UNVERIFIED={meta['confidence'].get('UNVERIFIED',0)}")

    if meta["clinical_topic"]:
        top3 = ", ".join(f"{t}({c})" for t, c in meta["clinical_topic"][:3])
        print(f"  {'Clinical topics':<20}: {top3}")
    if meta["method"]:
        top3 = ", ".join(f"{t}({c})" for t, c in meta["method"][:3])
        print(f"  {'Methods':<20}: {top3}")
    if meta["domain"]:
        top3 = ", ".join(f"{t}({c})" for t, c in meta["domain"][:3])
        print(f"  {'Domains':<20}: {top3}")

    # Warn on heterogeneous corpus
    if meta["clinical_topic"]:
        top_topic_count = meta["clinical_topic"][0][1]
        purity = top_topic_count / len(articles)
        if purity < 0.6:
            print(f"\n  ⚠️  Low corpus purity ({purity:.0%} dominant topic). "
                  f"Consider narrowing filters for higher synthesis quality.")

    # Article list
    print(f"\n  Articles:")
    print("  " + "─" * 56)
    for i, a in enumerate(articles, 1):
        t    = (a.get("title") or "")[:50]
        conf = a.get("topic_confidence", "?")[:1]  # H/M/L/U
        print(f"  [{i:>2}] [{conf}] ({a.get('year','?')}) {t}"
              + ("…" if len(a.get("title","")) > 50 else ""))
    print("  " + "─" * 56)
    print("       [H]=HIGH [M]=MEDIUM [L]=LOW [U]=UNVERIFIED confidence")

    # Run synthesis
    kwargs = {}
    if args.provider == "ollama":
        kwargs["model"] = args.ollama_model
    summarizer = get_summarizer(args.provider, **kwargs)

    print(f"\n  Running synthesis ({args.provider}) ...")
    summary = summarizer.summarize(articles, active_filters)

    # Save outputs
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_md   = build_full_markdown(summary, articles, active_filters,
                                    args.provider, timestamp, meta)
    print("\n  Saving outputs ...")
    paths = save_outputs(full_md, articles, timestamp)

    # Terminal preview
    preview = summary[:500]
    print("\n" + "─" * 60)
    print(preview + ("\n  ...[see full output in results/]"
                     if len(summary) > 500 else ""))
    print("\n" + "═" * 60)
    print(f"  Articles    : {len(articles)}")
    print(f"  Provider    : {args.provider}")
    print(f"  Coverage    : {meta['taxonomy_coverage']}% classified")
    print(f"  HIGH conf   : {meta['high_count']} articles")
    print(f"  Markdown    : {os.path.basename(paths['markdown'])}")
    print(f"  Text        : {os.path.basename(paths['text'])}")
    print(f"  Sources CSV : {os.path.basename(paths['csv'])}")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
