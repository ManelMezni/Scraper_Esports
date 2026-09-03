# Scraping Suite — Split by Source

This project was originally one flat folder mixing two unrelated scraping
pipelines that just happen to cover overlapping esports titles. It's split
into two top-level folders, one per data source, and every file inside them
follows a clear, consistent naming pattern.

```
.
├── thetracker/      # everything that pulls from tracker.gg's internal API
└── liquipedia/       # everything that scrapes liquipedia.net pages
```

## Naming pattern

| Pipeline | Scraper file | API file |
|---|---|---|
| `thetracker/` (Python) | `<game>_db.py` — scrapes tracker.gg, writes/reads MongoDB | `<game>_api.py` — Flask API serving that data |
| `liquipedia/` (Node.js) | `<game>_..._scraper.js` — scrapes a Liquipedia portal | `<game>_api.js` — Express API serving the scraped data (only built for Dota 2 so far) |

So for example: `valorant_db.py` + `valorant_api.py` (tracker.gg), and
`dota2_tournaments_scraper.js` + `dota2_api.js` (Liquipedia).

## Why these are separate

| | thetracker/ | liquipedia/ |
|---|---|---|
| Source | `api.tracker.gg` (tracker.gg's undocumented internal JSON API) | `liquipedia.net` (HTML pages, scraped with Cheerio) |
| Language | Python (Flask + PyMongo) | Node.js / ES modules (Axios + Cheerio + Express) |
| Data | Per-player match history / profile stats, 8 games | Tournament results, team rosters, player portals (Dota 2), plus a couple of other titles |
| Storage | MongoDB | Flat JSON files (`players.json`, `teams.json`, `tournaments.json`) |
| Auth | None, but Cloudflare frequently blocks it | None, but scraping HTML is fragile to markup changes |

See the `README.md` inside each folder for full setup/usage details.

## Two things worth your attention

1. **`thetracker/displays/Honor_of_kings_display.docx` is misnamed.** The
   screenshots inside it are hitting `/player/psn/.../history`, which is the
   **For Honor** route, not Honor of Kings. Kept under its original filename
   so nothing was silently renamed, but it belongs to the For Honor pair.

2. **`thetracker/UNRELATED_FILE_REVIEW_NEEDED/groq_chatbot_UNRELATED_hardcoded_key.py`
   has nothing to do with scraping and contains a hardcoded, live-looking
   Groq API key.** It was duplicated in two places in the original archive.
   Please rotate that key if it's real — see that folder's note in
   `thetracker/README.md` for details.
