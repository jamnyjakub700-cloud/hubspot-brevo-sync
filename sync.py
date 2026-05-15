#!/usr/bin/env python3
"""
HubSpot → Brevo sync
─────────────────────
Syncs contacts from active HubSpot deals to Brevo
with automatic language tagging (CZ / EN).

Run:    python sync.py
Cron (daily at 7:00):  0 7 * * * cd /path/to/script && python sync.py
"""

import os
import re
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION — adjust to your needs
# ──────────────────────────────────────────────────────────────────────

HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")
BREVO_API_KEY   = os.getenv("BREVO_API_KEY")

# Brevo list IDs (find in Brevo → Contacts → Lists → click list → ID in URL)
BREVO_LIST_CZ = int(os.getenv("BREVO_LIST_CZ", "0"))
BREVO_LIST_EN = int(os.getenv("BREVO_LIST_EN", "0"))

# Email domains → CZ newsletter
CZ_DOMAINS = {".cz", ".sk"}

# HubSpot deal stages to SKIP (internal stage names from HubSpot)
# View them via: GET /crm/v3/pipelines/deals
EXCLUDE_STAGES = {"closedlost"}

HUBSPOT_BASE = "https://api.hubapi.com"
BREVO_BASE   = "https://api.brevo.com/v3"

# ──────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────

def hs_headers() -> dict:
    return {
        "Authorization": f"Bearer {HUBSPOT_API_KEY}",
        "Content-Type": "application/json",
    }


def brevo_headers() -> dict:
    return {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
    }


