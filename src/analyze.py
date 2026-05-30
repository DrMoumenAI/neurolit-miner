"""
analyze.py
----------
NeuroLit Miner V2 — Research Analytics Layer.

Reads from the local SQLite database and produces:
  1. Publication trend by year            → trend_by_year.png + .csv
  2. Journal distribution                 → journal_distribution.png + .csv
  3. Topic distribution                   → topic_distribution.png + .csv
  4. MeSH term frequency                  → mesh_frequency.png + .csv
  5. MeSH co-occurrence matrix            → mesh_cooccurrence.png + .csv

All outputs saved to results/ directory.
No external APIs, no LLMs, no embeddings. Pure sqlite3 + matplotlib + csv.

Usage:
    python src/analyze.py                        # run all analyses
    python src/analyze.py --analysis trend       # run one only
    python src/analyze.py --topic glioblastoma   # filter by topic
    python src/analyze.py --year_from 2020       # filter by year
    python src/analyze.py --list                 # list available analyses

This is the foundation for Figure 1 of any NeuroLit Miner methods paper.
"""

import argparse
import csv
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from itertools import combinations
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow running as: python src/analyze.py
SRC_DIR     = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SRC_DIR)

DB_PATH      = os.path.join(PROJECT_DIR, "data",    "neurolit.db")
RESULTS_DIR  = os.path.join(PROJECT_DIR, "results")

os.makedirs(RESULTS_DIR, exist_ok=True)

# ── Matplotlib setup ──────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")   # non-interactive backend — works without a display
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Visual style ──────────────────────────────────────────────────────────────
# Matches NeuroLit Miner's dark surgical aesthetic
STYLE = {
    "bg":        "#080b0f",
    "surface":   "#0d1117",
    "border":    "#1e2a35",
    "accent":    "#00c9a7",
    "accent2":   "#0084ff",
    "amber":     "#fbbf24",
    "text":      "#c9d8e8",
    "dim":       "#5a7a94",
    "warn":      "#ff6b6b",
}

TOPIC_COLORS = [
    "#00c9a7", "#0084ff", "#fbbf24", "#f9a8d4", "#86efac",
    "#fca5a5", "#a78bfa", "#fb923c", "#34d399", "#e879f9",
    "#67e8f9", "#c4b5fd",
]

def _apply_dark_style(fig, ax):
    """Apply consistent dark theme to a figure."""
    fig.patch.set_facecolor(STYLE["bg"])
    ax.set_facecolor(STYLE["surface"])
    ax.tick_params(colors=STYLE["text"], labelsize=9)
    ax.xaxis.label.set_color(STYLE["text"])
    ax.yaxis.label.set_color(STYLE["text"])
    ax.title.set_color(STYLE["text"])
    for spine in ax.spines.values():
        spine.set_edgecolor(STYLE["border"])
    ax.grid(True, color=STYLE["border"], linewidth=0.5, alpha=0.7)
    ax.set_axisbelow(True)


def _save(fig, name: str, suffix: str = "") -> str:
    """Save figure to results/ and return the filepath."""
    fname    = f"{name}{suffix}.png"
    filepath = os.path.join(RESULTS_DIR, fname)
    fig.savefig(filepath, dpi=150, bbox_inches="tight",
                facecolor=STYLE["bg"], edgecolor="none")
    plt.close(fig)
    print(f"  ✓ Saved: {filepath}")
    return filepath


def _save_csv(rows: list[dict], name: str, suffix: str = "") -> str:
    """Save rows to a CSV file in results/."""
    if not rows:
        return ""
    fname    = f"{name}{suffix}.csv"
    filepath = os.path.join(RESULTS_DIR, fname)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ Saved: {filepath}")
    return filepath


