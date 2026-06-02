# NeuroLit Miner — System Architecture

**Version:** V3.1 Stable
**Author:** Assia M. Moumen, M.D., MEng
**Repository:** https://github.com/DrMoumenAI/neurolit-miner

---

## Overview

NeuroLit Miner is a modular, provider-agnostic research infrastructure platform for neurosurgical evidence synthesis. It is built as a pipeline of independent layers — each layer is useful in isolation, testable independently, and composable with others.

The system retrieves literature from PubMed and clinical trials from ClinicalTrials.gov, classifies articles using a three-axis biomedical taxonomy grounded in NLM MeSH ontology, stores everything in a structured SQLite database, generates publication-quality analytics figures, and produces AI-assisted evidence summaries.

**Core architectural principle:** every layer must function correctly without any other layer being available. The database works without the Flask UI. The analytics layer works without the synthesis layer. The synthesis layer works without a paid LLM backend. The system never crashes due to an optional component being unavailable.

---

## Full System Diagram

```
╔══════════════════════════════════════════════════════════════╗
║                     EXTERNAL SOURCES                         ║
╠══════════════════════╦═══════════════════════════════════════╣
║  PubMed              ║  ClinicalTrials.gov                   ║
║  NCBI E-utilities    ║  REST API v2                          ║
║  (XML)               ║  (JSON)                               ║
╚══════════╤═══════════╩══════════════╤════════════════════════╝
           │                          │
           ▼                          ▼
   ┌───────────────┐        ┌─────────────────┐
   │ pubmed_api.py │        │  trials_api.py  │
   │ esearch +     │        │  JSON → dicts   │
   │ efetch        │        └────────┬────────┘
   │ batch XML fix │                 │
   └───────┬───────┘                 │
           │                         │
           ▼                         │
   ┌───────────────┐                 │
   │  parser.py    │                 │
   │               │                 │
   │ • XML → dict  │                 │
   │ • MeSH extract│                 │
   │ • 3-axis      │                 │
   │   taxonomy    │                 │
   │   (V3.1)      │                 │
   └───────┬───────┘                 │
           │                         │
           ▼                         ▼
╔══════════════════════════════════════════════════════════════╗
║                      database.py                             ║
║                                                              ║
║  articles table     searches table     trials table          ║
║  (V1 + V3.1)        (V1)              (V1.5)                ║
║                                                              ║
║  pmid, title, authors, journal, year, abstract               ║
║  topics (V1 legacy)    mesh_terms (V1.5)                     ║
║  clinical_topic_tags   method_tags   domain_tags  (V3.1)     ║
║  topic_confidence (V3.1)                                     ║
╚═══════════╤══════════════════════════════════════════════════╝
            │
     ┌──────┴──────┐
     │             │
     ▼             ▼
┌──────────┐  ┌────────────────────────────────────────┐
│analyze.py│  │           summarize.py                 │
│          │  │           (thin CLI)                   │
│ 5 figure │  └────────────────┬───────────────────────┘
│ types    │                   │
│ PNG+CSV  │                   ▼
└──────────┘       ┌───────────────────────┐
     │             │     summarizer.py     │
     │             │  provider abstraction │
     │             │                       │
     │             │  mock  (default)      │
     │             │  ollama               │
     │             │  anthropic            │
     │             │  openai               │
     │             │  openrouter           │
     │             └───────────┬───────────┘
     │                         │
     ▼                         ▼
╔══════════════════════════════════════════════════════════════╗
║                       results/                               ║
║                                                              ║
║  trend_by_year.png          mesh_frequency.png               ║
║  journal_distribution.png   mesh_cooccurrence.png            ║
║  topic_distribution.png                                      ║
║                                                              ║
║  neurolit_summary_TIMESTAMP_SLUG.md                          ║
║  neurolit_summary_TIMESTAMP_SLUG.txt                         ║
║  neurolit_sources_TIMESTAMP_SLUG.csv                         ║
╚══════════════════════════════════════════════════════════════╝
            │
            ▼
   ┌──────────────────┐
   │     app.py       │
   │     (Flask)      │
   │                  │
   │  templates/      │
   │  index.html      │
   │  4 tabs          │
   └────────┬─────────┘
            │
            ▼
     localhost:5000
```

---

## Layer Reference

### Layer 1 — Retrieval

