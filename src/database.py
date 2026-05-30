"""
database.py
-----------
SQLite operations for NeuroLit Miner.

Schema:
  articles table — one row per unique article (deduplicated by PMID)
  searches table  — log of all queries run (for reproducibility)

Design note: storing topics as pipe-separated string keeps the schema simple
at V1. In V2 we can normalize to a topics join table.
"""

import sqlite3
import os
from datetime import datetime
from typing import Optional


# Default database path (relative to project root)
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "neurolit.db")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and return a connection.
    Enables WAL mode for safer concurrent access.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row   # rows accessible as dicts
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Create tables if they don't exist.
    Safe to call on every run — uses IF NOT EXISTS.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid        TEXT    UNIQUE NOT NULL,
            title       TEXT,
            authors     TEXT,
            journal     TEXT,
            year        TEXT,
            abstract    TEXT,
            topics      TEXT,       -- pipe-separated topic tags
            doi         TEXT,
            url         TEXT,
            date_added  TEXT        -- ISO timestamp when we stored it
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT,
            max_results INTEGER,
            year_from   TEXT,
            year_to     TEXT,
            results_count INTEGER,
            timestamp   TEXT
        )
    """)

    # Index on year and topics for fast filtering
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_year   ON articles(year)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_topics ON articles(topics)")

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at: {os.path.abspath(db_path)}")


def insert_articles(articles: list[dict], db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Insert a list of article dicts into the database.
    Skips duplicates (same PMID) silently using INSERT OR IGNORE.

    Returns:
        Number of new articles actually inserted (duplicates excluded)
    """
    if not articles:
        return 0

    conn = get_connection(db_path)
    cursor = conn.cursor()

    timestamp = datetime.utcnow().isoformat()
    inserted = 0

    for article in articles:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO articles
                    (pmid, title, authors, journal, year, abstract, topics, doi, url, date_added)
                VALUES
                    (:pmid, :title, :authors, :journal, :year, :abstract, :topics, :doi, :url, :date_added)
            """, {**article, "date_added": timestamp})

            if cursor.rowcount > 0:
                inserted += 1

        except sqlite3.Error as e:
            print(f"[WARNING] DB insert error for PMID {article.get('pmid', '?')}: {e}")

    conn.commit()
    conn.close()

    duplicates = len(articles) - inserted
    print(f"[DB] Inserted {inserted} new articles. ({duplicates} duplicates skipped)")
    return inserted


def log_search(query: str, max_results: int, year_from: Optional[int],
               year_to: Optional[int], results_count: int,
               db_path: str = DEFAULT_DB_PATH) -> None:
    """Log a search query for reproducibility tracking."""
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO searches (query, max_results, year_from, year_to, results_count, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (query, max_results, str(year_from or ""), str(year_to or ""),
          results_count, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def query_articles(topic: Optional[str] = None,
                   year_from: Optional[int] = None,
                   year_to: Optional[int] = None,
                   keyword: Optional[str] = None,
                   db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """
    Query stored articles with optional filters.

    Args:
        topic:     filter by topic tag (partial match, e.g. "AI_ML")
        year_from: minimum publication year
        year_to:   maximum publication year
        keyword:   search title and abstract for this term

    Returns:
        List of article dicts ordered by year descending
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    conditions = []
    params = []

    if topic:
        conditions.append("topics LIKE ?")
        params.append(f"%{topic}%")

    if year_from:
        conditions.append("CAST(year AS INTEGER) >= ?")
        params.append(year_from)

    if year_to:
        conditions.append("CAST(year AS INTEGER) <= ?")
        params.append(year_to)

    if keyword:
        conditions.append("(title LIKE ? OR abstract LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    cursor.execute(f"""
        SELECT pmid, title, authors, journal, year, abstract, topics, doi, url
        FROM articles
        {where_clause}
        ORDER BY CAST(year AS INTEGER) DESC
    """, params)

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    print(f"[DB] Query returned {len(rows)} articles.")
    return rows


def get_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Return summary statistics for the database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    stats = {}

    cursor.execute("SELECT COUNT(*) FROM articles")
    stats["total_articles"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM searches")
    stats["total_searches"] = cursor.fetchone()[0]

    cursor.execute("SELECT year, COUNT(*) as n FROM articles GROUP BY year ORDER BY year DESC LIMIT 10")
    stats["articles_by_year"] = {row["year"]: row["n"] for row in cursor.fetchall()}

    # Topic distribution
    cursor.execute("SELECT topics FROM articles")
    topic_counts = {}
    for row in cursor.fetchall():
        for t in row["topics"].split("|"):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    stats["topic_distribution"] = dict(sorted(topic_counts.items(),
                                               key=lambda x: x[1], reverse=True))

    conn.close()
    return stats