def _get_db():
    """Open the SQLite database. Exits with a helpful message if not found."""
    if not os.path.exists(DB_PATH):
        print(f"\n[ERROR] Database not found at: {DB_PATH}")
        print("Run at least one PubMed search first to populate the database.")
        print("  python src/app.py   → search via web UI")
        print("  python src/main.py --query 'glioblastoma' --max 50")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_articles(topic_filter: str = None,
                    year_from: int = None,
                    year_to: int = None) -> list[dict]:
    """
    Fetch articles from SQLite with optional filters.
    Returns list of dicts with all columns.
    """
    conn   = _get_db()
    cursor = conn.cursor()

    conditions = []
    params     = []

    if topic_filter:
        conditions.append("topics LIKE ?")
        params.append(f"%{topic_filter}%")
    if year_from:
        conditions.append("CAST(year AS INTEGER) >= ?")
        params.append(year_from)
    if year_to:
        conditions.append("CAST(year AS INTEGER) <= ?")
        params.append(year_to)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    cursor.execute(f"""
        SELECT pmid, title, journal, year, topics, mesh_terms
        FROM articles
        {where}
        ORDER BY CAST(year AS INTEGER) ASC
    """, params)

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ── Analysis 1: Publication Trend by Year ─────────────────────────────────────

def analysis_trend(topic_filter=None, year_from=None, year_to=None,
                   suffix=""):
    """
    Publication count per year.
    Saves: trend_by_year.png + trend_by_year.csv

    Clinical relevance: shows whether a research area is growing, plateauing,
    or declining — essential framing for any systematic review introduction.
    """
    print("\n[1] Publication trend by year")

    articles = _fetch_articles(topic_filter, year_from, year_to)
    if not articles:
        print("  No articles found. Run a PubMed search first.")
        return

    year_counts = Counter()
    for a in articles:
        yr = str(a.get("year", "")).strip()
        if yr and yr != "N/A" and yr.isdigit():
            year_counts[yr] += 1

    if not year_counts:
        print("  No valid year data found.")
        return

    years  = sorted(year_counts.keys())
    counts = [year_counts[y] for y in years]

    fig, ax = plt.subplots(figsize=(10, 4))
    _apply_dark_style(fig, ax)

    bars = ax.bar(years, counts, color=STYLE["accent"], alpha=0.85,
                  width=0.6, zorder=3)

    # Annotate bar tops
    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                str(count), ha="center", va="bottom",
                color=STYLE["text"], fontsize=8)

    # Trend line
    if len(years) > 2:
        import numpy as np
        x_idx = list(range(len(years)))
        z     = np.polyfit(x_idx, counts, 1)
        p     = np.poly1d(z)
        ax.plot(years, p(x_idx), color=STYLE["warn"], linewidth=1.5,
                linestyle="--", alpha=0.7, label="Trend", zorder=4)
        ax.legend(facecolor=STYLE["surface"], edgecolor=STYLE["border"],
                  labelcolor=STYLE["text"], fontsize=8)

    topic_label = f" · Topic: {topic_filter}" if topic_filter else ""
    ax.set_title(f"NeuroLit Miner — Publication Trend by Year{topic_label}",
                 fontsize=11, pad=12, color=STYLE["text"])
    ax.set_xlabel("Publication Year", fontsize=9)
    ax.set_ylabel("Articles (n)", fontsize=9)
    ax.tick_params(axis="x", rotation=45)

    fig.text(0.99, 0.01, f"n={len(articles)} articles · NeuroLit Miner",
             ha="right", va="bottom", fontsize=7, color=STYLE["dim"])

    _save(fig, "trend_by_year", suffix)
    _save_csv([{"year": y, "count": year_counts[y]} for y in years],
              "trend_by_year", suffix)

    print(f"  Articles: {len(articles)} · Years: {years[0]}–{years[-1]}")


# ── Analysis 2: Journal Distribution ─────────────────────────────────────────

