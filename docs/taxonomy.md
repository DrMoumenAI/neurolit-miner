# NeuroLit Miner — Taxonomy Specification

**Version:** V3.1 Stable
**Implementation:** `src/parser.py`
**Database columns:** `clinical_topic_tags`, `method_tags`, `domain_tags`, `topic_confidence`

---

## Why a Taxonomy?

### The problem with flat keyword search

PubMed returns articles that match a query but do not necessarily form a coherent evidence corpus. A query for "glioblastoma outcomes" may return:
- Retrospective single-center case series (n=45)
- Phase III randomized controlled trials
- Deep learning prognostic models
- Quality-of-life questionnaire studies

These are all valid results but represent fundamentally different evidence types. Synthesizing them without distinguishing their nature produces a summary of mixed quality and scientific weight.

**Evidence synthesis quality is determined by corpus coherence before it is determined by LLM quality.** A heterogeneous corpus produces a heterogeneous summary regardless of which model processes it.

### The problem with the V1 flat taxonomy

The V1 `topics` column used a single flat list mixing:
- Disease descriptors: `glioblastoma`, `meningioma`
- Methodology descriptors: `AI_ML`
- Outcome descriptors: `outcomes_research`

These are different ontological levels. The result: `outcomes_research` tagged 14 of 19 articles (74%) — too broad to be useful as a synthesis filter, and scientifically meaningless as a category label.

### The V3.1 solution

Three independent axes, each capturing a different dimension of the article:

| Axis | Field | Ontological level | Maps to PICO |
|------|-------|------------------|--------------|
| Clinical Topic | `clinical_topic_tags` | Disease / population / system category | Population (P) |
| Methodology | `method_tags` | Study design / analytical approach | Study Design |
| Domain | `domain_tags` | Aspect of care addressed | Outcome (O) |

This alignment with PICO (Population / Intervention / Comparator / Outcome) is intentional. It directly enables PICO extraction as a future module — the taxonomy does most of the Population and Outcome pre-annotation automatically.

### Why "Clinical Topic" not "Condition"?

"Condition" implies a medical diagnosis. `global_neurosurgery` describes a population context and system-level category. `pediatric_neurosurgery` describes a patient demographic, not a disease. "Clinical Topic" is the correct superordinate term for a category that includes both specific diagnoses and broader population descriptors.

---

## MeSH-First Classification Strategy

### What is MeSH?

Medical Subject Headings (MeSH) is the National Library of Medicine's controlled vocabulary thesaurus. NLM subject matter experts assign MeSH terms to each PubMed article after full-text review. MeSH terms are:
- Hierarchical (disease → subtype → specific variant)
- Consistent across author terminology
- Already present in the PubMed XML retrieved by NeuroLit Miner — zero additional API calls
- The standard vocabulary for systematic review search strategy construction

### Priority order

For each tag in each axis, classification is attempted in this priority order:

```
Priority 1 — MeSH match              → HIGH confidence
  NLM DescriptorName found in MeshHeadingList
  Example: "Glioblastoma" in mesh_terms → clinical_topic = "glioblastoma"

Priority 2 — Title keyword match     → MEDIUM confidence
  Keyword found in article title (case-insensitive substring)
  Only applied if no MeSH match found for this tag
  Example: "glioblastoma" in title → clinical_topic = "glioblastoma"

Priority 3 — Abstract keyword match  → LOW confidence
  Keyword found in abstract text (case-insensitive substring)
  Only applied if no title keyword match found for this tag
  Least reliable — abstract language is author-specific and variable

No match                             → UNVERIFIED
  No MeSH terms present AND no keyword match found
  Typically: very recent article (MeSH pending) or genuinely off-topic
```

### Why keyword fallback?

NLM MeSH indexing typically lags publication by 2–8 weeks. Articles published within this window will have empty `mesh_terms`. Without keyword fallback, all very recent articles would be UNVERIFIED and excluded from synthesis — which would systematically bias the corpus toward older literature. Keyword fallback ensures recent articles are classified at lower confidence while still being retrievable.

### Confidence assignment logic

**Per-axis confidence** is the highest confidence level achieved for any tag on that axis:
- If any tag on the clinical topic axis was MeSH-confirmed → clinical confidence = HIGH
- If the best match on the method axis was a title keyword → method confidence = MEDIUM

**Overall article confidence** is determined by the **clinical topic axis confidence**, not the minimum across all axes.

*Rationale:* A MeSH-confirmed disease tag determines whether an article belongs in a synthesis corpus. If "Glioblastoma" is NLM-confirmed but the methodology was only identified by abstract keyword, the article is still HIGH confidence for a glioblastoma synthesis. The method detection quality does not affect clinical relevance.

Exception: if the clinical topic axis returns UNVERIFIED (no clinical topic found), the system uses the best confidence available across all three axes.

---

## Confidence Levels