**Files:** `src/pubmed_api.py`, `src/trials_api.py`
**Introduced:** V1 (PubMed), V1.5 (ClinicalTrials)

`pubmed_api.py` implements the NCBI E-utilities two-step protocol:
1. `esearch.fcgi` — sends query string, receives list of PMIDs
2. `efetch.fcgi` — sends PMIDs in batches (≤200 per call), receives PubMed XML

**Critical V1.5 fix:** NCBI returns one complete XML document per batch, each with its own `<?xml?>` declaration and `<PubmedArticleSet>` root. Naive concatenation produces invalid XML ("junk after document element"). The fix extracts `<PubmedArticle>` blocks from each batch response using regex and wraps them in a single root document before parsing.

`trials_api.py` queries ClinicalTrials.gov API v2 (2023+), which returns JSON directly — no XML parsing required. Fields extracted per trial: NCT ID, title, status, phase, condition, intervention, sponsor, enrollment count, start/completion dates, primary endpoint, countries, brief summary.

**Rate limits:** NCBI allows 3 req/sec without an API key, 10 req/sec with `NCBI_API_KEY` in environment. Both modules include configurable `RATE_LIMIT_DELAY`.

---

### Layer 2 — Parsing and Taxonomy

**File:** `src/parser.py`
**Introduced:** V1 (parsing), V1.5 (MeSH), V3.1 (three-axis taxonomy)

`parse_xml()` converts PubMed XML to Python dicts. Handles:
- Standard and structured abstracts (multiple `AbstractText` elements with Label attributes — e.g. BACKGROUND, METHODS, RESULTS, CONCLUSIONS)
- Inconsistent publication date formats (PubDate/Year, MedlineDate strings like "2023 Jan-Feb", ArticleDate)
- Author formatting including collective names and author consortia
- Multi-location DOI extraction from ELocationID elements

`_extract_mesh()` navigates `MedlineCitation > MeshHeadingList > MeshHeading > DescriptorName`. Extracts descriptor names only (not qualifier subheadings) for clean frequency analysis. Returns empty list for articles pending NLM indexing.

**V3.1 taxonomy:** `assign_taxonomy()` classifies on three independent axes using MeSH-first priority. See [`docs/taxonomy.md`](taxonomy.md) for full specification.

**Backward compatibility:** The legacy `assign_topics()` function and `TOPIC_KEYWORDS` dict are fully preserved. All V1–V3 code that reads the `topics` column continues to work without modification.

---

### Layer 3 — Storage

**File:** `src/database.py`
**Introduced:** V1, extended V1.5, V3.1

SQLite database at `data/neurolit.db`. Three tables:

**`articles`** — deduplicated by PMID. Schema evolution:
```
V1:   pmid, title, authors, journal, year, abstract, topics, doi, url, date_added
V1.5: + mesh_terms
V3.1: + clinical_topic_tags, method_tags, domain_tags, topic_confidence
```

**`searches`** — log of all PubMed queries (query string, max results, year filters, result count, timestamp). Enables reproducibility: every search is recorded with its parameters.

**`trials`** — ClinicalTrials.gov records. Separate table because the schema is fundamentally different from articles (NCT ID, phase, recruitment status, sponsor, countries, primary endpoint).

**Migration strategy:** Every new column is added via `ALTER TABLE ADD COLUMN` wrapped in try/except. Each migration runs automatically on startup, is non-destructive, and is idempotent — safe to run multiple times. Existing records receive empty strings in new columns and are re-tagged by `backfill_taxonomy()`.

---

### Layer 4 — Analytics

**File:** `src/analyze.py`
**Introduced:** V2

Reads from SQLite, produces PNG figures and CSV data summaries in `results/`. Does not modify the database.

| Analysis | Output files | Clinical relevance |
|----------|-------------|-------------------|
| `trend` | `trend_by_year.png/csv` | Publication volume trajectory — growing, mature, or declining field |
| `journals` | `journal_distribution.png/csv` | Core publication venues — essential for SR search strategy and submission targeting |
| `topics` | `topic_distribution.png/csv` | Evidence landscape by category |
| `mesh` | `mesh_frequency.png/csv` | Authoritative semantic landscape via NLM ontology |
| `cooccurrence` | `mesh_cooccurrence.png/csv` | Structural map showing which concepts cluster together |

All figures share a dark surgical visual theme matching the Flask UI. Every figure includes `n=` annotation and data provenance note.

