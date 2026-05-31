"""
summarizer.py
-------------
NeuroLit Miner V3 — Provider Abstraction Layer.

This module is the ONLY place in the codebase that knows about LLM backends.
Everything else calls:

    from summarizer import get_summarizer
    s = get_summarizer()
    result = s.summarize(articles, filters)

No other module should import anthropic, openai, or any LLM SDK directly.

Architecture decision:
    The retrieval, storage, MeSH extraction, co-occurrence analytics,
    ClinicalTrials integration, and export systems are completely independent
    of this layer. NeuroLit Miner is fully functional without any LLM backend.
    The summarizer is an optional enhancement layer, not a core dependency.

Supported backends:
    mock        — deterministic keyword analysis, no API, no cost (default)
    ollama      — local LLM via Ollama, free, runs on your machine
    anthropic   — Anthropic Claude API (requires ANTHROPIC_API_KEY)
    openai      — OpenAI API (requires OPENAI_API_KEY)
    openrouter  — OpenRouter API, free tier available (requires OPENROUTER_API_KEY)

Graceful fallback:
    If the requested backend fails (missing key, import error, connection error),
    the system falls back to mock mode and logs a clear message.
    The application never crashes due to a missing LLM backend.

Extensibility:
    To add a new backend:
    1. Subclass BaseSummarizer
    2. Implement summarize(articles, filters) -> str
    3. Register it in PROVIDER_REGISTRY at the bottom of this file
    No other file needs to change.

Future modules that will use this layer:
    - PICO extraction      (extract Population/Intervention/Comparator/Outcome)
    - Evidence grading     (classify study quality)
    - Research gap detection
    - Topic synthesis
    - Causal analysis
"""

import os
import sys
from abc import ABC, abstractmethod
from collections import Counter


# ── Configuration ─────────────────────────────────────────────────────────────

# Default provider. Change here or pass --provider on CLI.
# Anthropic is intentionally NOT the default — the platform must work without it.
DEFAULT_PROVIDER = os.environ.get("NEUROLIT_PROVIDER", "mock")

# Minimum articles before synthesis is considered meaningful
MIN_ARTICLES_WARN = 3


# ── Base class ────────────────────────────────────────────────────────────────

class BaseSummarizer(ABC):
    """
    Abstract base class for all summarizer backends.

    Every backend must implement summarize() and nothing else is required.
    The structured output format (sections 1–4) is enforced here at the base
    level so all providers produce consistent output regardless of backend.

    Future modules (PICO extractor, evidence grader, gap detector) will
    follow the same pattern — subclass a base, implement one method.
    """

    @abstractmethod
    def summarize(self, articles: list[dict], filters: dict) -> str:
        """
        Generate a structured markdown summary from a list of article dicts.

        Args:
            articles: list of dicts from database.query_articles()
                      Each dict has: pmid, title, authors, journal, year,
                      abstract, topics, mesh_terms, url
            filters:  dict of filters applied (topic, keyword, year_from, year_to)
                      Used for context framing only.

        Returns:
            Markdown string with sections:
              ## 1. Current State of the Field
              ## 2. Dominant Methodologies
              ## 3. Key Findings
              ## 4. Research Gaps

        Raises:
            Should NOT raise — handle errors internally and return a
            fallback string. Callers should never crash due to LLM failure.
        """
        pass

    @property
    def name(self) -> str:
        """Human-readable provider name for display and logging."""
        return self.__class__.__name__.replace("Summarizer", "").lower()

    def build_evidence_block(self, articles: list[dict]) -> str:
        """
        Format articles into a numbered evidence block for LLM prompts.
        Shared across all LLM-based providers — single source of truth
        for how evidence is presented to any model.

        Design principle: articles are injected verbatim from the database.
        No information is added or inferred at this stage.
        """
        lines = []
        for i, a in enumerate(articles, 1):
            mesh = (a.get("mesh_terms") or "").replace("|", ", ")
            lines.append(
                f"[{i}] PMID: {a.get('pmid', 'N/A')}\n"
                f"    Title: {(a.get('title') or '').strip()}\n"
                f"    Journal: {(a.get('journal') or '').strip()} "
                f"({a.get('year', 'N/A')})\n"
                f"    MeSH: {mesh or 'Not indexed'}\n"
                f"    Abstract: {(a.get('abstract') or 'No abstract').strip()}\n"
            )
        return "\n".join(lines)

    def build_llm_prompt(self, articles: list[dict], filters: dict) -> str:
        """
        Shared prompt template for all LLM backends.
        Enforces citation grounding, no hallucination, and structured output.
        Centralised here so prompt changes propagate to all LLM providers.
        """
        filter_desc = " | ".join(
            f"{k}: {v}" for k, v in filters.items() if v
        ) or "all stored articles"

        return f"""You are an expert biomedical research assistant synthesizing \
neurosurgical literature for a physician-scientist.

You have {len(articles)} articles from a local PubMed database.
Search filters: {filter_desc}

STRICT RULES — follow exactly:
1. Only use information explicitly present in the abstracts below.
2. Never invent or fabricate citations or findings.
3. Cite articles by PMID inline: (PMID: 12345678).
4. If a section lacks evidence, write: "Insufficient data in current corpus."
5. Do not add general medical knowledge beyond what the abstracts support.
6. This output will be labeled as AI-assisted synthesis, not a systematic review.

ARTICLES:
{self.build_evidence_block(articles)}

Generate a structured synthesis with EXACTLY these four sections in markdown:

## 1. Current State of the Field
Summarize what these articles reveal about the current state of this research area.

## 2. Dominant Methodologies
What study designs and technical approaches appear most frequently? Cite PMIDs.

## 3. Key Findings
Most important findings across the articles. Cite PMIDs for every major claim.

## 4. Research Gaps
Limitations and future directions mentioned by authors. Cite PMIDs where explicit.
"""