| Level | Meaning | Typical article state |
|-------|---------|----------------------|
| `HIGH` | Clinical topic confirmed by NLM MeSH term | Indexed article with clear disease focus |
| `MEDIUM` | Clinical topic in article title; no MeSH confirmation | Recent article pending indexing, or MeSH uses different term |
| `LOW` | Clinical topic in abstract only; no title/MeSH match | Tangentially relevant article; use with caution |
| `UNVERIFIED` | No clinical topic identified | Very recent (MeSH pending), off-topic, or instrument study |

**Synthesis filter guidance:**
- `--min_confidence HIGH` — rigorous synthesis; MeSH-confirmed corpus only
- `--min_confidence MEDIUM` — standard synthesis; includes recent articles
- `--min_confidence LOW` — broad surveillance; maximum coverage, minimum precision
- No filter — all articles; use `--list_taxonomy` first to check corpus quality

---

## Axis 1 — Clinical Topic

Captures what disease, anatomy, or system-level category is studied.

| Tag | NLM MeSH Anchors | Keyword Fallback |
|-----|-----------------|-----------------|
| `glioblastoma` | Glioblastoma | glioblastoma, glioma, high-grade glioma, astrocytoma, IDH-wildtype, grade IV glioma |
| `low_grade_glioma` | Glioma | low-grade glioma, grade II/III glioma, oligodendroglioma, IDH-mutant, diffuse glioma |
| `meningioma` | Meningioma | meningioma, meningeal tumor, meningothelial |
| `brain_metastasis` | Brain Neoplasms | brain metastasis, cerebral metastasis, intracranial metastasis |
| `pituitary` | Pituitary Neoplasms, Pituitary Gland | pituitary adenoma, sellar, Cushing, acromegaly, prolactinoma, craniopharyngioma |
| `skull_base` | Skull Base Neoplasms, Neuroma Acoustic | skull base, acoustic neuroma, vestibular schwannoma, chordoma |
| `vascular` | Intracranial Aneurysm, Arteriovenous Malformations, Subarachnoid Hemorrhage | aneurysm, AVM, subarachnoid hemorrhage, cavernoma, cerebrovascular |
| `spine` | Spinal Cord, Spine, Intervertebral Disc, Spinal Cord Compression | spine, spinal, vertebral, disc herniation, spondylosis, myelopathy |
| `epilepsy_surgery` | Epilepsy, Drug Resistant Epilepsy | epilepsy surgery, temporal lobectomy, SEEG, drug-resistant epilepsy, hemispherectomy |
| `hydrocephalus` | Hydrocephalus | hydrocephalus, VP shunt, ETV, normal pressure hydrocephalus |
| `trauma` | Brain Injuries Traumatic, Craniocerebral Trauma | TBI, traumatic brain injury, subdural hematoma, epidural hematoma, craniectomy |
| `pediatric_neurosurgery` | Child, Infant, Pediatrics | pediatric, paediatric, craniosynostosis, medulloblastoma, ependymoma |
| `functional_neurosurgery` | Deep Brain Stimulation, Movement Disorders | DBS, Parkinson, essential tremor, dystonia, neuromodulation |
| `global_neurosurgery` | *(none — keyword only)* | global neurosurgery, LMIC, workforce, access to neurosurgical care |

> **Note on `global_neurosurgery`:** No specific NLM MeSH descriptor covers this category as of V3.1. All matching is keyword-based. Confidence will be MEDIUM (title match) or LOW (abstract only). This is expected, documented, and does not affect the validity of the category.

> **Note on `"gbm"` exclusion:** The abbreviation "GBM" was intentionally removed from the glioblastoma keyword list. It also expands to "gradient boosting machine" — a common machine learning algorithm. Including it caused false positives: TBI papers using gradient boosting were incorrectly tagged as glioblastoma. The MeSH anchor "Glioblastoma" cleanly catches the correct articles without this ambiguity.

---

## Axis 2 — Methodology

Captures how the study was designed and what analytical approach was used.

| Tag | NLM MeSH Anchors | Keyword Fallback |
|-----|-----------------|-----------------|
| `retrospective_cohort` | Retrospective Studies | retrospective, chart review, medical records review |
| `prospective_cohort` | Prospective Studies | prospective, longitudinal study, cohort study |
| `randomized_trial` | Randomized Controlled Trial | randomized, randomised, RCT, double-blind, placebo-controlled |
| `systematic_review` | Systematic Reviews as Topic, Meta-Analysis as Topic | systematic review, meta-analysis, PRISMA, pooled analysis |
| `case_series` | *(none)* | case series, case report |
| `ML_AI` | Machine Learning, Deep Learning, Neural Networks Computer | machine learning, deep learning, neural network, random forest, convolutional, transformer, LLM |
| `imaging_analysis` | Magnetic Resonance Imaging, Neuroimaging, Diffusion Tensor Imaging | MRI analysis, fMRI, DTI, tractography, radiomic, volumetric analysis |
| `biomechanical` | Biomechanical Phenomena | finite element, cadaveric, mechanical testing |
| `economic_analysis` | Cost-Benefit Analysis | cost-effectiveness, cost-utility, economic analysis |

