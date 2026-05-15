# HubSpot to Brevo Sync

Python script that syncs contacts from active HubSpot deals to Brevo (formerly Sendinblue) email marketing lists with automatic language detection.

## What it does

1. Fetches all active deals from HubSpot CRM
2. Extracts associated contacts with their properties
3. Detects language (CZ/EN) based on contact fields
4. Creates or updates contacts in Brevo with mapped attributes
5. Assigns contacts to language-specific Brevo lists

## Prerequisites

- Python 3.10+
- HubSpot Private App token (scopes: `crm.objects.deals.read`, `crm.objects.contacts.read`)
- Brevo API key
- Two Brevo lists (one per language)

## Setup

```bash
git clone https://github.com/jamnyjakub700-cloud/hubspot-brevo-sync.git
cd hubspot-brevo-sync

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API keys and list IDs
```

## Usage

```bash
# Run sync manually
python sync.py

# Schedule daily at 7:00 AM via cron
# 0 7 * * * cd /path/to/hubspot-brevo-sync && python sync.py
```

## Configuration

| Variable | Description |
|----------|-------------|
| `HUBSPOT_API_KEY` | HubSpot Private App token |
| `BREVO_API_KEY` | Brevo API key |
| `BREVO_LIST_CZ` | Brevo list ID for Czech contacts |
| `BREVO_LIST_EN` | Brevo list ID for English contacts |

## How it works

The script uses the HubSpot CRM API to fetch deals in active pipeline stages, then retrieves associated contacts. Each contact is analyzed for language preference based on available fields (locale, country, domain TLD). Contacts are then upserted to Brevo via the Brevo API with mapped attributes and added to the appropriate language list.

**Jakub Jamny** — AI automation specialist

- [LinkedIn](https://www.linkedin.com/in/jakub-jamn%C3%BD-3a0410246)
- [Website](https://jakubjamny.com)

## License

MIT
