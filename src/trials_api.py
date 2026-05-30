"""
trials_api.py
-------------
ClinicalTrials.gov API v2 module for NeuroLit Miner.

Queries the modern ClinicalTrials.gov REST API (v2, launched 2023) which
returns clean JSON — no XML parsing needed. Free, no API key required.

API documentation: https://clinicaltrials.gov/data-api/api

Fields retrieved per trial:
  - NCT ID          : unique trial identifier (e.g. NCT04573946)
  - title           : official trial title
  - status          : recruitment status (Recruiting, Completed, etc.)
  - phase           : trial phase (Phase 1, Phase 2/3, N/A, etc.)
  - condition       : medical condition(s) being studied
  - intervention    : drug/device/procedure being tested
  - sponsor         : lead organization
  - enrollment      : target or actual enrollment count
  - start_date      : trial start date
  - completion_date : primary completion date
  - primary_outcome : primary endpoint description
  - locations       : countries where trial is running
  - url             : direct ClinicalTrials.gov link

Clinical context:
  Cross-referencing published literature (PubMed) with active trials
  (ClinicalTrials.gov) is standard in systematic reviews and evidence
  synthesis. This module makes that cross-reference programmatic.
"""

import requests
import time
from typing import Optional

# ClinicalTrials.gov API v2 base URL
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"

# Rate limit: be a polite API citizen (no published limit, 1 req/sec is safe)
RATE_LIMIT_DELAY = 1.0