# ── Mock backend ──────────────────────────────────────────────────────────────

class MockSummarizer(BaseSummarizer):
    """
    Deterministic evidence summary from stored metadata.
    No API, no cost, no setup. Always works.

    Uses frequency analysis of MeSH terms, topics, study design keywords,
    and outcome keywords to produce a structured research summary.

    This is not prose generation — it is structured data extraction
    presented in narrative form. Honest, reproducible, citable.

    When to use: prototyping, testing, offline use, low-cost demos.
    Limitation: does not read or understand abstract content semantically.
    """

    # Study design keywords for abstract scanning
    DESIGN_KEYWORDS = {
        "retrospective cohort":   ["retrospective"],
        "prospective study":      ["prospective"],
        "randomized trial":       ["randomized", "randomised", "RCT"],
        "machine learning / AI":  ["machine learning", "deep learning",
                                   "neural network", "random forest",
                                   "convolutional", "artificial intelligence"],
        "systematic review":      ["meta-analysis", "systematic review"],
        "imaging study":          ["MRI", "CT scan", "imaging", "neuroimaging"],
        "case series":            ["case series", "case report"],
    }

    # Outcome domain keywords
    OUTCOME_KEYWORDS = {
        "survival / prognosis":   ["survival", "prognosis", "overall survival"],
        "surgical outcomes":      ["outcome", "complication", "morbidity",
                                   "mortality"],
        "tumor control":          ["recurrence", "extent of resection",
                                   "local control"],
        "functional outcomes":    ["quality of life", "functional",
                                   "neurological"],
        "diagnostic accuracy":    ["sensitivity", "specificity", "accuracy",
                                   "AUC", "ROC"],
    }

    # Limitation / gap keywords
    GAP_KEYWORDS = {
        "small sample size":    ["small sample", "limited sample", "underpowered",
                                 "larger cohort"],
        "retrospective bias":   ["retrospective", "selection bias"],
        "lack of randomization":["prospective", "randomized trial", "RCT needed"],
        "short follow-up":      ["longer follow", "short follow-up"],
        "single-center":        ["single center", "single institution",
                                 "multicenter"],
        "external validation":  ["validation", "external validation",
                                 "generalizab"],
    }

    def summarize(self, articles: list[dict], filters: dict) -> str:
        n = len(articles)
        years = sorted(set(
            a["year"] for a in articles
            if (a.get("year") or "").isdigit()
        ))
        yr = f"{years[0]}–{years[-1]}" if len(years) > 1 else (
            years[0] if years else "N/A")

        mesh_counts, mesh_indexed = self._count_mesh(articles)
        design_counts             = self._count_keywords(articles,
                                                         self.DESIGN_KEYWORDS)
        outcome_counts            = self._count_keywords(articles,
                                                         self.OUTCOME_KEYWORDS)
        gap_counts, gap_pmids     = self._count_gaps(articles)
        topic_counts              = self._count_topics(articles)
        journal_counts            = Counter(
            a["journal"].strip() for a in articles
            if a.get("journal", "").strip()
        )

        top_mesh    = mesh_counts.most_common(8)
        top_topics  = topic_counts.most_common(5)
        top_journals= journal_counts.most_common(4)
        top_designs = design_counts.most_common(5)
        ai_articles = [
            a for a in articles if design_counts.get("machine learning / AI", 0) > 0
            and any(kw in (
                (a.get("title","") + " " + a.get("abstract","")).lower())
                for kw in self.DESIGN_KEYWORDS["machine learning / AI"])
        ]

        def cite(pmids):
            return " ".join(f"(PMID: {p})" for p in pmids[:3] if p)

        sec1 = self._section_1(n, yr, mesh_indexed, top_mesh, top_topics,
                                top_journals, ai_articles, filters)
        sec2 = self._section_2(n, top_designs, ai_articles)
        sec3 = self._section_3(n, articles, outcome_counts)
        sec4 = self._section_4(gap_counts, gap_pmids, cite)

        note = (
            "\n\n---\n"
            "> **Mock mode:** This summary uses keyword-frequency analysis on "
            "stored metadata — not semantic language understanding. "
            "For narrative synthesis, use `--provider ollama` (free) or "
            "`--provider anthropic`.\n"
        )

        return "\n\n".join([sec1, sec2, sec3, sec4]) + note

    # ── Section builders ──────────────────────────────────────────────────────

    def _section_1(self, n, yr, mesh_indexed, top_mesh, top_topics,
                   top_journals, ai_articles, filters):
        mesh_str    = ", ".join(t for t, _ in top_mesh) or "not available"
        topic_str   = ", ".join(
            f"**{t}** ({c})" for t, c in top_topics[:4]) or "mixed"
        journal_str = ", ".join(
            f"*{j}*" for j, _ in top_journals[:3]) or "various journals"

        return (
            f"## 1. Current State of the Field\n\n"
            f"This corpus comprises **{n} articles** published between "
            f"**{yr}**. "
            f"NLM MeSH indexing ({mesh_indexed}/{n} articles indexed) "
            f"identifies the dominant subject headings as: {mesh_str}.\n\n"
            f"Topic classification shows concentration in: {topic_str}. "
            f"Publication venues include {journal_str}.\n\n"
            + (f"The corpus contains {len(ai_articles)} articles applying "
               f"machine learning or AI methods, indicating early-phase "
               f"computational integration into this domain."
               if ai_articles else
               "Computational AI approaches are not prominently represented "
               "in this corpus.")
        )

    def _section_2(self, n, top_designs, ai_articles):
        design_lines = "\n".join(
            f"- **{d}**: {c} articles" for d, c in top_designs
        ) or "- Mixed methodologies (keyword detection inconclusive)"

        return (
            f"## 2. Dominant Methodologies\n\n"
            f"Study design and methodology keywords detected across "
            f"{n} abstracts:\n\n"
            f"{design_lines}\n\n"
            f"> **Note:** Classification is keyword-based. Full-text review "
            f"required for definitive study design categorisation."
        )

    def _section_3(self, n, articles, outcome_counts):
        outcome_lines = "\n".join(
            f"- **{o}**: detected in {c} articles"
            for o, c in outcome_counts.most_common(5)
        ) or "- No dominant outcome pattern detected"

        recent = sorted(
            articles, key=lambda x: x.get("year", "0"), reverse=True)[:5]
        recent_refs = "\n".join(
            f"- {a.get('title','No title')[:75]}"
            f"{'…' if len(a.get('title','')) > 75 else ''} "
            f"(PMID: {a.get('pmid','N/A')}, {a.get('year','N/A')})"
            for a in recent
        )

        return (
            f"## 3. Key Findings\n\n"
            f"Outcome domains identified across {n} abstracts:\n\n"
            f"{outcome_lines}\n\n"
            f"Most recent articles in corpus:\n\n{recent_refs}\n\n"
            f"> **Mock mode limitation:** This section reflects keyword "
            f"detection, not semantic reading of findings. "
            f"Use an LLM provider for specific finding extraction."
        )

    def _section_4(self, gap_counts, gap_pmids, cite):
        if not gap_counts:
            gap_lines = "- No explicit limitation keywords detected."
        else:
            gap_lines = "\n".join(
                f"- **{g}**: flagged in {c} abstracts "
                f"{cite(gap_pmids.get(g, []))}"
                for g, c in gap_counts.most_common(6)
            )

        return (
            f"## 4. Research Gaps\n\n"
            f"Methodological limitations and gaps identified via abstract "
            f"keyword analysis:\n\n"
            f"{gap_lines}\n\n"
            f"> **Mock mode limitation:** Gap detection is keyword-based. "
            f"Use an LLM provider for nuanced gap analysis."
        )

    # ── Counting helpers ──────────────────────────────────────────────────────

    def _count_mesh(self, articles):
        counts, indexed = Counter(), 0
        for a in articles:
            s = (a.get("mesh_terms") or "").strip()
            if s:
                indexed += 1
                for t in s.split("|"):
                    t = t.strip()
                    if t:
                        counts[t] += 1
        return counts, indexed

    def _count_keywords(self, articles, keyword_map):
        counts = Counter()
        for a in articles:
            text = (
                (a.get("title") or "") + " " + (a.get("abstract") or "")
            ).lower()
            for label, kws in keyword_map.items():
                if any(kw.lower() in text for kw in kws):
                    counts[label] += 1
        return counts

    def _count_gaps(self, articles):
        counts, pmids = Counter(), {}
        for a in articles:
            text = (a.get("abstract") or "").lower()
            for gap, kws in self.GAP_KEYWORDS.items():
                if any(kw.lower() in text for kw in kws):
                    counts[gap] += 1
                    pmids.setdefault(gap, [])
                    if a.get("pmid"):
                        pmids[gap].append(a["pmid"])
        return counts, pmids

    def _count_topics(self, articles):
        counts = Counter()
        for a in articles:
            for t in (a.get("topics") or "").split("|"):
                t = t.strip()
                if t and t != "uncategorized":
                    counts[t] += 1
        return counts


