# NeuroLit Miner — Roadmap

**Current version:** V3.1 Stable
**Repository:** https://github.com/DrMoumenAI/neurolit-miner

---

## Completed

### V1 — Data Pipeline
**Released:** May 2026
**Commit tag:** Initial release

The foundational retrieval and storage layer. Establishes the core data pipeline that all subsequent versions build on.

**Capabilities:**
- PubMed retrieval via NCBI E-utilities (`esearch` + `efetch`)
- Multi-batch XML parsing with correct root element merging
- SQLite storage with PMID-based deduplication
- Flat keyword topic classification (12 categories)
- CSV export via `exporter.py`
- Full CLI via `main.py`: `--query`, `--search_db`, `--stats`, `--export`

---

### V1.5 — Platform Expansion
**Released:** May 2026

Transforms the tool from a PubMed downloader into a multi-source evidence platform with a web interface.

**Capabilities:**
- MeSH term extraction from PubMed XML (NLM-assigned, no additional API calls)
- ClinicalTrials.gov integration via API v2 (JSON)
- Separate `trials` table in SQLite with full schema
- Flask web UI at `localhost:5000` — 4 tabs
- MeSH amber tag display on article cards
- Trials CSV export with NCT ID, phase, status, countries, primary endpoint
- Stored trials counter in stats dashboard

---

### V2 — Research Analytics Layer
**Released:** May 2026

Adds quantitative analysis output — transforms stored data into publication-quality figures.

**Capabilities:**
- `analyze.py` with 5 figure types, each saved as PNG + CSV
  - Publication trend by year with linear regression trend line
  - Journal distribution (horizontal bar chart, top N venues)
  - Topic distribution (bar chart + pie chart)
  - MeSH term frequency (NLM-authoritative, amber color)
  - MeSH co-occurrence matrix (heatmap — structural map of the field)
- Dark surgical visual theme consistent with Flask UI
- CLI filters: `--analysis`, `--topic`, `--year_from`, `--year_to`, `--top_n`
- All figures include `n=` annotation and provenance note

---

### V3 — Provider-Agnostic Synthesis Layer
**Released:** May 2026

Adds AI-assisted evidence synthesis while preserving complete independence from any specific LLM provider.

**Capabilities:**
- `summarizer.py` — clean provider abstraction layer
  - `BaseSummarizer` abstract base class
  - `MockSummarizer` — deterministic keyword analysis, no API, no cost, always works
  - `OllamaSummarizer` — local LLM, free, no API key required
  - `AnthropicSummarizer` — Claude API
  - `OpenAISummarizer` — GPT API
  - `OpenRouterSummarizer` — multi-model, free tier available
  - `get_summarizer()` factory with graceful fallback to mock
  - Shared prompt template and evidence block builder across all LLM backends
- `summarize.py` — thin CLI, delegates all provider logic to `summarizer.py`
- Three output files: markdown summary, plain text, bibliography CSV
- Graceful fallback — application never crashes if LLM unavailable
- Default provider: mock (zero setup required)
- `ROADMAP_V3.md` with module interaction map

---

### V3.1 — Evidence Organization and Taxonomy Intelligence
**Released:** May 2026
**Git tag:** v3.1.0

The evidence organization layer — replaces the flat keyword taxonomy with a scientifically defensible three-axis classification system.

**Capabilities:**
- Three-axis taxonomy replacing flat topic system
  - Axis 1: Clinical Topic (14 categories, MeSH-first)
  - Axis 2: Methodology (9 categories, MeSH-first)
  - Axis 3: Domain (10 categories, MeSH-first)
- MeSH-first classification with keyword fallback
- Confidence scoring: HIGH (MeSH) / MEDIUM (title) / LOW (abstract) / UNVERIFIED
- Clinical topic confidence as primary overall signal
- Four new SQLite columns with automatic non-destructive migration
- `backfill_taxonomy()` — re-tags existing articles
- `--backfill_taxonomy` and `--force_backfill` CLI flags
- V3.1 synthesis filters: `--clinical_topic`, `--method`, `--domain`, `--min_confidence`
- Corpus taxonomy profile block in all synthesis output documents
- Per-article confidence indicators `[H]/[M]/[L]/[U]` in CLI display
- Corpus purity warning for heterogeneous queries (< 60% dominant topic)
- Unique output filenames with filter slugs — prevents overwrite on same-second runs
- `docs/` folder with architecture, taxonomy, and roadmap documentation
- `"gbm"` keyword false positive fix
- `mesh_terms` in CSV export fieldnames