def analysis_journals(top_n=15, topic_filter=None, year_from=None,
                      year_to=None, suffix=""):
    """
    Top journals by article count.
    Saves: journal_distribution.png + journal_distribution.csv

    Clinical relevance: identifies the core journals for a field —
    essential for systematic review search strategy and submission targeting.
    """
    print("\n[2] Journal distribution")

    articles = _fetch_articles(topic_filter, year_from, year_to)
    if not articles:
        print("  No articles found.")
        return

    journal_counts = Counter()
    for a in articles:
        j = (a.get("journal") or "").strip()
        if j:
            journal_counts[j] += 1

    if not journal_counts:
        print("  No journal data found.")
        return

    top     = journal_counts.most_common(top_n)
    labels  = [t[0] for t in top]
    values  = [t[1] for t in top]

    # Truncate long journal names for display
    display_labels = [l[:45] + "…" if len(l) > 45 else l for l in labels]

    fig, ax = plt.subplots(figsize=(10, max(4, len(top) * 0.4)))
    _apply_dark_style(fig, ax)

    colors = [STYLE["accent2"]] + [STYLE["accent"]] * (len(top) - 1)
    bars   = ax.barh(display_labels[::-1], values[::-1],
                     color=colors[::-1], alpha=0.85, zorder=3)

    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", color=STYLE["text"], fontsize=8)

    topic_label = f" · Topic: {topic_filter}" if topic_filter else ""
    ax.set_title(f"NeuroLit Miner — Top {top_n} Journals{topic_label}",
                 fontsize=11, pad=12, color=STYLE["text"])
    ax.set_xlabel("Articles (n)", fontsize=9)

    fig.text(0.99, 0.01, f"n={len(articles)} articles",
             ha="right", va="bottom", fontsize=7, color=STYLE["dim"])

    _save(fig, "journal_distribution", suffix)
    _save_csv([{"journal": l, "count": c} for l, c in top],
              "journal_distribution", suffix)

    print(f"  Top journal: {top[0][0]} ({top[0][1]} articles)")


# ── Analysis 3: Topic Distribution ───────────────────────────────────────────

def analysis_topics(year_from=None, year_to=None, suffix=""):
    """
    Topic tag frequency across stored articles.
    Saves: topic_distribution.png + topic_distribution.csv

    Note: topic tags are keyword-based and approximate. MeSH frequency
    (analysis 4) is the authoritative complement.
    """
    print("\n[3] Topic distribution (keyword-based tags)")

    articles = _fetch_articles(year_from=year_from, year_to=year_to)
    if not articles:
        print("  No articles found.")
        return

    topic_counts = Counter()
    for a in articles:
        topics_str = (a.get("topics") or "").strip()
        if topics_str:
            for t in topics_str.split("|"):
                t = t.strip()
                if t and t != "uncategorized":
                    topic_counts[t] += 1

    if not topic_counts:
        print("  No topic data found.")
        return

    top    = topic_counts.most_common(12)
    labels = [t[0].replace("_", " ") for t in top]
    values = [t[1] for t in top]
    colors = TOPIC_COLORS[:len(top)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    fig.patch.set_facecolor(STYLE["bg"])

    # Bar chart
    _apply_dark_style(fig, ax1)
    bars = ax1.barh(labels[::-1], values[::-1], color=colors[::-1],
                    alpha=0.85, zorder=3)
    for bar, val in zip(bars, values[::-1]):
        ax1.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                 str(val), va="center", color=STYLE["text"], fontsize=8)
    ax1.set_title("Topic Distribution (bar)", fontsize=10,
                  color=STYLE["text"], pad=10)
    ax1.set_xlabel("Articles (n)", fontsize=9)

    # Pie chart
    ax2.set_facecolor(STYLE["bg"])
    wedges, texts, autotexts = ax2.pie(
        values, labels=None, colors=colors,
        autopct=lambda p: f"{p:.0f}%" if p > 4 else "",
        startangle=140, pctdistance=0.75,
        wedgeprops={"linewidth": 0.5, "edgecolor": STYLE["bg"]}
    )
    for at in autotexts:
        at.set_color(STYLE["bg"])
        at.set_fontsize(7)
    ax2.legend(wedges, labels, loc="lower center", bbox_to_anchor=(0.5, -0.15),
               ncol=2, fontsize=7, facecolor=STYLE["surface"],
               edgecolor=STYLE["border"], labelcolor=STYLE["text"])
    ax2.set_title("Topic Distribution (pie)", fontsize=10,
                  color=STYLE["text"], pad=10)

    fig.suptitle("NeuroLit Miner — Topic Distribution",
                 fontsize=12, color=STYLE["text"], y=1.01)
    fig.text(0.99, -0.02, f"n={len(articles)} articles · keyword-based tags (approximate)",
             ha="right", fontsize=7, color=STYLE["dim"])

    _save(fig, "topic_distribution", suffix)
    _save_csv([{"topic": t[0], "count": t[1]} for t in top],
              "topic_distribution", suffix)

    print(f"  {len(topic_counts)} topics found · top: {top[0][0]} ({top[0][1]})")


