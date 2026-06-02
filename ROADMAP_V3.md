# NeuroLit Miner — Platform Roadmap

**Vision:** A modular, provider-agnostic research infrastructure platform
for neurosurgical evidence synthesis. Each module is independently useful
and composable with others.

---

## Architecture Principles

1. **Provider-agnostic** — no LLM is required for core functionality
2. **Modular** — each module (retrieval, analysis, synthesis) is independent
3. **Extensible** — new backends registered in one place, nothing else changes
4. **Reproducible** — all outputs include metadata, filters, and disclaimers
5. **Honest** — limitations are stated explicitly at every output layer

---

## Completed

### V1 — Data Pipeline
- [x] PubMed retrieval via NCBI E-utilities API
- [x] XML parsing with multi-batch fix
- [x] SQLite storage with deduplication (by PMID)
- [x] Topic classification (12-category keyword taxonomy)
- [x] CSV export
- [x] CLI (`main.py`)

### V1.5 — Platform Expansion
- [x] MeSH term extraction from PubMed XML (NLM-assigned, authoritative)
- [x] ClinicalTrials.gov integration (API v2, JSON)
- [x] Separate trials table in SQLite
- [x] Flask web UI (4 tabs: PubMed Search, Local Database, Analytics, Clinical Trials)
- [x] MeSH term display in UI (amber tags)
- [x] Trials CSV export
- [x] Stats dashboard with MeSH frequency chart

### V2 — Research Analytics Layer
- [x] `analyze.py` — 5 figure types saved as PNG + CSV
  - [x] Publication trend by year (with trend line)
  - [x] Journal distribution
  - [x] Topic distribution (bar + pie)
  - [x] MeSH term frequency (NLM-authoritative)
  - [x] MeSH co-occurrence matrix (heatmap)
- [x] Dark surgical visual theme consistent with Flask UI
- [x] CLI with topic/year/keyword filters

### V3 — Provider-Agnostic Synthesis Layer
- [x] `summarizer.py` — clean provider abstraction layer
  - [x] `BaseSummarizer` abstract base class
  - [x] `MockSummarizer` — deterministic keyword analysis, no API
  - [x] `OllamaSummarizer` — local LLM, free
  - [x] `AnthropicSummarizer` — Claude API
  - [x] `OpenAISummarizer` — GPT API
  - [x] `OpenRouterSummarizer` — multi-model, free tier available
  - [x] `get_summarizer()` factory with graceful fallback
  - [x] Shared prompt template across all LLM backends
  - [x] Shared evidence block builder
- [x] `summarize.py` — thin CLI, delegates entirely to summarizer.py
- [x] 3 output files: markdown summary, plain text, bibliography CSV
- [x] Graceful fallback — never crashes if LLM unavailable
- [x] Default provider: mock (works with zero setup)

---

## Planned

### V3.2 — Flask UI Taxonomy and Synthesis Integration
**Scope:** Flask UI update only — no new backend logic

- Three-axis tag display on article cards (Clinical Topic / Methodology / Domain)
- Filter dropdowns in Local Database tab for each axis
- Confidence badge on each article card
- Analytics tab: three-axis distribution charts
- Corpus purity score in Analytics tab
- Synthesis button in UI calling `summarize.py` backend

---

### V4.0 — PICO Extraction Module
**New file:** `src/pico.py`

Extract structured PICO elements from each abstract:
- **P** — Population (patient demographics, clinical topic)
- **I** — Intervention (surgery, drug, device, AI model)
- **C** — Comparator (control arm, standard of care)
- **O** — Outcome (primary endpoint, follow-up)

Architecture: subclass `BaseSummarizer` as `PICOExtractor`.
Same provider abstraction — mock mode extracts by taxonomy fields,
LLM mode extracts semantically. Output: `results/pico_[timestamp].csv`.

---

### V4.1 — Study Design Classification
**New file:** `src/classifier.py`

Classify each article by evidence level using `method_tags`:

| Level | Study Design |
|-------|-------------|
| I | RCT, systematic review |
| II | Prospective cohort |
| III | Retrospective cohort |
| IV | Case series |
| V | Expert opinion |

---

### V4.2 — Research Gap Detection
**New file:** `src/gaps.py`

Systematic extraction of stated limitations and future directions
across a corpus. Aggregates gap patterns, identifies most-cited
research needs, produces a structured gap map.

---

### V4.3 — Article–Trial Cross-Reference Module
**Enhancement to:** `database.py`, `app.py`

Link stored PubMed articles to stored ClinicalTrials.gov trials
by clinical topic MeSH term and condition field. Cross-reference
table in SQLite. New Flask UI tab.

---

## Architecture Principles (Permanent)

1. **Provider-agnostic** — no LLM required for core functionality
2. **Modular** — each layer independently useful and testable
3. **Extensible** — new backends registered in one place
4. **Reproducible** — all outputs include filters, timestamps, provenance
5. **Honest** — limitations stated explicitly in every output
6. **Backward compatible** — new versions never break existing functionality

---

*NeuroLit Miner · https://github.com/DrMoumenAI/neurolit-miner*  
*Author: Assia M. Moumen, M.D., MEng*
