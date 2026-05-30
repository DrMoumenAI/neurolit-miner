"""
parser.py
---------
Parses PubMed XML responses into structured Python dictionaries.

PubMed's efetch returns PubmedArticleSet XML. Each article contains:
  - MedlineCitation > PMID
  - MedlineCitation > Article > ArticleTitle
  - MedlineCitation > Article > Abstract > AbstractText
  - MedlineCitation > Article > AuthorList > Author
  - MedlineCitation > Article > Journal > Title
  - MedlineCitation > Article > Journal > JournalIssue > PubDate
  - MedlineCitation > MeshHeadingList (MeSH terms — extracted as of V1.5)

This module:
  1. Extracts MeSH headings directly from PubMed XML (structured biomedical ontology)
  2. Assigns keyword-based topic tags (fast, customizable, acknowledged as approximate)

MeSH terms are the authoritative NLM-assigned subject headings. They are:
  - hierarchical (disease → subtype → specific condition)
  - consistent across articles regardless of author terminology
  - the foundation for semantic filtering, co-occurrence analysis, and topic graphs
  - already present in the XML we fetch — zero additional API calls needed

Current limitation (honest): keyword topic tagging is still approximate.
MeSH terms are the ground truth; topic tags are a fast navigation layer.
"""

import xml.etree.ElementTree as ET
from typing import Optional


# ── Topic taxonomy ──────────────────────────────────────────────────────────
# Maps a topic label to a list of keywords (case-insensitive substring match).
# Edit or extend this dict to customize your surveillance categories.

TOPIC_KEYWORDS = {
    "glioblastoma":         ["glioblastoma", "gbm", "glioma", "high-grade glioma", "astrocytoma"],
    "meningioma":           ["meningioma"],
    "spine":                ["spine", "spinal", "vertebral", "disc herniation", "spondylosis",
                             "myelopathy", "cord compression"],
    "epilepsy_surgery":     ["epilepsy surgery", "temporal lobectomy", "seizure surgery",
                             "stereoEEG", "SEEG", "resective epilepsy"],
    "vascular":             ["aneurysm", "AVM", "arteriovenous", "subarachnoid hemorrhage",
                             "cavernoma", "cerebrovascular"],
    "AI_ML":                ["machine learning", "deep learning", "artificial intelligence",
                             "neural network", "random forest", "convolutional", "transformer",
                             "large language model", "LLM", "NLP"],
    "intraoperative_tech":  ["awake craniotomy", "intraoperative MRI", "iMRI",
                             "fluorescence-guided", "5-ALA", "neuronavigation",
                             "ultrasound-guided"],
    "global_neurosurgery":  ["global neurosurgery", "low-income", "LMIC", "sub-saharan",
                             "workforce", "access to care", "task sharing", "neurosurgical capacity"],
    "outcomes_research":    ["outcome", "prognosis", "survival", "quality of life", "QOL",
                             "NSQIP", "complication", "morbidity", "mortality", "readmission"],
    "radiosurgery":         ["radiosurgery", "gamma knife", "cyberknife", "stereotactic",
                             "SRS", "SBRT", "LINAC"],
    "pediatric":            ["pediatric", "paediatric", "childhood", "neonatal", "hydrocephalus",
                             "craniosynostosis"],
    "trauma":               ["traumatic brain injury", "TBI", "head trauma", "subdural",
                             "epidural hematoma", "craniectomy"],
}


def assign_topics(title: str, abstract: str) -> list[str]:
    """
    Assign topic tags to an article based on keyword matching.
    An article can belong to multiple topics.

    Args:
        title:    article title string
        abstract: abstract text string

    Returns:
        List of matching topic labels (empty list if none match)
    """
    combined = (title + " " + abstract).lower()
    matched = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw.lower() in combined for kw in keywords):
            matched.append(topic)
    return matched if matched else ["uncategorized"]


def _get_text(element, path: str, default: str = "") -> str:
    """Safe XML element text extraction with fallback."""
    node = element.find(path)
    if node is not None and node.text:
        return node.text.strip()
    return default


def _extract_authors(article_node) -> str:
    """Extract formatted author list as 'LastName FM, LastName FM, ...'"""
    authors = []
    author_list = article_node.find(".//AuthorList")
    if author_list is None:
        return "N/A"

    for author in author_list.findall("Author"):
        last  = _get_text(author, "LastName")
        fore  = _get_text(author, "ForeName")
        initials = _get_text(author, "Initials")

        if last:
            name = last
            if fore:
                # Use first letter of each forename word as initials
                name += " " + "".join(w[0] for w in fore.split() if w)
            elif initials:
                name += " " + initials
            authors.append(name)

    if not authors:
        # Handle collective names (consortia, groups)
        collective = article_node.find(".//CollectiveName")
        if collective is not None and collective.text:
            return collective.text.strip()

    return ", ".join(authors) if authors else "N/A"