def detect_language(email: str, country: str = "", hs_language: str = "") -> str:
    """
    Determine contact language (CZ or EN) by priority:
      1. hs_language field in HubSpot (if set manually)
      2. country field in HubSpot
      3. Email domain TLD (.cz / .sk → CZ)
      4. Default: EN
    """
    Určí jazyk kontaktu (CZ nebo EN) podle priority:
      1. Pole 'hs_language' v HubSpotu (pokud ho nastavíš manuálně)
      2. Pole 'country' v HubSpotu
      3. Doménová koncovka e-mailu (.cz / .sk → CZ)
      4. Výchozí: EN

    Jakmile se rozhodneš pro konkrétní HubSpot property,
    stačí upravit jen tuto funkci — zbytek skriptu zůstane stejný.
    """
    # 1. Explicit language field in HubSpot
    if hs_language:
        lang = hs_language.upper()
        if lang in {"CS", "CZ", "SK"}:
            return "CZ"
        if lang:
            return "EN"

    # 2. Contact country
    if country:
        c = country.strip().upper()
        if c in {"CZ", "CS", "CZECH", "CZECHIA", "CZECH REPUBLIC", "SK", "SLOVAKIA"}:
            return "CZ"
        if c:
            return "EN"

    # 3. Email domain TLD
    match = re.search(r"\.[a-z]{2,}$", email.lower())
    if match and match.group() in CZ_DOMAINS:
        return "CZ"

    # 4. Default
    return "EN"


# ──────────────────────────────────────────────────────────────────────
# HUBSPOT — read data
# ──────────────────────────────────────────────────────────────────────

def get_all_pipeline_deal_ids() -> list[str]:
    """Return IDs of all deals in pipeline (except closedlost)."""
    deal_ids = []
    after = None

    while True:
        params: dict = {
            "limit": 100,
            "properties": "dealname,dealstage",
        }
        if after:
            params["after"] = after

        resp = requests.get(
            f"{HUBSPOT_BASE}/crm/v3/objects/deals",
            headers=hs_headers(),
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        for deal in data.get("results", []):
            stage = (deal.get("properties") or {}).get("dealstage", "").lower()
            if stage not in EXCLUDE_STAGES:
                deal_ids.append(deal["id"])

        paging = data.get("paging", {}).get("next", {})
        after = paging.get("after")
        if not after:
            break

        time.sleep(0.1)  # HubSpot rate limit: 100 req/10 s

    log.info(f"HubSpot: found {len(deal_ids)} deals in pipeline")
    return deal_ids


def get_contact_ids_for_deal(deal_id: str) -> list[str]:
    """Return IDs of contacts associated with a given deal."""
    resp = requests.get(
        f"{HUBSPOT_BASE}/crm/v3/objects/deals/{deal_id}/associations/contacts",
        headers=hs_headers(),
        timeout=15,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return [r["id"] for r in resp.json().get("results", [])]


def get_contact_details(contact_id: str) -> dict:
    """Load email, name, country, and language field of a contact."""
    resp = requests.get(
        f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{contact_id}",
        headers=hs_headers(),
        params={"properties": "email,firstname,lastname,country,hs_language"},
        timeout=15,
    )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return resp.json().get("properties") or {}


# ──────────────────────────────────────────────────────────────────────
# BREVO — write data
# ──────────────────────────────────────────────────────────────────────

def upsert_brevo_contact(
    email: str,
    firstname: str,
    lastname: str,
    language: str,
) -> None:
    """
    Create or update a contact in Brevo.
    Adds it to the correct list (CZ or EN) and sets the LANGUAGE attribute.
    updateEnabled=True ensures existing contacts are updated, not duplicated.
    """    Vytvoří nebo aktualizuje kontakt v Brevo.
    Přidá ho do správného listu (CZ nebo EN) a nastaví atribut LANGUAGE.
    updateEnabled=True zajistí, že existující kontakt se jen aktualizuje,
    nikoli zduplikuje.
    """
    list_id = BREVO_LIST_CZ if language == "CZ" else BREVO_LIST_EN

    payload = {
        "email": email,
        "attributes": {
            "FIRSTNAME": firstname,
            "LASTNAME":  lastname,
            "LANGUAGE":  language,      # custom attribute — create it in Brevo first
        },
        "listIds": [list_id],
        "updateEnabled": True,
    }

    resp = requests.post(
        f"{BREVO_BASE}/contacts",
        headers=brevo_headers(),
        json=payload,
        timeout=15,
    )

    if resp.status_code in (200, 201):
        log.info(f"  ✓ CREATED  {email:45s} → [{language}]")
    elif resp.status_code == 204:
        log.info(f"  ↻ UPDATED  {email:45s} → [{language}]")
    else:
        log.warning(f"  ✗ ERROR    {email} | {resp.status_code} | {resp.text[:120]}")


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("══════════════════════════════════════════════")
    log.info("  HubSpot → Brevo sync")
    log.info("══════════════════════════════════════════════")

    # Check configuration
    errors = []
    if not HUBSPOT_API_KEY:
        errors.append("Missing HUBSPOT_API_KEY in .env")
    if not BREVO_API_KEY:
        errors.append("Missing BREVO_API_KEY in .env")
    if BREVO_LIST_CZ == 0:
        errors.append("Missing BREVO_LIST_CZ in .env (Brevo list ID)")
    if BREVO_LIST_EN == 0:
        errors.append("Missing BREVO_LIST_EN in .env (Brevo list ID)")
    if errors:
        for e in errors:
            log.error(f"  ✗ {e}")
        return

    # Load deals
    deal_ids = get_all_pipeline_deal_ids()
    if not deal_ids:
        log.info("No deals to process.")
        return

    # Process contacts
    seen: set[str] = set()  # deduplication across deals
    synced = skipped_no_email = skipped_dupe = 0

    for deal_id in deal_ids:
        contact_ids = get_contact_ids_for_deal(deal_id)

        for contact_id in contact_ids:
            if contact_id in seen:
                skipped_dupe += 1
                continue
            seen.add(contact_id)

            props   = get_contact_details(contact_id)
            email   = (props.get("email") or "").strip().lower()

            if not email:
                skipped_no_email += 1
                continue

            firstname   = props.get("firstname") or ""
            lastname    = props.get("lastname")  or ""
            country     = props.get("country")   or ""
            hs_language = props.get("hs_language") or ""

            language = detect_language(email, country, hs_language)
            upsert_brevo_contact(email, firstname, lastname, language)
            synced += 1

            time.sleep(0.15)  # Brevo: ~10 req/s limit

    log.info("──────────────────────────────────────────────")
    log.info(f"  Synced: {synced}")
    log.info(f"  Skipped (duplicate): {skipped_dupe}")
    log.info(f"  Skipped (no email): {skipped_no_email}")
    log.info("══════════════════════════════════════════════")


if __name__ == "__main__":
    main()