# ── Analysis 4: MeSH Term Frequency ──────────────────────────────────────────

def analysis_mesh_frequency(top_n=20, topic_filter=None,
                            year_from=None, year_to=None, suffix=""):
    """
    NLM MeSH term frequency across indexed articles.
    Saves: mesh_frequency.png + mesh_frequency.csv

    These are authoritative NLM-assigned subject headings — not keyword tags.
    High-frequency MeSH terms define the semantic landscape of a field.
    Clinical relevance: used to build systematic review search strategies
    and to identify MeSH terms for database queries.
    """
    print("\n[4] MeSH term frequency (NLM-assigned · authoritative)")

    articles = _fetch_articles(topic_filter, year_from, year_to)
    if not articles:
        print("  No articles found.")
        return

    mesh_counts   = Counter()
    indexed_count = 0

    for a in articles:
        mesh_str = (a.get("mesh_terms") or "").strip()
        if mesh_str:
            indexed_count += 1
            for term in mesh_str.split("|"):
                term = term.strip()
                if term:
                    mesh_counts[term] += 1

    if not mesh_counts:
        print("  No MeSH terms found. Articles may be too recent for NLM indexing.")
        print("  TODO V2.1: retry MeSH fetch for unindexed articles.")
        return

    top    = mesh_counts.most_common(top_n)
    labels = [t[0] for t in top]
    values = [t[1] for t in top]
    display_labels = [l[:40] + "…" if len(l) > 40 else l for l in labels]

    fig, ax = plt.subplots(figsize=(10, max(5, top_n * 0.38)))
    _apply_dark_style(fig, ax)

    bars = ax.barh(display_labels[::-1], values[::-1],
                   color=STYLE["amber"], alpha=0.8, zorder=3)
    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", color=STYLE["text"], fontsize=8)

    topic_label = f" · Topic: {topic_filter}" if topic_filter else ""
    ax.set_title(
        f"NeuroLit Miner — Top {top_n} MeSH Terms{topic_label}\n"
        f"NLM-assigned · {indexed_count}/{len(articles)} articles indexed",
        fontsize=10, pad=12, color=STYLE["text"]
    )
    ax.set_xlabel("Articles (n)", fontsize=9)

    fig.text(0.99, 0.01,
             "Source: NLM MeSH indexing via PubMed efetch XML",
             ha="right", va="bottom", fontsize=7, color=STYLE["dim"])

    _save(fig, "mesh_frequency", suffix)
    _save_csv([{"mesh_term": t[0], "count": t[1]} for t in top],
              "mesh_frequency", suffix)

    print(f"  {indexed_count}/{len(articles)} articles MeSH-indexed")
    print(f"  {len(mesh_counts)} unique MeSH terms found")
    print(f"  Top term: {top[0][0]} ({top[0][1]} articles)")


# ── Analysis 5: MeSH Co-occurrence ───────────────────────────────────────────

