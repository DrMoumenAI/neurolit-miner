"""
app.py
------
Flask web server for NeuroLit Miner V1.5.
Serves the UI and connects it to the real PubMed + ClinicalTrials pipeline.

Run:
    pip install flask
    python src/app.py

Then open: http://localhost:5000
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from flask import Flask, jsonify, render_template, request

from database import (
    get_stats,
    get_trials_stats,
    initialize_db,
    insert_articles,
    insert_trials,
    log_search,
    query_articles,
    query_trials,
)
from exporter import export_to_csv
from parser import parse_xml
from pubmed_api import fetch_records, search_pubmed
from trials_api import search_trials

app = Flask(__name__, template_folder="../templates")

# Initialize DB on startup (creates all tables including trials)
initialize_db()


# ── PubMed routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main UI."""
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    """
    Run a real PubMed search and return results as JSON.
    Expects JSON body: { query, max, year_from, year_to }
    """
    data      = request.get_json()
    query     = data.get("query", "").strip()
    max_res   = int(data.get("max", 20))
    year_from = int(data["year_from"]) if data.get("year_from") else None
    year_to   = int(data["year_to"])   if data.get("year_to")   else None

    if not query:
        return jsonify({"error": "Query cannot be empty."}), 400

    max_res = min(max_res, 50)

    try:
        pmids    = search_pubmed(query, max_results=max_res,
                                 year_from=year_from, year_to=year_to)
        if not pmids:
            return jsonify({"articles": [], "inserted": 0,
                            "message": "No results found. Try a different query."})

        xml_data = fetch_records(pmids)
        articles = parse_xml(xml_data)
        inserted = insert_articles(articles)
        log_search(query, max_res, year_from, year_to, inserted)

        return jsonify({
            "articles": articles,
            "inserted": inserted,
            "total":    len(articles),
            "message":  f"Retrieved {len(articles)} articles · {inserted} new stored."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/db/search", methods=["GET"])
def api_db_search():
    """Search already-stored articles in SQLite."""
    topic     = request.args.get("topic")
    keyword   = request.args.get("keyword")
    year_from = int(request.args["year_from"]) if request.args.get("year_from") else None
    year_to   = int(request.args["year_to"])   if request.args.get("year_to")   else None

    articles = query_articles(topic=topic, keyword=keyword,
                              year_from=year_from, year_to=year_to)
    return jsonify({"articles": articles, "total": len(articles)})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Return database statistics."""
    return jsonify(get_stats())


@app.route("/api/export", methods=["POST"])
def api_export():
    """Export current results to CSV."""
    data     = request.get_json()
    articles = data.get("articles", [])
    if not articles:
        return jsonify({"error": "No articles to export."}), 400
    filepath = export_to_csv(articles)
    return jsonify({"path": filepath, "count": len(articles)})


# ── ClinicalTrials.gov routes ─────────────────────────────────────────────────

@app.route("/api/trials/search", methods=["POST"])
def api_trials_search():
    """
    Search ClinicalTrials.gov and store results.
    Expects JSON: { condition, intervention, status, max }
    """
    data         = request.get_json()
    condition    = data.get("condition", "").strip()
    intervention = (data.get("intervention") or "").strip() or None
    status       = (data.get("status") or "").strip()       or None
    max_results  = int(data.get("max", 20))

    if not condition:
        return jsonify({"error": "Condition cannot be empty."}), 400

    try:
        trials   = search_trials(condition, intervention=intervention,
                                 status=status, max_results=max_results)
        inserted = insert_trials(trials, search_condition=condition)

        return jsonify({
            "trials":   trials,
            "inserted": inserted,
            "total":    len(trials),
            "message":  f"Retrieved {len(trials)} trials · {inserted} new stored."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trials/db", methods=["GET"])
def api_trials_db():
    """Query stored trials from SQLite."""
    condition = request.args.get("condition")
    status    = request.args.get("status")
    phase     = request.args.get("phase")
    keyword   = request.args.get("keyword")

    trials = query_trials(condition=condition, status=status,
                          phase=phase, keyword=keyword)
    return jsonify({"trials": trials, "total": len(trials)})


@app.route("/api/trials/stats", methods=["GET"])
def api_trials_stats():
    """Return trials table statistics."""
    return jsonify(get_trials_stats())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "═"*50)
    print("  NeuroLit Miner — Web Interface")
    print("  Open: http://localhost:5000")
    print("═"*50 + "\n")
    app.run(debug=True, port=5000)
