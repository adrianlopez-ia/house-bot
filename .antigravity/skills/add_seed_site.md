# Skill: Add New Seed Site

Follow these steps to add a new website or search query to the discovery system.

## 1. Open `discovery/seed_sites.py`
This file contains the initial list of sites and queries.

## 2. Add to `SEED_SITES`
If it's a specific URL you want to monitor, add it to the `SEED_SITES` list.
Ensure you specify the correct `Zone` (NORTE, ESTE, OESTE).

## 3. Add to `DISCOVERY_QUERIES`
If you want to search DuckDuckGo for new sites, add a search query string to `DISCOVERY_QUERIES`.
Be specific: "cooperativas vivienda madrid norte", etc.

## 4. Run Discovery
Use the `/buscar` command in Telegram or run `main.py` to trigger a discovery cycle.

## 5. Verify in DB
Check the `sites` table in `house_bot.db` to ensure the new site is registered and has the correct zone.