def analysis_mesh_cooccurrence(top_n=15, min_cooccurrence=2,
                               topic_filter=None, year_from=None,
                               year_to=None, suffix=""):
    """
    MeSH term co-occurrence — which terms appear together most frequently.
    Saves: mesh_cooccurrence.png + mesh_cooccurrence.csv

    Co-occurrence reveals the semantic structure of a field:
    which conditions, interventions, and outcomes are studied together.
    This is the foundation for topic graphs and evidence mapping.

    Example output:
      Glioblastoma + Machine Learning: 8 articles
      Glioblastoma + Prognosis: 12 articles
      Brain Neoplasms + Neurosurgical Procedures: 9 articles
    """
    print("\n[5] MeSH co-occurrence analysis")

    articles = _fetch_articles(topic_filter, year_from, year_to)
    if not articles:
        print("  No articles found.")
        return

    # Build co-occurrence counter
    cooccurrence = Counter()
    term_freq    = Counter()  # for filtering to top terms only

    for a in articles:
        mesh_str = (a.get("mesh_terms") or "").strip()
        if not mesh_str:
            continue
        terms = [t.strip() for t in mesh_str.split("|") if t.strip()]
        for term in terms:
            term_freq[term] += 1
        # Count all pairwise co-occurrences (sorted tuple = order-independent)
        for pair in combinations(sorted(set(terms)), 2):
            cooccurrence[pair] += 1

    if not cooccurrence:
        print("  Not enough MeSH-indexed articles for co-occurrence analysis.")
        print("  Run more PubMed searches to accumulate data.")
        return

    # Filter to top N most frequent terms to keep the matrix readable
    top_terms = {t for t, _ in term_freq.most_common(top_n)}

    # Filter pairs where both terms are in top_N
    filtered = {pair: count for pair, count in cooccurrence.items()
                if pair[0] in top_terms and pair[1] in top_terms
                and count >= min_cooccurrence}

    if not filtered:
        print(f"  No co-occurrences found with min_count >= {min_cooccurrence}.")
        print(f"  Try lowering --min_cooccurrence or running more searches.")
        return

    # Build matrix
    terms_list = sorted(top_terms)
    n          = len(terms_list)
    term_idx   = {t: i for i, t in enumerate(terms_list)}
    matrix     = [[0] * n for _ in range(n)]

    for (t1, t2), count in filtered.items():
        if t1 in term_idx and t2 in term_idx:
            i, j = term_idx[t1], term_idx[t2]
            matrix[i][j] = count
            matrix[j][i] = count

    # Truncate labels for display
    display_terms = [t[:25] + "…" if len(t) > 25 else t for t in terms_list]

    fig, ax = plt.subplots(figsize=(max(8, n * 0.55), max(7, n * 0.55)))
    fig.patch.set_facecolor(STYLE["bg"])
    ax.set_facecolor(STYLE["bg"])

    import numpy as np
    mat_array = np.array(matrix, dtype=float)
    # Mask zeros for cleaner display
    mat_array[mat_array == 0] = float("nan")

    im = ax.imshow(mat_array, cmap="YlOrBr", aspect="auto",
                   interpolation="nearest")

    # Annotate cells
    for i in range(n):
        for j in range(n):
            if matrix[i][j] > 0:
                ax.text(j, i, str(matrix[i][j]),
                        ha="center", va="center",
                        fontsize=7, color="#1a1a1a", fontweight="bold")

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(display_terms, rotation=45, ha="right", fontsize=7,
                       color=STYLE["text"])
    ax.set_yticklabels(display_terms, fontsize=7, color=STYLE["text"])

    cbar = fig.colorbar(im, ax=ax, shrink=0.6, pad=0.02)
    cbar.ax.tick_params(colors=STYLE["text"], labelsize=7)
    cbar.set_label("Co-occurrence count", color=STYLE["text"], fontsize=8)

    topic_label = f" · Topic: {topic_filter}" if topic_filter else ""
    ax.set_title(
        f"NeuroLit Miner — MeSH Co-occurrence Matrix{topic_label}\n"
        f"Top {n} terms · min co-occurrence: {min_cooccurrence}",
        fontsize=10, pad=12, color=STYLE["text"]
    )

    fig.text(0.99, 0.01, "NLM MeSH indexing · authoritative",
             ha="right", va="bottom", fontsize=7, color=STYLE["dim"])

    _save(fig, "mesh_cooccurrence", suffix)

    # Save CSV — sorted by count descending
    csv_rows = [{"term_1": p[0], "term_2": p[1], "cooccurrence": c}
                for p, c in sorted(filtered.items(),
                                   key=lambda x: x[1], reverse=True)]
    _save_csv(csv_rows, "mesh_cooccurrence", suffix)

    top_pairs = sorted(filtered.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"  {len(filtered)} co-occurring pairs found")
    print(f"  Top pairs:")
    for (t1, t2), c in top_pairs:
        print(f"    {t1} + {t2}: {c}")