def search_trials(condition: str,
                  intervention: Optional[str] = None,
                  status: Optional[str] = None,
                  max_results: int = 20) -> list[dict]:
    """
    Search ClinicalTrials.gov and return a list of structured trial dicts.

    Args:
        condition:    medical condition (e.g. "glioblastoma", "meningioma")
        intervention: optional filter (e.g. "surgery", "temozolomide", "AI")
        status:       optional recruitment status filter:
                      "RECRUITING", "COMPLETED", "ACTIVE_NOT_RECRUITING",
                      "NOT_YET_RECRUITING", "TERMINATED"
        max_results:  maximum number of trials to retrieve (default 20, max 50)

    Returns:
        List of trial dicts, each containing structured fields for DB storage

    Example:
        trials = search_trials("glioblastoma", intervention="surgery", max_results=25)
    """
    max_results = min(max_results, 50)  # hard cap for UI responsiveness

    # Build query string
    # CT.gov v2 uses 'query.cond' for condition and 'query.intr' for intervention
    params = {
        "query.cond": condition,
        "pageSize":   max_results,
        "format":     "json",
        # Request specific fields to keep response lean
        "fields": "|".join([
            "NCTId", "BriefTitle", "OverallStatus", "Phase",
            "Condition", "InterventionName", "LeadSponsorName",
            "EnrollmentCount", "StartDate", "PrimaryCompletionDate",
            "PrimaryOutcomeMeasure", "LocationCountry",
        ]),
    }

    if intervention:
        params["query.intr"] = intervention

    if status:
        params["filter.overallStatus"] = status

    print(f"[Trials] Searching ClinicalTrials.gov: condition='{condition}'"
          + (f", intervention='{intervention}'" if intervention else "")
          + (f", status='{status}'" if status else "")
          + f" (max {max_results})")

    try:
        response = requests.get(CT_BASE, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

    except requests.exceptions.RequestException as e:
        print(f"[ERROR] ClinicalTrials.gov request failed: {e}")
        return []

    except ValueError as e:
        print(f"[ERROR] JSON decode failed: {e}")
        return []

    studies = data.get("studies", [])
    total   = data.get("totalCount", "unknown")
    print(f"[Trials] Found {total} total trials. Parsing {len(studies)} records.")

    time.sleep(RATE_LIMIT_DELAY)
    return [_parse_study(s) for s in studies]


def _parse_study(study: dict) -> dict:
    """
    Parse a single ClinicalTrials.gov v2 study JSON object into a flat dict.

    The v2 API nests data under protocolSection > various modules.
    We flatten the fields we need into a clean dict for DB storage.

    Args:
        study: raw study dict from the API response

    Returns:
        Flat dict with standardized field names
    """
    # Navigate the nested JSON structure
    proto      = study.get("protocolSection", {})
    id_mod     = proto.get("identificationModule", {})
    status_mod = proto.get("statusModule", {})
    desc_mod   = proto.get("descriptionModule", {})
    design_mod = proto.get("designModule", {})
    sponsor_mod= proto.get("sponsorCollaboratorsModule", {})
    outcomes   = proto.get("outcomesModule", {})
    contacts   = proto.get("contactsLocationsModule", {})
    cond_mod   = proto.get("conditionsModule", {})
    interv_mod = proto.get("armsInterventionsModule", {})

    # NCT ID and URL
    nct_id = id_mod.get("nctId", "")
    url    = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""

    # Title: prefer brief title
    title  = id_mod.get("briefTitle", "") or id_mod.get("officialTitle", "")

    # Status
    overall_status = status_mod.get("overallStatus", "Unknown")

    # Dates
    start_date      = status_mod.get("startDateStruct", {}).get("date", "")
    completion_date = status_mod.get("primaryCompletionDateStruct", {}).get("date", "")

    # Phase — stored as list, join to string
    phases = design_mod.get("phases", [])
    phase  = ", ".join(phases) if phases else "N/A"

    # Enrollment
    enrollment_info  = design_mod.get("enrollmentInfo", {})
    enrollment_count = str(enrollment_info.get("count", "")) if enrollment_info else ""

    # Conditions (list → pipe-separated)
    conditions = cond_mod.get("conditions", [])
    condition_str = " | ".join(conditions) if conditions else ""

    # Interventions (list of dicts → extract names)
    interventions = interv_mod.get("interventions", [])
    interv_names  = [i.get("name", "") for i in interventions if i.get("name")]
    interv_str    = " | ".join(interv_names[:5]) if interv_names else ""  # cap at 5

    # Lead sponsor
    lead_sponsor = sponsor_mod.get("leadSponsor", {}).get("name", "")

    # Primary outcome (first one)
    primary_outcomes = outcomes.get("primaryOutcomes", [])
    primary_outcome  = primary_outcomes[0].get("measure", "") if primary_outcomes else ""

    # Countries (unique, sorted)
    locations  = contacts.get("locations", [])
    countries  = sorted(set(
        loc.get("country", "") for loc in locations if loc.get("country")
    ))
    country_str = " | ".join(countries) if countries else ""

    # Brief summary (from description module)
    summary = desc_mod.get("briefSummary", "")
    # Truncate long summaries for DB storage
    if len(summary) > 1000:
        summary = summary[:997] + "..."

    return {
        "nct_id":           nct_id,
        "title":            title,
        "status":           overall_status,
        "phase":            phase,
        "condition":        condition_str,
        "intervention":     interv_str,
        "sponsor":          lead_sponsor,
        "enrollment":       enrollment_count,
        "start_date":       start_date,
        "completion_date":  completion_date,
        "primary_outcome":  primary_outcome,
        "countries":        country_str,
        "summary":          summary,
        "url":              url,
        "search_condition": "",   # filled by caller for provenance tracking
        "date_added":       "",   # filled by database.py on insert
    }


def get_trial_details(nct_id: str) -> Optional[dict]:
    """
    Fetch full details for a single trial by NCT ID.
    Useful for expanding a summary record to full protocol.

    Args:
        nct_id: trial identifier (e.g. "NCT04573946")

    Returns:
        Parsed trial dict, or None if not found
    """
    try:
        response = requests.get(f"{CT_BASE}/{nct_id}", timeout=15)
        response.raise_for_status()
        study = response.json()
        return _parse_study(study)
    except Exception as e:
        print(f"[ERROR] Could not fetch trial {nct_id}: {e}")
        return None
