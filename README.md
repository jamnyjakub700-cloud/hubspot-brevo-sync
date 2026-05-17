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

## Quick Start

1. **Clone and install dependencies**
   ```bash
   git clone https://github.com/YOUR_USERNAME/hubspot-brevo-sync.git
   cd hubspot-brevo-sync
   pip install -r requirements.txt
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and list IDs
   ```

3. **Create Brevo lists** — one list for each language (e.g. list 12 for Czech, list 14 for English). Set the list IDs in `BREVO_LIST_CZ` and `BREVO_LIST_EN`.

4. **Run the sync**
   ```bash
   python sync.py
   ```

5. **Schedule via cron** for automatic daily syncing:
   ```bash
   # Every day at 7:00 AM
   0 7 * * * cd /path/to/hubspot-brevo-sync && python sync.py
   ```

## Configuration

| Variable | Description |
|----------|-------------|
| `HUBSPOT_API_KEY` | HubSpot Private App token |
| `BREVO_API_KEY` | Brevo API key |
| `BREVO_LIST_CZ` | Brevo list ID for Czech contacts |
| `BREVO_LIST_EN` | Brevo list ID for English contacts |

## How Language Detection Works

Each contact is assigned a language (CZ or EN) using the following priority:

1. **`hs_language` field** — if the HubSpot contact has an explicit language/locale set (e.g. `cs`, `cs-CZ`), that value is used directly.
2. **Country** — if the contact's country is Czech Republic or Slovakia, the language is set to CZ.
3. **Email domain TLD** — if the email ends in `.cz` or `.sk`, the language is set to CZ.
4. **Default** — if none of the above match, the contact defaults to EN.

To adapt this for other language pairs, modify the detection logic in `sync.py` and create additional Brevo lists for each language.

## How it works

The script uses the HubSpot CRM API to fetch deals in active pipeline stages, then retrieves associated contacts. Each contact is analyzed for language preference using the priority chain above. Contacts are then upserted to Brevo via the Brevo API with mapped attributes and added to the appropriate language list.

## License

MIT
