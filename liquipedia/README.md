# liquipedia/ — liquipedia.net scraping suite

A Node.js scraper suite that fetches and parses HTML pages from
**liquipedia.net** (tournament portals, team portals, player portals) using
Axios + Cheerio, and exposes cached results over a small Express API. Unlike
`thetracker/`, this pipeline writes flat JSON files rather than MongoDB.

```
liquipedia/
├── scrapers/       # Node/ES-module scraper + API files, plus package.json
├── data/            # scraped output (already-run results, currently Dota 2)
└── displays/         # Word/PDF exports of sample output
```

---

## 1. Files (`scrapers/`)

| File | Scrapes | Exports |
|---|---|---|
| `dota2_tournaments_scraper.js` | Dota 2 tournament portals (`Recent_Tournament_Results`, `Tier_1..4_Tournaments`, `Monthly/Weekly_Tournaments`, `Show_Matches`, plus yearly `Qualifier_Tournaments/<year>` pages) | `getAllTournaments()` |
| `dota2_teams_scraper.js` | Dota 2 team portals, split by region (Americas/Europe/China/Southeast Asia) | `getAllTeams()` |
| `dota2_players_scraper.js` | Dota 2 player portals, same 4 regions | `getAllPlayers()` |
| `dota2_api.js` | Express app on port `3000` that imports the three Dota 2 scrapers above, caches their results in memory, and serves them as JSON | — |
| `cs2_tournaments_scraper.js` | Counter-Strike tournament portals (S/A/B/C-Tier, Monthly/Weekly, plus quarterly `Qualifier_Tournaments/<year>_Q<n>`) | (scraper only — no matching Express wrapper yet) |
| `valorant_tournaments_scraper.js` | Same tournament-portal pattern, generalized with a `game` variable (currently set to `"valorant"`) and yearly qualifiers | (scraper only — no matching Express wrapper yet) |

Only the **Dota 2** pipeline is wired end-to-end (scrapers → `dota2_api.js`
→ `data/*.json`). The `cs2_tournaments_scraper.js` and
`valorant_tournaments_scraper.js` scrapers exist and run standalone but
aren't yet plugged into an Express app the way Dota 2 is — following the
same `_db`/`_api` idea as `thetracker/`, the natural next step would be
building `cs2_api.js` and `valorant_api.js` wrappers for them.

---

## 2. Requirements

```bash
cd scrapers
npm install    # axios, cheerio, express, mongodb, puppeteer
```

`mongodb` and `puppeteer` are listed as dependencies in `package.json` but
none of the current scraper files import them — the active pipeline (Dota 2)
only uses `axios` + `cheerio`, and the API layer only uses `express` + `fs`.

---

## 3. Data files (`data/`)

Already-scraped Dota 2 results, one array of objects per file:

- **`tournaments.json`** — tier, title, link, date, prize pool, location, participant count, winner, runner-up.
- **`teams.json`** — team/player name + Liquipedia link, from the regional `Portal:Teams/*` pages.
- **`players.json`** — player id/name/nationality/team, from the regional `Portal:Players/*` pages. Note: several entries are portal boilerplate rows (`Inactive`, `Retired`, `Banned`, `Deceased`) rather than real players — worth filtering downstream.

Every entry carries a `sourceUrl` field pointing at the exact Liquipedia page it came from, useful for re-scraping or debugging a bad row.

---

## 4. Running it

```bash
cd scrapers
node dota2_api.js
# API running at http://localhost:3000
```

The scrapers set a custom `User-Agent` (`MyTestProject/1.0 (myemail@example.com)`)
per Liquipedia's request for identifiable bot traffic — update this to your
own contact info before running against the live site.

To run the CS2 or Valorant scrapers standalone (no server), import and call
their exported functions from a small script:

```js
import { /* exported fn */ } from './cs2_tournaments_scraper.js';
```

(Check the bottom of each file for the actual export name — they aren't
wired into `dota2_api.js`, so there's no ready-made route to hit yet.)

---

## 5. Known issues / caveats

- **HTML-markup fragile.** These scrapers depend on Liquipedia's current page structure (Cheerio selectors for `TeamCard` blocks, tournament tables, etc.) — any Liquipedia template change will silently break parsing rather than erroring cleanly.
- **No caching/backoff between scraper runs** beyond the simple in-memory cache in `dota2_api.js` — repeated runs re-hit every portal page each time.
- **CS2 and Valorant scrapers aren't exposed over HTTP** yet — only Dota 2 has an Express wrapper.
- **`players.json` includes non-player boilerplate rows** (see above) that should be filtered before use.

## 6. Suggested next steps

1. Build `cs2_api.js` / `valorant_api.js` Express wrappers analogous to `dota2_api.js`, or generalize one API file to take a `game` parameter.
2. Persist scraped output on a schedule (cron / node-cron) instead of only on-demand, and diff against the last run to catch schema drift early.
3. Filter portal-boilerplate rows out of `players.json` at scrape time.
4. Drop the unused `mongodb`/`puppeteer` deps from `package.json` if they're not going to be used, or wire them in if the plan is to move off flat JSON files (mirroring how `thetracker/` uses MongoDB).