# ── Ollama backend ────────────────────────────────────────────────────────────

class OllamaSummarizer(BaseSummarizer):
    """
    Local LLM via Ollama. Free, no API key, runs on your machine.
    Install: https://ollama.ai  then: ollama pull llama3
    """

    def __init__(self, model: str = "llama3",
                 host: str = "http://localhost:11434"):
        self.model = model
        self.host  = host

    def summarize(self, articles: list[dict], filters: dict) -> str:
        try:
            import requests
        except ImportError:
            return self._fallback("requests not installed: pip install requests")

        prompt = self.build_llm_prompt(articles, filters)
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=120
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
        except Exception as e:
            return self._fallback(
                f"Ollama unavailable: {e}\n"
                f"Start Ollama: ollama serve\n"
                f"Pull model:   ollama pull {self.model}"
            )

    def _fallback(self, msg):
        return (f"## Ollama Summarizer — Unavailable\n\n"
                f"{msg}\n\n"
                f"Falling back to mock mode would require re-running with "
                f"`--provider mock`.")


# ── Anthropic backend ─────────────────────────────────────────────────────────

class AnthropicSummarizer(BaseSummarizer):
    """
    Anthropic Claude API. Best prose quality.
    Requires: pip install anthropic
    Requires: ANTHROPIC_API_KEY environment variable
    """

    MODEL = "claude-opus-4-5"

    def summarize(self, articles: list[dict], filters: dict) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return self._no_key_message()
        try:
            import anthropic
        except ImportError:
            return ("## Anthropic — Package Missing\n\n"
                    "Run: `pip install anthropic`")

        prompt = self.build_llm_prompt(articles, filters)
        try:
            client  = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self.MODEL, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            return f"## Anthropic API Error\n\n{e}"

    def _no_key_message(self):
        return (
            "## Anthropic — API Key Not Found\n\n"
            "Set your key in PowerShell:\n"
            "```\n$env:ANTHROPIC_API_KEY = 'sk-ant-...'\n```\n"
            "Get a key at: https://console.anthropic.com/\n\n"
            "Or use a free provider: `--provider ollama` or `--provider mock`"
        )