CLI: `python src/analyze.py [--analysis TYPE] [--topic FILTER] [--year_from Y] [--top_n N]`

---

### Layer 5 — Synthesis

**Files:** `src/summarizer.py`, `src/summarize.py`
**Introduced:** V3, V3.1

**`summarizer.py`** is the provider abstraction layer — the **only** file in the codebase that imports LLM SDKs. All other code calls:

```python
from summarizer import get_summarizer
s = get_summarizer("mock")   # or "ollama", "anthropic", "openai", "openrouter"
result = s.summarize(articles, filters)
```

`BaseSummarizer` defines the interface. Each backend implements `summarize()`. To add a new backend: subclass `BaseSummarizer`, implement `summarize()`, add one entry to `PROVIDER_REGISTRY`. Nothing else in the codebase changes.

`get_summarizer()` never raises — if a backend fails (missing key, import error, network error), it returns `MockSummarizer` and logs a clear message.

**`summarize.py`** is a thin CLI. It fetches articles from SQLite, computes corpus metadata, calls `get_summarizer().summarize()`, builds the output document, and saves three files. It contains no provider-specific logic.

**V3.1 additions:** four new CLI filters (`--clinical_topic`, `--method`, `--domain`, `--min_confidence`), corpus taxonomy profile block in every output document, per-article confidence indicators in terminal, corpus purity warning for heterogeneous queries, unique filename slugs.

---

### Layer 6 — Export

**File:** `src/exporter.py`
**Introduced:** V1

`export_to_csv()` writes article dicts to CSV with standard fieldnames compatible with reference managers (Zotero, Mendeley). V3.1 adds `mesh_terms`, `clinical_topic_tags`, `method_tags`, `domain_tags`, `topic_confidence` to the export fieldnames.

`print_summary_table()` renders a formatted terminal table for CLI output.

---

### Layer 7 — Web Interface

**Files:** `src/app.py`, `templates/index.html`
**Introduced:** V1.5

Flask application at `localhost:5000`. Four tabs, each backed by a REST API endpoint:

| Tab | Endpoint | Function |
|-----|----------|----------|
| PubMed Search | `POST /api/search` | Live query → parse → store → display with MeSH tags |
| Local Database | `GET /api/db/search` | Filter and browse stored articles |
| Analytics | `GET /api/stats` | Database statistics, MeSH frequency, topic distribution |
| Clinical Trials | `POST /api/trials/search` | ClinicalTrials.gov live search and storage |

Additional endpoints: `/api/export` (CSV), `/api/trials/db` (stored trials), `/api/trials/stats`.

**Important:** The Flask development server is not production-hardened. `localhost:5000` only.

---

## Version History

| Version | Layer added | Key capability |
|---------|------------|----------------|
| V1 | Retrieval, Storage, Export | PubMed pipeline, SQLite, CLI |
| V1.5 | MeSH extraction, Trials, Web UI | ClinicalTrials.gov, Flask interface |
| V2 | Analytics | 5 figure types, PNG+CSV output |
| V3 | Synthesis | Provider-agnostic LLM layer |
| V3.1 | Taxonomy | Three-axis classification, confidence scoring |

---

## Design Decision Log

| Decision | Rationale |
|----------|-----------|
| SQLite over PostgreSQL | Portable, zero-config, single-file. A researcher can email their entire database. |
| Provider abstraction in `summarizer.py` only | One file knows about LLMs. Everything else is LLM-agnostic. Adding a new backend requires changing one file. |
| MeSH-first classification | NLM assigns MeSH after full-text review. More reliable than author terminology. Already in the XML we fetch — zero additional API calls. |
| Clinical topic confidence as primary signal | A MeSH-confirmed disease tag determines corpus quality for synthesis, regardless of how the methodology was detected. |
| Legacy `topics` column preserved | Backward compatibility. Every V1–V3 function continues to work. New columns are additive only. |
| Default provider = mock | The system must work with zero setup. A researcher on a plane with no internet should be able to run a synthesis. |
| CLI first, UI second | CLI outputs are reproducible, scriptable, and citable in methods sections. UI is a convenience layer. |
| Disclaimer in all outputs | AI-assisted synthesis is not a systematic review. This must be stated clearly in every output document. |

---

*NeuroLit Miner · https://github.com/DrMoumenAI/neurolit-miner*
