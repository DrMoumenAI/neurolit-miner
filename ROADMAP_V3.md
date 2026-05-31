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

### V3.1 — PICO Extraction Module
**File:** `src/pico.py`  
**What:** Extract structured PICO elements from each abstract:
- Population (patient demographics, condition)
- Intervention (surgery, drug, device, AI model)
- Comparator (control arm, standard of care)
- Outcome (primary endpoint, follow-up)

**Why:** PICO is the foundation of systematic review inclusion criteria.
Automating extraction enables rapid evidence mapping.

**Architecture:** Subclass `BaseSummarizer` as `PICOExtractor`.
Same provider abstraction — mock mode extracts by keyword, LLM mode
extracts semantically.

**Output:** `results/pico_[timestamp].csv` — one row per article.

---

### V3.2 — Study Design Classification
**File:** `src/classifier.py`  
**What:** Classify each article by evidence level:
- Level I: RCT, systematic review, meta-analysis
- Level II: Prospective cohort
- Level III: Retrospective cohort, case-control
- Level IV: Case series
- Level V: Expert opinion, case report

**Why:** Evidence grading is mandatory for systematic reviews and
clinical guideline development.

**Architecture:** Rule-based classifier (mock) + LLM classifier (LLM providers).
Returns structured dict per article, stored back to SQLite.

---

### V3.3 — Research Gap Detection
**File:** `src/gaps.py`  
**What:** Systematic extraction of stated limitations and future directions
across a corpus. Aggregates gap patterns, identifies most-cited research
needs, produces a structured gap map.

**Why:** Gap detection is the core output of a scoping review and the
primary justification for new research proposals.

**Output:** Gap frequency table + narrative summary.

---

### V3.4 — Cross-Reference Module (Articles ↔ Trials)
**File:** enhancement to `database.py` + `app.py`  
**What:** Link stored PubMed articles to stored ClinicalTrials.gov trials
by condition, MeSH term, and keyword. Surface articles that have
corresponding active trials and vice versa.

**Why:** Evidence gap between published literature and active trials is
a key input for systematic reviews and research prioritisation.

**Output:** Cross-reference table in SQLite + UI display in new tab.

---

### V4 — Export Enhancements
- [ ] RIS/BibTeX export for reference managers (Zotero, Mendeley, EndNote)
- [ ] PRISMA flow diagram generator (screening stages)
- [ ] Structured abstract table (one row per article, all fields)
- [ ] Full summary report combining analyze.py figures + summarize.py text

---

### V5 — Visualisation Layer (Flask Integration)
- [ ] Integrate analyze.py figures into Analytics tab (rendered inline)
- [ ] Summarize button in Flask UI (calls summarizer.py, displays markdown)
- [ ] PICO table view in Local Database tab
- [ ] Evidence level badges on article cards

---

## Module Interaction Map

```
PubMed API          ClinicalTrials API
    ↓                       ↓
pubmed_api.py         trials_api.py
    ↓                       ↓
parser.py          (direct JSON parse)
    ↓                       ↓
         database.py (SQLite)
         ↙        ↓        ↘
   analyze.py  summarize.py  [future: pico.py, classifier.py, gaps.py]
      ↓              ↓
  PNG + CSV     MD + TXT + CSV
         ↘      ↙
         app.py (Flask UI)
              ↓
        localhost:5000
```

---

## Design Decision Log

| Decision | Rationale |
|----------|-----------|
| Default provider = mock | Platform must work with zero setup |
| Provider abstraction in summarizer.py | Single registration point for all LLM backends |
| SQLite over PostgreSQL | Portable, zero-config, researcher-friendly |
| CLI first, UI second | Easier to test, debug, and cite in methods sections |
| MeSH over keyword-only | NLM ontology is authoritative; keywords are approximate |
| Separate trials table | Articles and trials have different schemas; join later |
| Disclaimer in all outputs | Scientific honesty; prevents misuse as systematic review |

---

*NeuroLit Miner · https://github.com/DrMoumenAI/neurolit-miner*  
*Author: Assia Moumen M.D., MEng*