# ── OpenAI backend ────────────────────────────────────────────────────────────

class OpenAISummarizer(BaseSummarizer):
    """
    OpenAI GPT API.
    Requires: pip install openai
    Requires: OPENAI_API_KEY environment variable
    """

    MODEL = "gpt-4o-mini"

    def summarize(self, articles: list[dict], filters: dict) -> str:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return ("## OpenAI — API Key Not Found\n\n"
                    "Set: `$env:OPENAI_API_KEY = 'sk-...'`")
        try:
            from openai import OpenAI
        except ImportError:
            return "## OpenAI — Package Missing\n\nRun: `pip install openai`"

        prompt = self.build_llm_prompt(articles, filters)
        try:
            client = OpenAI(api_key=api_key)
            resp   = client.chat.completions.create(
                model=self.MODEL, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"## OpenAI API Error\n\n{e}"


# ── OpenRouter backend ────────────────────────────────────────────────────────

class OpenRouterSummarizer(BaseSummarizer):
    """
    OpenRouter — access many models via one API, including free tiers.
    Free models: mistralai/mistral-7b-instruct, google/gemma-2-9b-it
    Requires: pip install openai
    Requires: OPENROUTER_API_KEY from openrouter.ai
    """

    MODEL = "mistralai/mistral-7b-instruct"

    def summarize(self, articles: list[dict], filters: dict) -> str:
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return ("## OpenRouter — API Key Not Found\n\n"
                    "Get a free key at: https://openrouter.ai/\n"
                    "Set: `$env:OPENROUTER_API_KEY = 'sk-or-...'`")
        try:
            from openai import OpenAI
        except ImportError:
            return "## OpenRouter — Package Missing\n\nRun: `pip install openai`"

        prompt = self.build_llm_prompt(articles, filters)
        try:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key
            )
            resp = client.chat.completions.create(
                model=self.MODEL, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"## OpenRouter API Error\n\n{e}"


# ── Provider registry ─────────────────────────────────────────────────────────
# Single place to register all providers.
# To add a new backend: subclass BaseSummarizer, implement summarize(),
# add one entry here. Nothing else changes.

PROVIDER_REGISTRY = {
    "mock":        MockSummarizer,
    "ollama":      OllamaSummarizer,
    "anthropic":   AnthropicSummarizer,
    "openai":      OpenAISummarizer,
    "openrouter":  OpenRouterSummarizer,
}

PROVIDER_DESCRIPTIONS = {
    "mock":       "Keyword analysis · no API · no cost · always works (default)",
    "ollama":     "Local LLM · free · ollama.ai · ollama pull llama3",
    "anthropic":  "Claude API · best quality · ANTHROPIC_API_KEY required",
    "openai":     "GPT API · OPENAI_API_KEY required",
    "openrouter": "Multi-model · free tier available · OPENROUTER_API_KEY",
}


def get_summarizer(provider: str = None, **kwargs) -> BaseSummarizer:
    """
    Factory function — returns a configured summarizer instance.
    This is the public API for the rest of the codebase.

    Usage:
        from summarizer import get_summarizer
        s = get_summarizer()                    # uses DEFAULT_PROVIDER
        s = get_summarizer("anthropic")          # specific provider
        result = s.summarize(articles, filters)

    Graceful fallback: if provider is unknown or instantiation fails,
    returns MockSummarizer so the application never crashes.

    Args:
        provider: provider name string (default: DEFAULT_PROVIDER env var or "mock")
        **kwargs: passed to provider constructor (e.g. model, host for Ollama)

    Returns:
        BaseSummarizer instance
    """
    name = (provider or DEFAULT_PROVIDER).lower().strip()

    if name not in PROVIDER_REGISTRY:
        print(f"[summarizer] Unknown provider '{name}'. "
              f"Falling back to mock.")
        print(f"[summarizer] Available: {', '.join(PROVIDER_REGISTRY)}")
        return MockSummarizer()

    try:
        cls = PROVIDER_REGISTRY[name]
        return cls(**kwargs)
    except Exception as e:
        print(f"[summarizer] Failed to initialise '{name}': {e}. "
              f"Falling back to mock.")
        return MockSummarizer()