def _extract_year(article_node) -> str:
    """
    Extract publication year. PubMed stores dates inconsistently —
    we check multiple locations in order of reliability.
    """
    # 1. PubDate > Year (most common)
    year = _get_text(article_node, ".//PubDate/Year")
    if year:
        return year

    # 2. PubDate > MedlineDate (fallback: "2023 Jan-Feb" format)
    medline_date = _get_text(article_node, ".//PubDate/MedlineDate")
    if medline_date:
        # Extract first 4-digit year from the string
        import re
        match = re.search(r'\b(19|20)\d{2}\b', medline_date)
        if match:
            return match.group()

    # 3. ArticleDate > Year (epub date)
    year = _get_text(article_node, ".//ArticleDate/Year")
    if year:
        return year

    return "N/A"


def _extract_abstract(article_node) -> str:
    """
    Extract abstract text. Handles structured abstracts (multiple AbstractText
    elements with Label attributes, e.g. BACKGROUND, METHODS, RESULTS).
    """
    abstract_node = article_node.find(".//Abstract")
    if abstract_node is None:
        return "No abstract available."

    texts = []
    for abstract_text in abstract_node.findall("AbstractText"):
        label = abstract_text.get("Label", "")
        text  = abstract_text.text or ""
        if label:
            texts.append(f"{label}: {text.strip()}")
        else:
            texts.append(text.strip())

    return " ".join(texts) if texts else "No abstract available."



def _extract_mesh(medline_node) -> list[str]:
    """
    Extract MeSH (Medical Subject Headings) terms from a MedlineCitation node.

    PubMed XML structure for MeSH:
        MedlineCitation
          └── MeshHeadingList
                └── MeshHeading (one per term)
                      ├── DescriptorName  (main heading, e.g. "Glioblastoma")
                      └── QualifierName   (subheading, e.g. "surgery", "diagnosis")

    We extract DescriptorName only (not qualifiers) to keep terms clean and
    suitable for frequency analysis and co-occurrence mapping.

    MeSH terms are NLM-assigned after peer review — they are authoritative,
    consistent, and ontology-structured. Unlike keyword tags, they do not depend
    on author terminology and work across languages.

    Args:
        medline_node: the MedlineCitation XML element

    Returns:
        List of MeSH descriptor strings (empty list if none assigned)
        Example: ["Glioblastoma", "Brain Neoplasms", "Neurosurgery",
                  "Machine Learning", "Prognosis"]
    """
    mesh_list = medline_node.find("MeshHeadingList")
    if mesh_list is None:
        # MeSH terms are only assigned after NLM indexing (can take weeks
        # after publication). Very recent articles will have an empty list.
        return []

    terms = []
    for heading in mesh_list.findall("MeshHeading"):
        descriptor = heading.find("DescriptorName")
        if descriptor is not None and descriptor.text:
            terms.append(descriptor.text.strip())

    return terms

def parse_xml(xml_string: str) -> list[dict]:
    """
    Parse a PubMed efetch XML response into a list of article dictionaries.

    Each dict contains:
        pmid, title, authors, journal, year, abstract, topics, mesh_terms, doi

    Args:
        xml_string: raw XML string from fetch_records()

    Returns:
        List of article dicts (empty list on parse error)
    """
    if not xml_string or not xml_string.strip():
        return []

    articles = []

    # NCBI returns one XML document per batch. When fetch_records() joins
    # multiple batches, the result has repeated XML declarations and root
    # elements — invalid XML. Fix: strip declarations and wrap in one root.
    import re
    cleaned = re.sub(r'<\?xml[^?]*\?>', '', xml_string)          # strip <?xml ...?> headers
    cleaned = re.sub(r'</PubmedArticleSet>\s*<PubmedArticleSet>', # merge adjacent root elements
                     '', cleaned)
    cleaned = cleaned.strip()
    # If there's still no single root, wrap defensively
    if not cleaned.startswith('<PubmedArticleSet'):
        cleaned = f'<PubmedArticleSet>{cleaned}</PubmedArticleSet>'

    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as e:
        print(f"[ERROR] XML parse failed: {e}")
        return []

    for article_set in root.iter("PubmedArticle"):
        try:
            medline  = article_set.find("MedlineCitation")
            article  = medline.find("Article") if medline is not None else None

            if medline is None or article is None:
                continue

            pmid     = _get_text(medline, "PMID")
            title    = _get_text(article, "ArticleTitle")
            journal  = _get_text(article, ".//Journal/Title")
            year     = _extract_year(article)
            authors  = _extract_authors(article)
            abstract = _extract_abstract(article)

            # MeSH terms — extracted from MeshHeadingList on MedlineCitation
            # Note: medline node is the parent, not the article node
            mesh_terms = _extract_mesh(medline)

            # DOI — stored in ELocationID with EIdType="doi"
            doi = ""
            for loc in article.findall(".//ELocationID"):
                if loc.get("EIdType") == "doi" and loc.text:
                    doi = loc.text.strip()
                    break

            topics = assign_topics(title, abstract)

            articles.append({
                "pmid":       pmid,
                "title":      title,
                "authors":    authors,
                "journal":    journal,
                "year":       year,
                "abstract":   abstract,
                "topics":     "|".join(topics),      # keyword-based, approximate
                "mesh_terms": "|".join(mesh_terms),  # NLM-assigned, authoritative
                "doi":        doi,
                "url":        f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            })

        except Exception as e:
            print(f"[WARNING] Skipped one article due to parse error: {e}")
            continue

    print(f"[Parser] Successfully parsed {len(articles)} articles.")
    return articles