---

## Axis 3 — Domain

Captures what aspect of clinical care is addressed.

| Tag | NLM MeSH Anchors | Keyword Fallback |
|-----|-----------------|-----------------|
| `surgical_technique` | Neurosurgical Procedures | surgical approach, craniotomy, resection technique, extent of resection, supramaximal resection |
| `surgical_outcomes` | Treatment Outcome, Postoperative Complications | complication, morbidity, mortality, reoperation, readmission |
| `oncologic_outcomes` | Survival Analysis, Neoplasm Recurrence Local, Disease-Free Survival | overall survival, progression-free survival, recurrence, tumor control |
| `functional_outcomes` | Quality of Life, Recovery of Function | quality of life, QOL, KPS, Karnofsky, neurological function, cognitive function |
| `diagnosis_biomarker` | Biomarkers Tumor, Diagnosis | biomarker, IDH mutation, MGMT methylation, 1p19q, diagnostic accuracy |
| `pharmacological` | Temozolomide, Bevacizumab, Antineoplastic Agents | chemotherapy, temozolomide, bevacizumab, immunotherapy, targeted therapy |
| `radiosurgery_radiotherapy` | Radiosurgery, Radiotherapy | radiosurgery, gamma knife, SRS, LINAC, SBRT, fractionated radiotherapy |
| `intraoperative_technology` | Neuronavigation, Fluorescence | awake craniotomy, iMRI, 5-ALA, cortical mapping, intraoperative ultrasound |
| `rehabilitation` | Rehabilitation | rehabilitation, neurological recovery, cognitive rehabilitation |
| `epidemiology` | Epidemiology, Incidence, Prevalence | incidence, prevalence, registry study, population-based |

---

## Backfill Workflow

When upgrading from V1–V3 to V3.1, existing articles have empty taxonomy columns. The backfill process re-tags them.

### When to run backfill

- After first installing V3.1 on an existing database
- After updating the taxonomy (adding tags, modifying keywords, correcting errors)
- After upgrading to a future taxonomy version

### Commands

```bash
# Tag UNVERIFIED articles only (default — fast, non-destructive)
python src/main.py --backfill_taxonomy

# Force re-tag ALL articles (use after taxonomy updates)
python src/main.py --force_backfill
```

### What backfill does

1. Reads every article from the database (title, abstract, mesh_terms)
2. Runs `assign_taxonomy()` on each article
3. Writes results to `clinical_topic_tags`, `method_tags`, `domain_tags`, `topic_confidence`
4. Skips articles where `topic_confidence != UNVERIFIED` (unless `--force_backfill`)
5. Prints a confidence breakdown report on completion

### What backfill does NOT do

- Does not modify the legacy `topics` column
- Does not delete any existing data
- Does not modify `mesh_terms` (those are extracted at fetch time)
- Cannot retroactively add MeSH terms to articles that were fetched before MeSH indexing

### Sample backfill output

```
[Backfill] Starting V3.1 taxonomy backfill
[Backfill] 19 articles in database
[Backfill] Mode: tag UNVERIFIED only
[Backfill] 19/19 processed (19 tagged, 0 skipped)

[Backfill] ═══ Complete ═══
[Backfill] Total articles   : 19
[Backfill] Tagged           : 19
[Backfill] Confidence breakdown:
[Backfill]   HIGH           : 14
[Backfill]   MEDIUM         : 4
[Backfill]   LOW            : 1
[Backfill]   UNVERIFIED     : 0
```

A corpus with 74% HIGH confidence (14/19) is well-suited for rigorous synthesis.

---

## Limitations and Known Issues

| Limitation | Impact | Mitigation |
|-----------|--------|-----------|
| `global_neurosurgery` has no MeSH anchor | Always MEDIUM/LOW confidence | Documented; keyword list is comprehensive |
| MeSH indexing lag (2–8 weeks) | Recent articles classified at MEDIUM/LOW | Keyword fallback; re-fetch after indexing |
| Multi-label ambiguity | An article on GBM + ML receives both `glioblastoma` and `ML_AI` | Correct behavior — multi-label is intentional |
| Confidence reflects clinical topic only | Method and domain confidence not surfaced per-article | Design decision — clinical relevance is the primary filter |
| 14 clinical topics may not cover all subspecialties | Tumors of the foramen magnum, etc. may be uncategorized | Taxonomy will expand as corpus grows |

---

## Future Taxonomy Development

| Planned feature | Target version |
|----------------|---------------|
| PICO pre-annotation using taxonomy fields | V4 |
| Evidence grading using method_tags + confidence | V5 |
| Taxonomy expansion from corpus MeSH frequency analysis | V5 |
| Flask UI three-axis filter dropdowns | V3.2 |

---

*NeuroLit Miner · https://github.com/DrMoumenAI/neurolit-miner*  
*Author: Assia M. Moumen, M.D., MEng*
