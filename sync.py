#!/usr/bin/env python3
"""
HubSpot → Brevo sync
─────────────────────
Syncs contacts from active HubSpot deals to Brevo
with automatic language tagging (CZ / EN).

Spuštění:    python sync.py
Cron (denně v 7:00):  0 7 * * * cd /path/to/script && python sync.py
"""

import os
import re
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# KONFIGURACE — upravte podle potřeby
# ──────────────────────────────────────────────────────────────────────

HUBSPOT_API_KEY = os.getenv("HUBSPOT_API_KEY")
BREVO_API_KEY   = os.getenv("BREVO_API_KEY")

# ID listů v Brevo (zjistíš v Brevo → Contacts → Lists → klikni na list → ID v URL)
BREVO_LIST_CZ = int(os.getenv("BREVO_LIST_CZ", "0"))
BREVO_LIST_EN = int(os.getenv("BREVO_LIST_EN", "0"))

# E-mailové domény → CZ newsletter
CZ_DOMAINS = {".cz", ".sk"}

# HubSpot deal stages, které se PŘESKOČÍ (interní názvy stages z HubSpotu)
# Zobraz si je přes: GET /crm/v3/pipelines/deals
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
# POMOCNÉ FUNKCE
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
    Určí jazyk kontaktu (CZ nebo EN) podle priority:
      1. Pole 'hs_language' v HubSpotu (pokud ho nastavíš manuálně)
      2. Pole 'country' v HubSpotu
      3. Doménová koncovka e-mailu (.cz / .sk → CZ)
      4. Výchozí: EN

    Jakmile se rozhodneš pro konkrétní HubSpot property,
    stačí upravit jen tuto funkci — zbytek skriptu zůstane stejný.
    """
    # 1. Explicitní jazykové pole v HubSpotu
    if hs_language:
        lang = hs_language.upper()
        if lang in {"CS", "CZ", "SK"}:
            return "CZ"
        if lang:
            return "EN"

    # 2. Země kontaktu
    if country:
        c = country.strip().upper()
        if c in {"CZ", "CS", "CZECH", "CZECHIA", "CZECH REPUBLIC", "SK", "SLOVAKIA"}:
            return "CZ"
        if c:
            return "EN"

    # 3. Doménová koncovka e-mailu
    match = re.search(r"\.[a-z]{2,}$", email.lower())
    if match and match.group() in CZ_DOMAINS:
        return "CZ"

    # 4. Výchozí
    return "EN"


# ──────────────────────────────────────────────────────────────────────
# HUBSPOT — čtení dat
# ──────────────────────────────────────────────────────────────────────

def get_all_pipeline_deal_ids() -> list[str]:
    """Vrátí ID všech dealů v pipeline (kromě closedlost)."""
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

    log.info(f"HubSpot: nalezeno {len(deal_ids)} dealů v pipeline")
    return deal_ids


def get_contact_ids_for_deal(deal_id: str) -> list[str]:
    """Vrátí ID kontaktů přiřazených k danému dealu."""
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
    """Načte e-mail, jméno, zemi a jazykové pole kontaktu."""
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
# BREVO — zápis dat
# ──────────────────────────────────────────────────────────────────────

def upsert_brevo_contact(
    email: str,
    firstname: str,
    lastname: str,
    language: str,
) -> None:
    """
    Vytvoří nebo aktualizuje kontakt v Brevo.
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
            "LANGUAGE":  language,      # vlastní atribut — vytvoř ho v Brevo napřed
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
        log.info(f"  ✓ NOVÝ     {email:45s} → [{language}]")
    elif resp.status_code == 204:
        log.info(f"  ↻ UPDATE   {email:45s} → [{language}]")
    else:
        log.warning(f"  ✗ CHYBA    {email} | {resp.status_code} | {resp.text[:120]}")


# ──────────────────────────────────────────────────────────────────────
# HLAVNÍ LOGIKA
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("══════════════════════════════════════════════")
    log.info("  HubSpot → Brevo sync")
    log.info("══════════════════════════════════════════════")

    # Kontrola konfigurace
    errors = []
    if not HUBSPOT_API_KEY:
        errors.append("Chybí HUBSPOT_API_KEY v .env")
    if not BREVO_API_KEY:
        errors.append("Chybí BREVO_API_KEY v .env")
    if BREVO_LIST_CZ == 0:
        errors.append("Chybí BREVO_LIST_CZ v .env (ID listu v Brevo)")
    if BREVO_LIST_EN == 0:
        errors.append("Chybí BREVO_LIST_EN v .env (ID listu v Brevo)")
    if errors:
        for e in errors:
            log.error(f"  ✗ {e}")
        return

    # Načtení dealů
    deal_ids = get_all_pipeline_deal_ids()
    if not deal_ids:
        log.info("Žádné dealy k zpracování.")
        return

    # Průchod kontakty
    seen: set[str] = set()  # deduplikace přes více dealů
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
    log.info(f"  Synchronizováno: {synced}")
    log.info(f"  Přeskočeno (duplicita): {skipped_dupe}")
    log.info(f"  Přeskočeno (chybí e-mail): {skipped_no_email}")
    log.info("══════════════════════════════════════════════")


if __name__ == "__main__":
    main()