---

## Current

### V3.1 Stabilization
**Status:** 🔄 In progress

Post-release cleanup and repository professionalization.

- [x] Technical debt review completed
- [x] `docs/architecture.md` created
- [x] `docs/taxonomy.md` created
- [x] `docs/roadmap.md` created
- [x] README rewritten for V3.1
- [ ] `neurolit-miner-ui.html` removed from repo
- [ ] `src/index.html` confirmed removed
- [ ] Screenshots organized into `docs/screenshots/`
- [ ] `ROADMAP_V3.md` updated to point to `docs/roadmap.md`
- [ ] Git tag `v3.1.0` created

---

## Planned

### V3.2 — UI Taxonomy Integration
**Priority:** High
**Scope:** Flask UI update only — no new backend logic

- Three-axis tag display on article cards (Clinical Topic / Methodology / Domain rows)
- Filter dropdowns in Local Database tab for each axis
- Confidence badge on each article card
- Analytics tab: three-axis distribution charts (replacing/supplementing topic chart)
- Corpus purity score in Analytics tab
- `--list_taxonomy` improvements with per-category article counts

---

### V4 — PICO Extraction Module
**Priority:** Medium
**New file:** `src/pico.py`

PICO (Population / Intervention / Comparator / Outcome) is the standard framework for systematic review inclusion criteria. V3.1 taxonomy already pre-annotates P (via `clinical_topic_tags`) and O (via `domain_tags`).

- Mock mode: rule-based extraction using existing taxonomy fields
- LLM mode: semantic PICO extraction using `BaseSummarizer` architecture
- Output: `results/pico_TIMESTAMP.csv` — one row per article
- SQLite storage: PICO fields as new columns (non-destructive migration)

---

### V5 — Evidence Grading
**Priority:** Medium
**New file:** `src/classifier.py`

Maps study design to evidence level (Oxford CEBM or equivalent):

| Evidence Level | Study Design (`method_tags`) |
|---------------|------------------------------|
| Level I | `randomized_trial`, `systematic_review` |
| Level II | `prospective_cohort` |
| Level III | `retrospective_cohort` |
| Level IV | `case_series` |
| Level V | Expert opinion, case report |

Evidence level stored per article. Badge display in Flask UI. Integrated into synthesis output (confidence × evidence level).

---

### V5.1 — Articles–Trials Cross-Reference
**Priority:** Medium

Link stored PubMed articles to stored ClinicalTrials.gov trials by clinical topic MeSH term and condition field. Identify articles with corresponding active trials and vice versa. Cross-reference table in SQLite. New Flask UI tab.

---

### V6 — Export Enhancements
**Priority:** Low–Medium

- RIS / BibTeX export for reference managers (Zotero, Mendeley, EndNote)
- PRISMA flow diagram generator (screening stage tracking)
- Structured abstract table export (one row per article, all fields as columns)
- Combined PDF report: `analyze.py` figures + `summarize.py` synthesis

---

### V7 — Full UI Integration
**Priority:** Low

- `analyze.py` figures rendered inline in Analytics tab
- Synthesis button in Flask UI (calls `summarize.py` backend, displays markdown)
- PICO table view in Local Database tab
- Evidence level badges on article cards

---

### V8 — NeurosurgEval Integration
**Priority:** Long-term, contingent

Integration point for a future neurosurgical evidence evaluation framework. NeuroLit Miner provides retrieval, taxonomy, analytics, and synthesis infrastructure. NeurosurgEval would provide domain-specific evaluation rubrics and quality criteria.

---

## Architecture Principles (Permanent)

These principles are non-negotiable in all future development:

1. **Provider-agnostic** — no LLM is required for core functionality
2. **Modular** — each layer is independently useful, testable, and replaceable
3. **Extensible** — new backends registered in one place; nothing else changes
4. **Reproducible** — all outputs include filters, timestamps, and provenance
5. **Honest** — limitations stated explicitly in every output document
6. **Backward compatible** — new versions never break existing functionality

---

*NeuroLit Miner · https://github.com/DrMoumenAI/neurolit-miner*
*Author: Assia M. Moumen, M.D., MEng*
