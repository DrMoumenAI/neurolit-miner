"""
app.py
------
Simple Flask web UI for NeuroLit Miner.

Provides endpoints:
  - GET  /             → serves the HTML UI
  - POST /api/search   → runs PubMed search pipeline and returns JSON articles
  - GET  /api/stats    → returns database statistics as JSON
  - GET  /api/export   → exports filtered/current articles to CSV and returns file

This file uses the existing backend modules in `src/` (pubmed_api, parser, database, exporter).
Keep the implementation minimal and beginner-friendly.
"""

import os
import sys
from flask import Flask, request, jsonify, render_template, send_file

# Allow running from project root: python src/app.py
sys.path.insert(0, os.path.dirname(__file__))

from pubmed_api import search_pubmed, fetch_records
from parser import parse_xml
from database import initialize_db, insert_articles, log_search, query_articles, get_stats
from exporter import export_to_csv
from flask import send_from_directory


# Configure Flask to find templates directory one level up (project root/templates)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
app = Flask(__name__, template_folder=TEMPLATES_DIR)


@app.route("/")
def index():
    """Render the main UI page.

    The UI (templates/index.html) calls the API endpoints below.
    """
    # Ensure DB is initialized before the first use
    initialize_db()
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def api_search():
    """Run a PubMed search and return parsed articles as JSON.

    Expected JSON body: {"query": str, "max_results": int, "year_from": int|None, "year_to": int|None}
    Pipeline:
      1. search_pubmed()
      2. fetch_records()
      3. parse_xml()
      4. insert_articles()
      5. log_search()
    """
    data = request.get_json(force=True) or {}
    query = data.get("query", "").strip()
    max_results = int(data.get("max_results") or 50)
    year_from = data.get("year_from") or None
    year_to = data.get("year_to") or None

    if not query:
        return jsonify({"error": "query is required"}), 400

    initialize_db()

    # 1. Search PubMed for PMIDs
    pmids = search_pubmed(query=query, max_results=max_results,
                         year_from=year_from, year_to=year_to)

    if not pmids:
        # Return empty list so frontend can handle gracefully
        log_search(query, max_results, year_from, year_to, 0)
        return jsonify([])

    # 2. Fetch full XML
    xml_data = fetch_records(pmids)

    # 3. Parse XML
    articles = parse_xml(xml_data)

    # 4. Insert into DB (deduplicates)
    inserted = insert_articles(articles)
    duplicates = max(0, len(articles) - inserted)

    # 5. Log search
    log_search(query, max_results, year_from, year_to, inserted)

    # Total articles now in DB
    stats = get_stats()
    total_articles = stats.get("total_articles", 0)

    # Return structured response for frontend clarity
    return jsonify({
        "articles": articles,
        "retrieved": len(articles),
        "inserted": inserted,
        "duplicates": duplicates,
        "total_articles": total_articles,
    })


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Return simple DB statistics as JSON."""
    initialize_db()
    stats = get_stats()
    return jsonify(stats)


@app.route("/api/export", methods=["GET"])
def api_export():
    """Export stored or filtered articles to CSV and return file.

    Optional query params: topic, year_from, year_to, keyword
    If no articles found, returns 400 with a JSON error.
    """
    topic = request.args.get("topic") or None
    year_from = request.args.get("year_from") or None
    year_to = request.args.get("year_to") or None
    keyword = request.args.get("keyword") or None

    initialize_db()
    # If no filters provided, export all stored articles
    results = query_articles(topic=topic,
                             year_from=int(year_from) if year_from else None,
                             year_to=int(year_to) if year_to else None,
                             keyword=keyword)

    if not results:
        return jsonify({"error": "no articles to export"}), 400

    filepath = export_to_csv(results)
    if not filepath:
        return jsonify({"error": "export failed"}), 500

    # If caller requested an AJAX/json response, return metadata so frontend
    # can show a message and then trigger the download separately.
    if request.args.get("ajax") in ("1", "true", "yes"):
        return jsonify({
            "message": "CSV exported from current SQLite database snapshot.",
            "filename": os.path.basename(filepath),
            "filepath": filepath,
        })

    # Default behavior: send file for download
    return send_file(filepath, as_attachment=True)



@app.route('/api/export/download', methods=['GET'])
def api_export_download():
    """Download a previously-created CSV file by filename.

    Query param: file=<filename.csv>
    """
    filename = request.args.get('file')
    if not filename:
        return jsonify({"error": "file parameter required"}), 400

    results_dir = os.path.join(os.path.dirname(__file__), '..', 'results')
    return send_from_directory(results_dir, filename, as_attachment=True)


if __name__ == "__main__":
    # Run development server: python src/app.py
    app.run(host="127.0.0.1", port=5000, debug=True)
