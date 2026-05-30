<<<<<<< HEAD
# NeuroLit Miner 🧠

**Automated neurosurgical literature surveillance via PubMed E-utilities**
![NeuroLit Miner UI](Screenshot.png)

---

## Clinical Problem Statement

The neurosurgical literature is expanding at a rate that no individual clinician can manually track. Over 4,000 neurosurgery-related articles are indexed on PubMed annually, with AI/ML-focused publications doubling between 2018 and 2023. Evidence synthesis — the backbone of evidence-based neurosurgery — currently requires hours of manual search, deduplication, and categorization per review cycle.

NeuroLit Miner automates this process. It queries PubMed programmatically via the NCBI E-utilities API, retrieves structured metadata, classifies results by topic, and stores them in a local SQLite database for downstream analysis, systematic review preparation, or research tracking.

---

## What It Does (V1)

- Query PubMed with any neurosurgery keyword or topic combination
- Retrieve structured metadata: title, authors, journal, year, abstract, PMID
- Save results to CSV and SQLite
- Topic-tag results automatically
- Search and filter stored results by keyword, year, or topic

---

## Target Use Cases

- Systematic review preprocessing
- Research landscape surveillance (e.g., "all AI + glioblastoma papers 2020–2025")
- Fellowship application literature prep
- Academic productivity tracking

---

## Tech Stack

```
Python 3.x
requests          — HTTP calls to NCBI E-utilities
xml.etree         — XML parsing (PubMed returns XML)
sqlite3           — local database storage
csv               — export
json              — config and API handling
```

All dependencies are standard library or minimal. No deep learning frameworks required.

---

## Project Structure

```
neurolit-miner/
│
├── src/
│   ├── pubmed_api.py       # NCBI E-utilities query logic
│   ├── parser.py           # XML → structured dict
│   ├── database.py         # SQLite operations
│   ├── exporter.py         # CSV export
│   └── main.py             # CLI entry point
│
├── data/                   # Local SQLite database
├── results/                # CSV exports
├── requirements.txt
└── README.md
```

---

## Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Run a search
python src/main.py --query "glioblastoma machine learning" --max 50

# Search with year filter
python src/main.py --query "AI neurosurgery" --max 100 --year_from 2020

# Export stored results
python src/main.py --export --topic "glioblastoma"
```

## Web UI (new)

Run a simple local Flask web UI that uses the existing backend pipeline:

```bash
# Install dependencies (if not already done)
pip install -r requirements.txt

# Run the Flask app (development server)
python src/app.py
```

Then open your browser to: http://localhost:5000

The UI uses the real PubMed backend (no simulation) and stores results in the same SQLite database used by the CLI.

Important notes (beginner-friendly)
- The UI must be opened via the Flask app at http://localhost:5000 — do NOT open `templates/index.html` directly in your browser as a `file://` URL. The page depends on backend API routes (`/api/search`, `/api/stats`, `/api/export`) which are provided by the Flask server.
- The SQLite database (data/neurolit.db) is the source of truth. Searches append into this cumulative database; previous articles remain stored unless you delete the DB file.
- The CSV export in `results/` is a generated snapshot of the current DB contents at the time you click Export. It is not a live view — re-running searches updates the DB but does not automatically rewrite previously-exported CSV files unless you explicitly export again.

---

## Roadmap

| Version | Features |
|---------|----------|
| V1 | PubMed search, SQLite storage, CSV export, topic tagging |
| V1.5 | ClinicalTrials.gov module (GBM/meningioma trials) |
| V2 | Duplicate detection, batch queries, abstract keyword frequency |
| V3 | AI summarization layer, evidence grading scaffold |

---

## Author

**Assia Moumen** — M.D., MEng 
Pre-residency researcher building computational tools for neurosurgical evidence synthesis and global neurosurgery intelligence.

> *"We developed a Python-based automated literature surveillance tool using NCBI E-utilities to systematically retrieve and classify neurosurgical publications..."*
> — future Methods section

---

## Citation / Academic Use

If this tool contributes to a systematic review or meta-analysis, cite as:
```
Assia M Moumen NeuroLit Miner: Automated neurosurgical literature surveillance tool. 
GitHub, 2025. https://github.com/DrMoumenAI/neurolit-miner
```
=======
# neurolit-miner
Automated neurosurgical literature surveillance tool. Queries PubMed via NCBI E-utilities, classifies results by topic, stores in SQLite. Built with Python.
>>>>>>> 7a9dc6e2d53e9053e122c26a625841e9c690c7e9
