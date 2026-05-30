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
            topics      TEXT,       -- pipe-separated keyword topic tags (approximate)
            mesh_terms  TEXT,       -- pipe-separated NLM MeSH headings (authoritative)
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
    # V1.5 upgrade: add mesh_terms column to existing databases that were
    # created before this column existed. ALTER TABLE ADD COLUMN is safe to
    # run on a DB that already has the column — we catch the error silently.
    try:
        cursor.execute("ALTER TABLE articles ADD COLUMN mesh_terms TEXT DEFAULT ''")
        print("[DB] Added mesh_terms column to existing database (V1 → V1.5 upgrade)")
    except Exception:
        pass  # Column already exists — normal on fresh databases

    # Index must be created AFTER the column exists (migration above)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mesh ON articles(mesh_terms)")

    # ── V1.5: ClinicalTrials.gov trials table ────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trials (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nct_id           TEXT    UNIQUE NOT NULL,
            title            TEXT,
            status           TEXT,
            phase            TEXT,
            condition        TEXT,
            intervention     TEXT,
            sponsor          TEXT,
            enrollment       TEXT,
            start_date       TEXT,
            completion_date  TEXT,
            primary_outcome  TEXT,
            countries        TEXT,
            summary          TEXT,
            url              TEXT,
            search_condition TEXT,
            date_added       TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_status ON trials(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_phase  ON trials(phase)")

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
                    (pmid, title, authors, journal, year, abstract, topics, mesh_terms, doi, url, date_added)
                VALUES
                    (:pmid, :title, :authors, :journal, :year, :abstract, :topics, :mesh_terms, :doi, :url, :date_added)
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
        SELECT pmid, title, authors, journal, year, abstract, topics, mesh_terms, doi, url
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

    # MeSH term frequency — top 20 most common terms across all articles
    cursor.execute("SELECT mesh_terms FROM articles WHERE mesh_terms != ''")
    mesh_counts = {}
    for row in cursor.fetchall():
        for term in row["mesh_terms"].split("|"):
            term = term.strip()
            if term:
                mesh_counts[term] = mesh_counts.get(term, 0) + 1
    stats["top_mesh_terms"] = dict(
        sorted(mesh_counts.items(), key=lambda x: x[1], reverse=True)[:20]
    )
    stats["total_mesh_indexed"] = sum(
        1 for row in cursor.execute("SELECT mesh_terms FROM articles")
        if row["mesh_terms"]
    )

    conn.close()
    return stats


# ── V1.5: Trials functions ────────────────────────────────────────────────────

def insert_trials(trials: list[dict], search_condition: str = "",
                  db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Insert a list of trial dicts into the trials table.
    Deduplicates by NCT ID using INSERT OR IGNORE.

    Args:
        trials:           list of dicts from trials_api.search_trials()
        search_condition: the condition keyword used to find these trials
                          (stored for provenance — reproducibility tracking)

    Returns:
        Number of new trials actually inserted
    """
    if not trials:
        return 0

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # V1.5: add trials table if upgrading from V1 database
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trials (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nct_id           TEXT    UNIQUE NOT NULL,
            title            TEXT,
            status           TEXT,
            phase            TEXT,
            condition        TEXT,
            intervention     TEXT,
            sponsor          TEXT,
            enrollment       TEXT,
            start_date       TEXT,
            completion_date  TEXT,
            primary_outcome  TEXT,
            countries        TEXT,
            summary          TEXT,
            url              TEXT,
            search_condition TEXT,
            date_added       TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_status ON trials(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trial_phase  ON trials(phase)")

    timestamp = datetime.utcnow().isoformat()
    inserted  = 0

    for trial in trials:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO trials (
                    nct_id, title, status, phase, condition, intervention,
                    sponsor, enrollment, start_date, completion_date,
                    primary_outcome, countries, summary, url,
                    search_condition, date_added
                ) VALUES (
                    :nct_id, :title, :status, :phase, :condition, :intervention,
                    :sponsor, :enrollment, :start_date, :completion_date,
                    :primary_outcome, :countries, :summary, :url,
                    :search_condition, :date_added
                )
            """, {**trial,
                  "search_condition": search_condition,
                  "date_added":       timestamp})

            if cursor.rowcount > 0:
                inserted += 1

        except sqlite3.Error as e:
            print(f"[WARNING] DB insert error for {trial.get('nct_id','?')}: {e}")

    conn.commit()
    conn.close()

    duplicates = len(trials) - inserted
    print(f"[DB] Trials: inserted {inserted} new. ({duplicates} duplicates skipped)")
    return inserted


def query_trials(condition: Optional[str] = None,
                 status: Optional[str] = None,
                 phase: Optional[str] = None,
                 keyword: Optional[str] = None,
                 db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """
    Query stored trials with optional filters.

    Args:
        condition: filter by condition field (partial match)
        status:    filter by recruitment status (partial match)
        phase:     filter by trial phase (partial match)
        keyword:   search title and summary for this term

    Returns:
        List of trial dicts ordered by start_date descending
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    conditions_sql = []
    params = []

    if condition:
        conditions_sql.append("(condition LIKE ? OR search_condition LIKE ?)")
        params.extend([f"%{condition}%", f"%{condition}%"])

    if status:
        conditions_sql.append("status LIKE ?")
        params.append(f"%{status}%")

    if phase:
        conditions_sql.append("phase LIKE ?")
        params.append(f"%{phase}%")

    if keyword:
        conditions_sql.append("(title LIKE ? OR summary LIKE ? OR primary_outcome LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    where_clause = "WHERE " + " AND ".join(conditions_sql) if conditions_sql else ""

    cursor.execute(f"""
        SELECT nct_id, title, status, phase, condition, intervention,
               sponsor, enrollment, start_date, completion_date,
               primary_outcome, countries, summary, url, search_condition
        FROM trials
        {where_clause}
        ORDER BY start_date DESC
    """, params)

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    print(f"[DB] Trials query returned {len(rows)} records.")
    return rows


def get_trials_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """Return summary statistics for the trials table."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    stats = {}

    try:
        cursor.execute("SELECT COUNT(*) FROM trials")
        stats["total_trials"] = cursor.fetchone()[0]

        cursor.execute("SELECT status, COUNT(*) as n FROM trials GROUP BY status ORDER BY n DESC")
        stats["trials_by_status"] = {row["status"]: row["n"] for row in cursor.fetchall()}

        cursor.execute("SELECT phase, COUNT(*) as n FROM trials GROUP BY phase ORDER BY n DESC")
        stats["trials_by_phase"] = {row["phase"]: row["n"] for row in cursor.fetchall()}

    except sqlite3.OperationalError:
        # Trials table doesn't exist yet (V1 database)
        stats["total_trials"] = 0
        stats["trials_by_status"] = {}
        stats["trials_by_phase"] = {}

    conn.close()
    return stats
