"""
parser.py
---------
NeuroLit Miner V3.1 — PubMed XML parser with three-axis taxonomy.

PubMed's efetch returns PubmedArticleSet XML. Each article contains:
  - MedlineCitation > PMID
  - MedlineCitation > Article > ArticleTitle
  - MedlineCitation > Article > Abstract > AbstractText
  - MedlineCitation > Article > AuthorList > Author
  - MedlineCitation > Article > Journal > Title
  - MedlineCitation > Article > Journal > JournalIssue > PubDate
  - MedlineCitation > MeshHeadingList (MeSH terms — NLM-assigned, authoritative)

V3.1 changes — three-axis taxonomy replaces flat topic list:
  Axis 1: clinical_topic  — what clinical area is studied
                            (disease, anatomy, system-level category)
  Axis 2: method_tags     — how the study was designed
                            (study design, analytical approach)
  Axis 3: domain_tags     — what aspect of care is addressed
                            (surgical technique, outcomes, diagnosis, etc.)

Each axis is independent. An article can have multiple tags per axis.
The legacy `topics` field is preserved unchanged for backward compatibility.

Confidence scoring (V3.1):
  HIGH       — tag confirmed by a matching NLM MeSH term (authoritative)
  MEDIUM     — tag matched in article title only (no MeSH confirmation)
  LOW        — tag matched in abstract only (no title or MeSH confirmation)
  UNVERIFIED — no MeSH terms stored AND no keyword match

Scientific rationale:
  MeSH-first classification mirrors how clinical librarians construct
  systematic review search strategies. It is reproducible, consistent
  across author terminology, and directly maps to PICO Population axis.
  Keyword fallback is retained for very recent articles pending NLM indexing.
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# THREE-AXIS TAXONOMY (V3.1)
# ═══════════════════════════════════════════════════════════════════════════════
#
# Each taxonomy dict maps:
#   tag_label -> {
#       "mesh":     list of NLM MeSH DescriptorNames that confirm this tag (HIGH)
#       "keywords": list of title/abstract keywords (MEDIUM/LOW fallback)
#   }
#
# Design principles:
#   - AXIS 1 (clinical_topic): disease, anatomy, system-level category
#     "Clinical Topic" chosen over "Condition" because global_neurosurgery
#     and pediatric_neurosurgery describe populations, not conditions.
#   - AXIS 2 (method_tags): study design and analytical methodology
#   - AXIS 3 (domain_tags): clinical domain / aspect of care
#
# The three axes are semantically orthogonal. A condition tag says nothing
# about methodology. A methodology tag says nothing about domain. This maps
# directly to PICO: Topic≈Population, Method≈Study Design, Domain≈Outcome.
# ═══════════════════════════════════════════════════════════════════════════════

CLINICAL_TOPIC_TAXONOMY = {
    # ── Brain tumors ─────────────────────────────────────────────────────────
    "glioblastoma": {
        "mesh": ["Glioblastoma"],
        # "gbm" intentionally excluded — matches "gradient boosting machine"
        # causing false positives in ML papers on non-oncology topics
        "keywords": ["glioblastoma", "glioma", "high-grade glioma", "astrocytoma",
                     "IDH-wildtype", "grade IV glioma", "grade 4 glioma"],
    },
    "low_grade_glioma": {
        "mesh": ["Glioma"],
        "keywords": ["low-grade glioma", "grade II glioma", "grade III glioma",
                     "oligodendroglioma", "IDH-mutant", "diffuse glioma"],
    },
    "meningioma": {
        "mesh": ["Meningioma"],
        "keywords": ["meningioma", "meningeal tumor", "meningothelial"],
    },
    "brain_metastasis": {
        "mesh": ["Brain Neoplasms"],   # NLM uses this for metastases too
        "keywords": ["brain metastasis", "brain metastases", "cerebral metastasis",
                     "intracranial metastasis"],
    },
    "pituitary": {
        "mesh": ["Pituitary Neoplasms", "Pituitary Gland"],
        "keywords": ["pituitary", "pituitary adenoma", "sellar", "Cushing",
                     "acromegaly", "prolactinoma", "craniopharyngioma"],
    },
    "skull_base": {
        "mesh": ["Skull Base Neoplasms", "Neuroma, Acoustic"],
        "keywords": ["skull base", "acoustic neuroma", "vestibular schwannoma",
                     "glomus", "chordoma", "chondrosarcoma skull"],
    },

    # ── Vascular ──────────────────────────────────────────────────────────────
    "vascular": {
        "mesh": ["Intracranial Aneurysm", "Arteriovenous Malformations",
                 "Subarachnoid Hemorrhage", "Cavernous Sinus"],
        "keywords": ["aneurysm", "AVM", "arteriovenous malformation",
                     "subarachnoid hemorrhage", "cavernoma", "cavernous malformation",
                     "cerebrovascular", "intracranial hemorrhage"],
    },

    # ── Spine ─────────────────────────────────────────────────────────────────
    "spine": {
        "mesh": ["Spinal Cord", "Spine", "Intervertebral Disc",
                 "Spinal Cord Compression"],
        "keywords": ["spine", "spinal", "vertebral", "disc herniation",
                     "spondylosis", "myelopathy", "cord compression",
                     "lumbar", "cervical spine", "thoracic spine",
                     "scoliosis", "kyphosis"],
    },

    # ── Epilepsy surgery ──────────────────────────────────────────────────────
    "epilepsy_surgery": {
        "mesh": ["Epilepsy", "Drug Resistant Epilepsy"],
        "keywords": ["epilepsy surgery", "temporal lobectomy", "seizure surgery",
                     "stereoEEG", "SEEG", "resective epilepsy",
                     "drug-resistant epilepsy", "hemispherectomy",
                     "corpus callosotomy"],
    },

    # ── Hydrocephalus / CSF ───────────────────────────────────────────────────
    "hydrocephalus": {
        "mesh": ["Hydrocephalus"],
        "keywords": ["hydrocephalus", "CSF diversion", "ventriculoperitoneal shunt",
                     "VP shunt", "endoscopic third ventriculostomy", "ETV",
                     "normal pressure hydrocephalus"],
    },

    # ── Trauma ────────────────────────────────────────────────────────────────
    "trauma": {
        "mesh": ["Brain Injuries, Traumatic", "Craniocerebral Trauma"],
        "keywords": ["traumatic brain injury", "TBI", "head trauma",
                     "subdural hematoma", "epidural hematoma",
                     "decompressive craniectomy", "diffuse axonal injury"],
    },

    # ── Pediatric ─────────────────────────────────────────────────────────────
    "pediatric_neurosurgery": {
        "mesh": ["Child", "Infant", "Pediatrics"],
        "keywords": ["pediatric", "paediatric", "childhood brain",
                     "neonatal neurosurgery", "craniosynostosis",
                     "pediatric tumor", "medulloblastoma", "ependymoma"],
    },

    # ── Functional / movement ─────────────────────────────────────────────────
    "functional_neurosurgery": {
        "mesh": ["Deep Brain Stimulation", "Movement Disorders"],
        "keywords": ["deep brain stimulation", "DBS", "movement disorder",
                     "Parkinson", "essential tremor", "dystonia",
                     "neuromodulation", "stereotactic functional"],
    },

    # ── Global neurosurgery ───────────────────────────────────────────────────
    # Placed on clinical_topic axis, not domain — describes a population
    # context and system-level category, not a disease or methodology
    "global_neurosurgery": {
        "mesh": [],   # No specific NLM MeSH term — keyword-only
        "keywords": ["global neurosurgery", "low-income", "LMIC",
                     "sub-saharan", "neurosurgical workforce",
                     "access to neurosurgical care", "task sharing",
                     "neurosurgical capacity", "burden of neurosurgical disease"],
    },
}


METHOD_TAXONOMY = {
    "retrospective_cohort": {
        "mesh": ["Retrospective Studies"],
        "keywords": ["retrospective", "chart review", "medical records review",
                     "retrospective analysis"],
    },
    "prospective_cohort": {
        "mesh": ["Prospective Studies"],
        "keywords": ["prospective", "longitudinal study", "cohort study"],
    },
    "randomized_trial": {
        "mesh": ["Randomized Controlled Trials as Topic",
                 "Randomized Controlled Trial"],
        "keywords": ["randomized", "randomised", "RCT",
                     "double-blind", "placebo-controlled"],
    },
    "systematic_review": {
        "mesh": ["Systematic Reviews as Topic", "Meta-Analysis as Topic"],
        "keywords": ["systematic review", "meta-analysis", "PRISMA",
                     "evidence synthesis", "pooled analysis"],
    },
    "case_series": {
        "mesh": [],
        "keywords": ["case series", "case report", "single case"],
    },
    "ML_AI": {
        "mesh": ["Machine Learning", "Deep Learning",
                 "Neural Networks, Computer"],
        "keywords": ["machine learning", "deep learning", "artificial intelligence",
                     "neural network", "random forest", "convolutional",
                     "transformer", "large language model", "LLM", "NLP",
                     "support vector machine", "gradient boosting"],
    },
    "imaging_analysis": {
        "mesh": ["Magnetic Resonance Imaging", "Neuroimaging",
                 "Diffusion Tensor Imaging"],
        "keywords": ["MRI analysis", "CT analysis", "DTI", "fMRI",
                     "neuroimaging study", "tractography", "volumetric analysis",
                     "radiomic"],
    },
    "biomechanical": {
        "mesh": ["Biomechanical Phenomena"],
        "keywords": ["finite element", "biomechanical", "cadaveric study",
                     "mechanical testing"],
    },
    "economic_analysis": {
        "mesh": ["Cost-Benefit Analysis"],
        "keywords": ["cost-effectiveness", "cost-utility", "economic analysis",
                     "healthcare cost", "cost analysis"],
    },
}


DOMAIN_TAXONOMY = {
    "surgical_technique": {
        "mesh": ["Neurosurgical Procedures"],
        "keywords": ["surgical approach", "surgical technique", "craniotomy",
                     "operative corridor", "surgical anatomy", "resection technique",
                     "extent of resection", "supramaximal resection",
                     "gross total resection"],
    },
    "surgical_outcomes": {
        "mesh": ["Treatment Outcome", "Postoperative Complications"],
        "keywords": ["surgical outcome", "complication", "morbidity", "mortality",
                     "reoperation", "readmission", "30-day outcome",
                     "perioperative", "adverse event"],
    },
    "oncologic_outcomes": {
        "mesh": ["Survival Analysis", "Neoplasm Recurrence, Local",
                 "Disease-Free Survival"],
        "keywords": ["overall survival", "progression-free survival",
                     "local recurrence", "tumor control", "disease control",
                     "time to progression", "median survival"],
    },
    "functional_outcomes": {
        "mesh": ["Quality of Life", "Recovery of Function"],
        "keywords": ["quality of life", "QOL", "functional status",
                     "neurological function", "KPS", "Karnofsky",
                     "cognitive function", "activities of daily living"],
    },
    "diagnosis_biomarker": {
        "mesh": ["Biomarkers, Tumor", "Diagnosis"],
        "keywords": ["diagnosis", "biomarker", "imaging feature",
                     "molecular marker", "IDH mutation", "MGMT methylation",
                     "1p19q", "TERT", "diagnostic accuracy"],
    },
    "pharmacological": {
        "mesh": ["Temozolomide", "Bevacizumab", "Antineoplastic Agents"],
        "keywords": ["chemotherapy", "temozolomide", "bevacizumab",
                     "immunotherapy", "checkpoint inhibitor", "targeted therapy",
                     "carmustine", "lomustine"],
    },
    "radiosurgery_radiotherapy": {
        "mesh": ["Radiosurgery", "Radiotherapy"],
        "keywords": ["radiosurgery", "gamma knife", "CyberKnife", "LINAC",
                     "stereotactic radiosurgery", "SRS", "SBRT",
                     "radiation therapy", "fractionated radiotherapy"],
    },
    "intraoperative_technology": {
        "mesh": ["Neuronavigation", "Fluorescence"],
        "keywords": ["awake craniotomy", "intraoperative MRI", "iMRI",
                     "5-ALA", "fluorescence-guided", "neuronavigation",
                     "intraoperative ultrasound", "cortical mapping",
                     "intraoperative monitoring"],
    },
    "rehabilitation": {
        "mesh": ["Rehabilitation"],
        "keywords": ["rehabilitation", "neurological recovery",
                     "physical therapy", "occupational therapy",
                     "cognitive rehabilitation"],
    },
    "epidemiology": {
        "mesh": ["Epidemiology", "Incidence", "Prevalence"],
        "keywords": ["incidence", "prevalence", "epidemiology",
                     "population-based", "registry study", "demographic"],
    },
}


# ── Legacy flat taxonomy (V1–V3) ──────────────────────────────────────────────
# Preserved unchanged for backward compatibility.
# The `topics` column in SQLite continues to be populated from this dict.
# All existing V1–V3 functions that read `topics` continue to work.

TOPIC_KEYWORDS = {
    "glioblastoma":        ["glioblastoma", "glioma", "high-grade glioma",
                            "astrocytoma"],
    "meningioma":          ["meningioma"],
    "spine":               ["spine", "spinal", "vertebral", "disc herniation",
                            "spondylosis", "myelopathy", "cord compression"],
    "epilepsy_surgery":    ["epilepsy surgery", "temporal lobectomy",
                            "seizure surgery", "stereoEEG", "SEEG",
                            "resective epilepsy"],
    "vascular":            ["aneurysm", "AVM", "arteriovenous",
                            "subarachnoid hemorrhage", "cavernoma",
                            "cerebrovascular"],
    "AI_ML":               ["machine learning", "deep learning",
                            "artificial intelligence", "neural network",
                            "random forest", "convolutional", "transformer",
                            "large language model", "LLM", "NLP"],
    "intraoperative_tech": ["awake craniotomy", "intraoperative MRI", "iMRI",
                            "fluorescence-guided", "5-ALA", "neuronavigation",
                            "ultrasound-guided"],
    "global_neurosurgery": ["global neurosurgery", "low-income", "LMIC",
                            "sub-saharan", "workforce", "access to care",
                            "task sharing", "neurosurgical capacity"],
    "outcomes_research":   ["outcome", "prognosis", "survival",
                            "quality of life", "QOL", "NSQIP",
                            "complication", "morbidity", "mortality",
                            "readmission"],
    "radiosurgery":        ["radiosurgery", "gamma knife", "cyberknife",
                            "stereotactic", "SRS", "SBRT", "LINAC"],
    "pediatric":           ["pediatric", "paediatric", "childhood",
                            "neonatal", "hydrocephalus", "craniosynostosis"],
    "trauma":              ["traumatic brain injury", "TBI", "head trauma",
                            "subdural", "epidural hematoma", "craniectomy"],
}


# ═══════════════════════════════════════════════════════════════════════════════
# TAXONOMY ASSIGNMENT FUNCTIONS (V3.1)
# ═══════════════════════════════════════════════════════════════════════════════

def _match_taxonomy_axis(taxonomy: dict,
                         mesh_terms: list[str],
                         title: str,
                         abstract: str) -> tuple[list[str], str]:
    """
    Match a single taxonomy axis against MeSH terms and text.
    Returns (matched_tags, confidence_level).

    Confidence hierarchy (MeSH-first):
      HIGH   — at least one tag confirmed by an NLM MeSH term
      MEDIUM — at least one tag matched in title, no MeSH confirmation
      LOW    — at least one tag matched in abstract only
      UNVERIFIED — no matches found

    This function is the core of the MeSH-first classification strategy.
    MeSH terms are checked first and take priority. Keyword matching is a
    fallback for articles pending NLM indexing (typically recent papers).

    Args:
        taxonomy:   one of CLINICAL_TOPIC_TAXONOMY / METHOD_TAXONOMY / DOMAIN_TAXONOMY
        mesh_terms: list of MeSH descriptors already extracted from PubMed XML
        title:      article title string
        abstract:   abstract text string

    Returns:
        (list of matched tag labels, confidence string)
    """
    mesh_set      = set(mesh_terms)
    title_lower   = title.lower()
    abstract_lower= abstract.lower()

    matched_high   = []   # MeSH-confirmed
    matched_medium = []   # title keyword match
    matched_low    = []   # abstract keyword match only

    for tag, spec in taxonomy.items():
        mesh_kws   = spec.get("mesh", [])
        text_kws   = spec.get("keywords", [])

        # Priority 1: MeSH match (authoritative — NLM-assigned after full-text review)
        if any(m in mesh_set for m in mesh_kws):
            matched_high.append(tag)
            continue   # no need to check keywords if MeSH confirms

        # Priority 2: title keyword match
        if any(kw.lower() in title_lower for kw in text_kws):
            matched_medium.append(tag)
            continue

        # Priority 3: abstract keyword match (least reliable)
        if any(kw.lower() in abstract_lower for kw in text_kws):
            matched_low.append(tag)

    # Aggregate confidence: highest confidence level achieved determines overall score
    all_matched = matched_high + matched_medium + matched_low
    if matched_high:
        confidence = "HIGH"
    elif matched_medium:
        confidence = "MEDIUM"
    elif matched_low:
        confidence = "LOW"
    else:
        confidence = "UNVERIFIED"

    return (all_matched if all_matched else ["uncategorized"], confidence)


def assign_taxonomy(title: str, abstract: str,
                    mesh_terms: list[str]) -> dict:
    """
    V3.1 three-axis taxonomy assignment.
    Returns a dict with all three axes and confidence scores.

    This is the public API for taxonomy assignment.
    Called by parse_xml() for new articles and by backfill_taxonomy()
    for existing articles.

    Args:
        title:      article title
        abstract:   abstract text
        mesh_terms: list of NLM MeSH descriptor strings

    Returns:
        {
            "clinical_topic_tags": list[str],   # Axis 1 — what is studied
            "method_tags":         list[str],   # Axis 2 — how it was studied
            "domain_tags":         list[str],   # Axis 3 — what aspect of care
            "topic_confidence":    str,         # overall: HIGH/MEDIUM/LOW/UNVERIFIED
            "clinical_confidence": str,         # per-axis confidence
            "method_confidence":   str,
            "domain_confidence":   str,
        }
    """
    clinical_tags, clinical_conf = _match_taxonomy_axis(
        CLINICAL_TOPIC_TAXONOMY, mesh_terms, title, abstract)

    method_tags, method_conf = _match_taxonomy_axis(
        METHOD_TAXONOMY, mesh_terms, title, abstract)

    domain_tags, domain_conf = _match_taxonomy_axis(
        DOMAIN_TAXONOMY, mesh_terms, title, abstract)

    # Overall confidence: driven primarily by clinical_topic axis.
    #
    # Design decision (V3.1 review):
    # The "minimum across axes" rule is too strict for evidence synthesis.
    # A HIGH-confidence disease tag (MeSH-confirmed) is what determines
    # whether an article belongs in a synthesis corpus — regardless of
    # whether the methodology tag was confirmed by MeSH or by keyword.
    #
    # Rule: clinical_topic confidence is the primary signal.
    # If clinical topic is UNVERIFIED, we fall back to the best available.
    confidence_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNVERIFIED": 0}
    if clinical_conf != "UNVERIFIED":
        overall = clinical_conf
    else:
        # No clinical topic identified — use best confidence across all axes
        overall = max(
            [clinical_conf, method_conf, domain_conf],
            key=lambda c: confidence_rank[c]
        )

    return {
        "clinical_topic_tags": clinical_tags,
        "method_tags":         method_tags,
        "domain_tags":         domain_tags,
        "topic_confidence":    overall,
        "clinical_confidence": clinical_conf,
        "method_confidence":   method_conf,
        "domain_confidence":   domain_conf,
    }


def assign_topics(title: str, abstract: str) -> list[str]:
    """
    Legacy flat topic assignment — preserved for backward compatibility.
    Still populates the `topics` column in SQLite.
    All V1–V3 functions that read `topics` continue to work unchanged.

    V3.1 note: prefer assign_taxonomy() for new code.
    """
    combined = (title + " " + abstract).lower()
    matched  = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in combined for kw in keywords):
            matched.append(topic)
    return matched if matched else ["uncategorized"]


# ═══════════════════════════════════════════════════════════════════════════════
# XML EXTRACTION HELPERS (unchanged from V1.5)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_text(element, path: str, default: str = "") -> str:
    """Safe XML element text extraction with fallback."""
    node = element.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return default


def _extract_authors(article_node) -> str:
    """Extract formatted author list as 'LastName FM, LastName FM, ...'"""
    authors     = []
    author_list = article_node.find(".//AuthorList")
    if author_list is None:
        return "N/A"

    for author in author_list.findall("Author"):
        last     = _get_text(author, "LastName")
        fore     = _get_text(author, "ForeName")
        initials = _get_text(author, "Initials")
        if last:
            name = last
            if fore:
                name += " " + "".join(w[0] for w in fore.split() if w)
            elif initials:
                name += " " + initials
            authors.append(name)

    if not authors:
        collective = article_node.find(".//CollectiveName")
        if collective is not None and collective.text:
            return collective.text.strip()

    return ", ".join(authors) if authors else "N/A"


def _extract_year(article_node) -> str:
    """Extract publication year — checks multiple PubMed date locations."""
    year = _get_text(article_node, ".//PubDate/Year")
    if year:
        return year
    medline_date = _get_text(article_node, ".//PubDate/MedlineDate")
    if medline_date:
        match = re.search(r'\b(19|20)\d{2}\b', medline_date)
        if match:
            return match.group()
    year = _get_text(article_node, ".//ArticleDate/Year")
    if year:
        return year
    return "N/A"


def _extract_abstract(article_node) -> str:
    """Extract abstract text. Handles structured abstracts with Labels."""
    abstract_node = article_node.find(".//Abstract")
    if abstract_node is None:
        return "No abstract available."
    texts = []
    for abstract_text in abstract_node.findall("AbstractText"):
        label = abstract_text.get("Label", "")
        text  = abstract_text.text or ""
        texts.append(f"{label}: {text.strip()}" if label else text.strip())
    return " ".join(texts) if texts else "No abstract available."


def _extract_mesh(medline_node) -> list[str]:
    """
    Extract MeSH DescriptorNames from MedlineCitation.
    Returns empty list for recent articles pending NLM indexing.
    We extract DescriptorName only (not QualifierName) for clean frequency
    analysis and co-occurrence mapping.
    """
    mesh_list = medline_node.find("MeshHeadingList")
    if mesh_list is None:
        return []
    terms = []
    for heading in mesh_list.findall("MeshHeading"):
        descriptor = heading.find("DescriptorName")
        if descriptor is not None and descriptor.text:
            terms.append(descriptor.text.strip())
    return terms


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PARSE FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def parse_xml(xml_string: str) -> list[dict]:
    """
    Parse a PubMed efetch XML response into a list of article dictionaries.

    V3.1 additions to each dict:
        clinical_topic_tags  — Axis 1 pipe-separated (clinical topic)
        method_tags          — Axis 2 pipe-separated (methodology)
        domain_tags          — Axis 3 pipe-separated (domain)
        topic_confidence     — overall confidence: HIGH/MEDIUM/LOW/UNVERIFIED

    Preserved from V1.5 (backward compatibility):
        topics               — legacy flat tags, still populated
        mesh_terms           — NLM MeSH terms, still populated

    Args:
        xml_string: raw XML string from pubmed_api.fetch_records()

    Returns:
        List of article dicts (empty list on parse error)
    """
    if not xml_string or not xml_string.strip():
        return []

    articles = []

    # Multi-batch XML fix (V1.5): strip repeated XML declarations and
    # merge adjacent PubmedArticleSet root elements into one valid document.
    cleaned = re.sub(r'<\?xml[^?]*\?>', '', xml_string)
    cleaned = re.sub(r'</PubmedArticleSet>\s*<PubmedArticleSet>', '', cleaned)
    cleaned = cleaned.strip()
    if not cleaned.startswith('<PubmedArticleSet'):
        cleaned = f'<PubmedArticleSet>{cleaned}</PubmedArticleSet>'

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as e:
        print(f"[ERROR] XML parse failed: {e}")
        return []

    for article_set in root.iter("PubmedArticle"):
        try:
            medline = article_set.find("MedlineCitation")
            article = medline.find("Article") if medline is not None else None
            if medline is None or article is None:
                continue

            pmid     = _get_text(medline, "PMID")
            title    = _get_text(article, "ArticleTitle")
            journal  = _get_text(article, ".//Journal/Title")
            year     = _extract_year(article)
            authors  = _extract_authors(article)
            abstract = _extract_abstract(article)

            # MeSH terms — used as primary input to V3.1 taxonomy
            mesh_terms = _extract_mesh(medline)

            # DOI
            doi = ""
            for loc in article.findall(".//ELocationID"):
                if loc.get("EIdType") == "doi" and loc.text:
                    doi = loc.text.strip()
                    break

            # V1 legacy topics (backward compatibility — unchanged)
            legacy_topics = assign_topics(title, abstract)

            # V3.1 three-axis taxonomy
            taxonomy = assign_taxonomy(title, abstract, mesh_terms)

            articles.append({
                # ── Core fields (V1) ──────────────────────────────────────
                "pmid":     pmid,
                "title":    title,
                "authors":  authors,
                "journal":  journal,
                "year":     year,
                "abstract": abstract,
                "doi":      doi,
                "url":      f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",

                # ── Legacy taxonomy (V1–V3, preserved) ───────────────────
                "topics":     "|".join(legacy_topics),  # keyword-based, approximate

                # ── MeSH extraction (V1.5, preserved) ────────────────────
                "mesh_terms": "|".join(mesh_terms),     # NLM-assigned, authoritative

                # ── Three-axis taxonomy (V3.1, new) ───────────────────────
                "clinical_topic_tags": "|".join(taxonomy["clinical_topic_tags"]),
                "method_tags":         "|".join(taxonomy["method_tags"]),
                "domain_tags":         "|".join(taxonomy["domain_tags"]),
                "topic_confidence":    taxonomy["topic_confidence"],
            })

        except Exception as e:
            print(f"[WARNING] Skipped one article due to parse error: {e}")
            continue

    print(f"[Parser] Successfully parsed {len(articles)} articles.")
    return articles