# ── CLI ───────────────────────────────────────────────────────────────────────

ANALYSES = {
    "trend":         "Publication trend by year",
    "journals":      "Journal distribution",
    "topics":        "Topic distribution (keyword-based)",
    "mesh":          "MeSH term frequency (NLM-assigned)",
    "cooccurrence":  "MeSH co-occurrence matrix",
}


def main():
    parser = argparse.ArgumentParser(
        description="NeuroLit Miner V2 — Research Analytics Layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/analyze.py                              # run all analyses
  python src/analyze.py --analysis trend             # one analysis only
  python src/analyze.py --analysis mesh              # MeSH frequency
  python src/analyze.py --topic glioblastoma         # filter by topic
  python src/analyze.py --year_from 2020             # filter by year
  python src/analyze.py --top_n 10                  # fewer items per chart
  python src/analyze.py --list                       # list analyses
        """
    )

    parser.add_argument("--analysis",  type=str, default=None,
                        choices=list(ANALYSES.keys()),
                        help="Run one specific analysis (default: all)")
    parser.add_argument("--topic",     type=str, default=None,
                        help="Filter articles by topic tag (e.g. glioblastoma, AI_ML)")
    parser.add_argument("--year_from", type=int, default=None,
                        help="Filter articles from this year")
    parser.add_argument("--year_to",   type=int, default=None,
                        help="Filter articles to this year")
    parser.add_argument("--top_n",     type=int, default=15,
                        help="Number of items per chart (default: 15)")
    parser.add_argument("--min_cooccurrence", type=int, default=2,
                        help="Minimum co-occurrence count to display (default: 2)")
    parser.add_argument("--list",      action="store_true",
                        help="List available analyses and exit")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable analyses:")
        for key, desc in ANALYSES.items():
            print(f"  {key:<15} {desc}")
        print()
        return

    # Build filename suffix from filters
    suffix = ""
    if args.topic:     suffix += f"_{args.topic}"
    if args.year_from: suffix += f"_from{args.year_from}"
    if args.year_to:   suffix += f"_to{args.year_to}"

    print("\n" + "═" * 55)
    print("  NeuroLit Miner V2 — Research Analytics")
    print(f"  Database : {DB_PATH}")
    print(f"  Output   : {RESULTS_DIR}")
    if args.topic:     print(f"  Filter   : topic = {args.topic}")
    if args.year_from: print(f"  Filter   : year >= {args.year_from}")
    if args.year_to:   print(f"  Filter   : year <= {args.year_to}")
    print("═" * 55)

    # Check DB exists before running anything
    if not os.path.exists(DB_PATH):
        print(f"\n[ERROR] No database found at {DB_PATH}")
        print("Run a PubMed search first: python src/app.py")
        sys.exit(1)

    kw = dict(topic_filter=args.topic, year_from=args.year_from,
              year_to=args.year_to, suffix=suffix)

    if args.analysis == "trend" or args.analysis is None:
        analysis_trend(**kw)

    if args.analysis == "journals" or args.analysis is None:
        analysis_journals(top_n=args.top_n, **kw)

    if args.analysis == "topics" or args.analysis is None:
        analysis_topics(year_from=args.year_from, year_to=args.year_to,
                        suffix=suffix)

    if args.analysis == "mesh" or args.analysis is None:
        analysis_mesh_frequency(top_n=args.top_n, **kw)

    if args.analysis == "cooccurrence" or args.analysis is None:
        analysis_mesh_cooccurrence(
            top_n=args.top_n,
            min_cooccurrence=args.min_cooccurrence,
            **kw
        )

    print("\n" + "═" * 55)
    print(f"  Done. All outputs saved to: {RESULTS_DIR}")
    print("═" * 55 + "\n")


if __name__ == "__main__":
    main()
