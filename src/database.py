"""
database.py
-----------
NeuroLit Miner V3.1 — SQLite operations.

Schema:
  articles table — one row per unique article (deduplicated by PMID)
  searches table — log of all queries run (for reproducibility)
  trials table   — ClinicalTrials.gov records (V1.5)

V3.1 additions to articles table:
  clinical_topic_tags TEXT  — Axis 1: clinical topic (MeSH-first, pipe-separated)
  method_tags         TEXT  — Axis 2: study methodology (MeSH-first, pipe-separated)
  domain_tags         TEXT  — Axis 3: clinical domain (MeSH-first, pipe-separated)
  topic_confidence    TEXT  — HIGH | MEDIUM | LOW | UNVERIFIED

Backward compatibility:
  The legacy `topics` column is preserved unchanged.
  All V1–V3 functions that read `topics` continue to work without modification.
  V3.1 columns are additive only — existing databases are migrated automatically
  via ALTER TABLE ADD COLUMN on startup (non-destructive, idempotent).

Migration strategy:
  Phase 1 (automatic): schema migration adds four columns on every startup.
  Phase 2 (optional):  backfill_taxonomy() re-tags all existing articles.
                       CLI: python src/main.py --backfill_taxonomy
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
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            pmid                 TEXT    UNIQUE NOT NULL,
            title                TEXT,
            authors              TEXT,
            journal              TEXT,
            year                 TEXT,
            abstract             TEXT,
            topics               TEXT,  -- legacy flat tags V1–V3 (preserved, approximate)
            mesh_terms           TEXT,  -- NLM MeSH headings V1.5 (authoritative)
            doi                  TEXT,
            url                  TEXT,
            date_added           TEXT,  -- ISO timestamp
            clinical_topic_tags  TEXT,  -- V3.1 Axis 1: clinical topic (MeSH-first)
            method_tags          TEXT,  -- V3.1 Axis 2: study methodology
            domain_tags          TEXT,  -- V3.1 Axis 3: clinical domain
            topic_confidence     TEXT   -- V3.1: HIGH | MEDIUM | LOW | UNVERIFIED
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

    # ── V3.1 migration: add three-axis taxonomy columns ──────────────────────
    # Non-destructive. Each ALTER TABLE is wrapped in try/except.
    # Existing records get empty strings — backfill_taxonomy() fills them later.
    # Running this on a fresh database is also safe (column already exists).
    v31_columns = [
        ("clinical_topic_tags", "TEXT DEFAULT ''"),
        ("method_tags",         "TEXT DEFAULT ''"),
        ("domain_tags",         "TEXT DEFAULT ''"),
        ("topic_confidence",    "TEXT DEFAULT 'UNVERIFIED'"),
    ]
    v31_added = []
    for col, col_type in v31_columns:
        try:
            cursor.execute(
                f"ALTER TABLE articles ADD COLUMN {col} {col_type}")
            v31_added.append(col)
        except Exception:
            pass  # Column already exists — normal on fresh databases

    if v31_added:
        print(f"[DB] V3.1 migration: added columns {v31_added}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_clinical_topic "
        "ON articles(clinical_topic_tags)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_method "
        "ON articles(method_tags)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_domain "
        "ON articles(domain_tags)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_confidence "
        "ON articles(topic_confidence)")

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
                    (pmid, title, authors, journal, year, abstract,
                     topics, mesh_terms, doi, url, date_added,
                     clinical_topic_tags, method_tags, domain_tags,
                     topic_confidence)
                VALUES
                    (:pmid, :title, :authors, :journal, :year, :abstract,
                     :topics, :mesh_terms, :doi, :url, :date_added,
                     :clinical_topic_tags, :method_tags, :domain_tags,
                     :topic_confidence)
            """, {
                **article,
                "date_added":           timestamp,
                "clinical_topic_tags":  article.get("clinical_topic_tags", ""),
                "method_tags":          article.get("method_tags", ""),
                "domain_tags":          article.get("domain_tags", ""),
                "topic_confidence":     article.get("topic_confidence", "UNVERIFIED"),
            })

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
                   clinical_topic: Optional[str] = None,
                   method: Optional[str] = None,
                   domain: Optional[str] = None,
                   confidence: Optional[str] = None,
                   db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """
    Query stored articles with optional filters.

    V3.1 additions:
        clinical_topic: filter Axis 1 (e.g. "glioblastoma", "trauma")
        method:         filter Axis 2 (e.g. "ML_AI", "retrospective_cohort")
        domain:         filter Axis 3 (e.g. "surgical_outcomes", "diagnosis_biomarker")
        confidence:     filter by confidence level (e.g. "HIGH", "MEDIUM")

    Backward compatible: existing callers using only topic/year/keyword
    continue to work without modification.

    Returns:
        List of article dicts ordered by year descending
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    conditions = []
    params = []

    if topic:
        # Legacy filter — searches the flat topics column
        conditions.append("topics LIKE ?")
        params.append(f"%{topic}%")

    if clinical_topic:
        conditions.append("clinical_topic_tags LIKE ?")
        params.append(f"%{clinical_topic}%")

    if method:
        conditions.append("method_tags LIKE ?")
        params.append(f"%{method}%")

    if domain:
        conditions.append("domain_tags LIKE ?")
        params.append(f"%{domain}%")

    if confidence:
        conditions.append("topic_confidence = ?")
        params.append(confidence.upper())

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
        SELECT pmid, title, authors, journal, year, abstract,
               topics, mesh_terms, doi, url,
               clinical_topic_tags, method_tags, domain_tags,
               topic_confidence
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


# ── V3.1: Backfill taxonomy ───────────────────────────────────────────────────

def backfill_taxonomy(db_path: str = DEFAULT_DB_PATH,
                      force: bool = False) -> dict:
    """
    Re-tag all existing articles using the V3.1 three-axis taxonomy.

    Reads every article from the database, runs assign_taxonomy() on
    stored title + abstract + mesh_terms, writes results to the three
    new axis columns and topic_confidence.

    Design principles:
    - Non-destructive: the legacy `topics` column is never modified
    - Idempotent: safe to run multiple times
    - Transparent: prints progress and a summary report
    - Selective: skips already-tagged articles unless force=True

    Args:
        db_path: path to SQLite database
        force:   if True, re-tag all articles even if already tagged
                 if False (default), only tag UNVERIFIED articles

    Returns:
        dict with summary statistics:
        {
            "total":      int,  total articles processed
            "tagged":     int,  articles successfully tagged
            "skipped":    int,  articles skipped (already tagged, force=False)
            "high":       int,  articles with HIGH confidence
            "medium":     int,  articles with MEDIUM confidence
            "low":        int,  articles with LOW confidence
            "unverified": int,  articles still UNVERIFIED after tagging
        }
    """
    # Import here to avoid circular import — parser imports nothing from database
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from parser import assign_taxonomy

    conn   = get_connection(db_path)
    cursor = conn.cursor()

    # Fetch all articles — we need title, abstract, mesh_terms, and
    # current topic_confidence to decide whether to skip
    cursor.execute("""
        SELECT pmid, title, abstract, mesh_terms, topic_confidence
        FROM articles
        ORDER BY id ASC
    """)
    articles = cursor.fetchall()
    total    = len(articles)

    print(f"\n[Backfill] Starting V3.1 taxonomy backfill")
    print(f"[Backfill] {total} articles in database")
    print(f"[Backfill] Mode: {'force re-tag all' if force else 'tag UNVERIFIED only'}")
    print(f"[Backfill] " + "─" * 40)

    stats = {"total": total, "tagged": 0, "skipped": 0,
             "high": 0, "medium": 0, "low": 0, "unverified": 0}

    for i, row in enumerate(articles, 1):
        pmid       = row["pmid"]
        confidence = row["topic_confidence"] or "UNVERIFIED"

        # Skip already-tagged articles unless force=True
        if not force and confidence != "UNVERIFIED":
            stats["skipped"] += 1
            continue

        title     = row["title"]    or ""
        abstract  = row["abstract"] or ""
        mesh_str  = row["mesh_terms"] or ""
        mesh_list = [t.strip() for t in mesh_str.split("|") if t.strip()]

        taxonomy  = assign_taxonomy(title, abstract, mesh_list)

        cursor.execute("""
            UPDATE articles
            SET clinical_topic_tags = ?,
                method_tags         = ?,
                domain_tags         = ?,
                topic_confidence    = ?
            WHERE pmid = ?
        """, (
            "|".join(taxonomy["clinical_topic_tags"]),
            "|".join(taxonomy["method_tags"]),
            "|".join(taxonomy["domain_tags"]),
            taxonomy["topic_confidence"],
            pmid,
        ))

        stats["tagged"] += 1
        conf = taxonomy["topic_confidence"]
        stats[conf.lower()] = stats.get(conf.lower(), 0) + 1

        # Progress indicator every 25 articles
        if i % 25 == 0 or i == total:
            print(f"[Backfill] {i}/{total} processed "
                  f"({stats['tagged']} tagged, {stats['skipped']} skipped)")

    conn.commit()
    conn.close()

    # Summary report
    print(f"\n[Backfill] ═══ Complete ═══")
    print(f"[Backfill] Total articles   : {stats['total']}")
    print(f"[Backfill] Tagged           : {stats['tagged']}")
    print(f"[Backfill] Skipped          : {stats['skipped']}")
    print(f"[Backfill] Confidence breakdown (tagged articles):")
    print(f"[Backfill]   HIGH           : {stats['high']}")
    print(f"[Backfill]   MEDIUM         : {stats['medium']}")
    print(f"[Backfill]   LOW            : {stats['low']}")
    print(f"[Backfill]   UNVERIFIED     : {stats['unverified']}")
    print(f"[Backfill] ═══════════════\n")

    return stats


def get_taxonomy_stats(db_path: str = DEFAULT_DB_PATH) -> dict:
    """
    Return V3.1 three-axis taxonomy statistics for the analytics layer.

    Called by analyze.py and the Flask /api/stats route.
    Returns frequency distributions for all three axes plus confidence.

    Returns:
        {
            "clinical_topic_distribution": {tag: count, ...},
            "method_distribution":         {tag: count, ...},
            "domain_distribution":         {tag: count, ...},
            "confidence_distribution":     {level: count, ...},
            "taxonomy_coverage":           float,  # % articles tagged (not UNVERIFIED)
            "high_confidence_count":       int,
        }
    """
    conn   = get_connection(db_path)
    cursor = conn.cursor()

    result = {
        "clinical_topic_distribution": {},
        "method_distribution":         {},
        "domain_distribution":         {},
        "confidence_distribution":     {},
        "taxonomy_coverage":           0.0,
        "high_confidence_count":       0,
    }

    try:
        # Confidence distribution
        cursor.execute("""
            SELECT topic_confidence, COUNT(*) as n
            FROM articles
            GROUP BY topic_confidence
        """)
        conf_rows = cursor.fetchall()
        total = 0
        tagged = 0
        for row in conf_rows:
            level = row["topic_confidence"] or "UNVERIFIED"
            count = row["n"]
            result["confidence_distribution"][level] = count
            total += count
            if level != "UNVERIFIED":
                tagged += count
            if level == "HIGH":
                result["high_confidence_count"] = count

        result["taxonomy_coverage"] = round(
            (tagged / total * 100) if total > 0 else 0.0, 1)

        # Axis frequency counts
        def count_axis(column):
            cursor.execute(
                f"SELECT {column} FROM articles WHERE {column} != ''")
            counts = {}
            for row in cursor.fetchall():
                for tag in (row[column] or "").split("|"):
                    tag = tag.strip()
                    if tag and tag != "uncategorized":
                        counts[tag] = counts.get(tag, 0) + 1
            return dict(sorted(counts.items(),
                                key=lambda x: x[1], reverse=True))

        result["clinical_topic_distribution"] = count_axis("clinical_topic_tags")
        result["method_distribution"]         = count_axis("method_tags")
        result["domain_distribution"]         = count_axis("domain_tags")

    except Exception as e:
        print(f"[DB] get_taxonomy_stats error: {e}")

    conn.close()
    return result
