# thetracker/ — tracker.gg scraping suite

A collection of scraper + Flask API pairs that pull match/profile data from
**tracker.gg's internal API** (`api.tracker.gg`) for eight games, store it in
**MongoDB**, and expose it over simple JSON endpoints.

```
thetracker/
├── scrapers/                       # active code, one pair per game
│   ├── <game>_db.py                # scrape tracker.gg → MongoDB
│   ├── <game>_api.py               # Flask API serving that MongoDB data
│   └── valorant_experiments/       # extra Valorant-only scratch files (see below)
├── displays/                        # Word docs of sample API output (screenshots), per game
├── legacy_prototype/                 # older duplicate of valorant_experiments/ (see bottom)
└── UNRELATED_FILE_REVIEW_NEEDED/     # a file with no relation to scraping — read this section
```

## 1. The 8 game pairs (`scrapers/`)

Every game is exactly two files, named the same way:

| Game | Scraper (`_db.py`) | API (`_api.py`) | Mongo DB name | Data shape |
|---|---|---|---|---|
| Valorant | `valorant_db.py` | `valorant_api.py` | `valorant` | Per-match |
| League of Legends | `lol_db.py` | `lol_api.py` | `league` | Per-match (ranked only, queues 420/440) |
| Teamfight Tactics | `tft_db.py` | `tft_api.py` | `tft` | Per-match |
| Counter-Strike 2 | `cs2_db.py` | `cs2_api.py` | `cs2` | Per-match |
| PUBG | `pubg_db.py` | `pubg_api.py` | `pubg` | Per-match |
| Rainbow Six Siege | `r6_db.py` | `r6_api.py` | `r6siege` | Per-match |
| Rocket League | `rocket_league_db.py` | `rocket_league_api.py` | `rocket_league` | Per-**day** heatmap (not per-match) |
| For Honor | `for_honor_db.py` | `for_honor_api.py` | `for_honor` | Profile **snapshot** — sample output is `displays/Honor_of_kings_display.docx`, misnamed but confirmed to be For Honor |

**`<game>_db.py`** — standalone script: connect to MongoDB → fetch all
pages of matches (or the single profile/heatmap) from tracker.gg → parse →
upsert into a `matches` collection and a rolled-up `players` collection.
Runnable directly, and also imported by the matching `_api.py`.

**`<game>_api.py`** — Flask app exposing the MongoDB data as JSON, plus a
`/fetch/...` route that triggers a live scrape + upsert on demand. Imports
its scraping/parsing/upsert functions straight from `<game>_db.py`, so the
two files must stay in the same folder (they do — both live in `scrapers/`).

Player identifiers differ by game:
- **Riot titles** (Valorant, LoL, TFT): Riot ID `Name#Tag`, URL-encoded as `Name%23Tag`.
- **CS2**: numeric **Steam64 ID**.
- **PUBG**: Steam display name.
- **R6 Siege, Rocket League, For Honor**: `platform` (`psn`/`xbl`/`steam`/`epic`/`ubi`) + player name.

### Common endpoints (present in every API, naming varies slightly by identifier type)

| Route | Description |
|---|---|
| `GET /` | Health check |
| `GET /players` | All stored player summaries |
| `GET /matches` | All stored matches (per-match games only) |
| `GET /matches/<match_id>` | Single match |
| `GET /player/<id...>/stats` | Aggregated stats for one player |
| `GET /player/<id...>/matches` | All matches for one player |
| `GET /fetch/<id...>` | Live-scrapes tracker.gg for that player and upserts into MongoDB |

Game-specific extras:
- **LoL / R6 / CS2**: `.../champions`, `.../operators`, `.../maps` — breakdown by champion/operator/map.
- **Rocket League**: `.../heatmap` instead of `.../matches` (daily activity, not individual games).
- **For Honor**: `.../history` (snapshot history) and `.../gametype/<pvp|pve>` (raw pass-through segment).

---

## 2. Requirements

```bash
cd scrapers
pip install -r requirements.txt   # flask, requests, pymongo
```

- A running **MongoDB** instance, default `mongodb://localhost:27017` (change `MONGO_URI` at the top of each `_db.py` file if needed).
- No login/cookies required for tracker.gg — just a browser-like `User-Agent`/`Referer`. Cloudflare **will** intermittently block requests (see [Known issues](#4-known-issues--caveats)).

Run a scraper: `python valorant_db.py` (or any other `<game>_db.py`).
Run an API: `python valorant_api.py` (or any other `<game>_api.py`), then hit `http://127.0.0.1:5000/`.

---

## 3. `scrapers/valorant_experiments/` — extra Valorant-only files

These aren't part of the 8-game pattern above; they're earlier
Valorant-specific experiments that were sitting loose in the original
folder. Renamed for clarity, but kept separate so they don't get confused
with the real `valorant_db.py` / `valorant_api.py`:

| File | What it actually is |
|---|---|
| `valorant_alt_db.py` | A second, **decoupled** Valorant scraper — the only file that's allowed to talk to tracker.gg in this mini-pipeline. |
| `valorant_alt_api.py` | A Flask API that **only** reads MongoDB, never calls tracker.gg directly — pairs with `valorant_alt_db.py`. |
| `valorant_alt_api_test_client.py` | A little script that hits `valorant_alt_api.py`'s endpoints and prints the JSON responses. |
| `valorant_hardcoded_demo_api.py` | A trivial Flask stub with one hardcoded fake player (`TenZ`, made-up stats) — not connected to tracker.gg or MongoDB at all. Demo/placeholder only. |
| `valorant_sample_data_db.py` | A Valorant "scraper" that currently uses **sample/fake data**, not a live API — the fetch step is a stub. |
| `valorant_henrikdev_db.py` | A **different** Valorant scraper entirely — hits `api.henrikdev.xyz`, a third-party Valorant stats API, not tracker.gg. Needs its own API key (placeholder in the file). |
| `valorant_rating_stub_api.py` | A tiny Flask stub with a hardcoded kills/deaths/assists example — not wired to any real data source. |
| `mongo_connection_smoke_test.py` | A one-off script that just inserts a test document into MongoDB to confirm the connection works. |

None of these need to run together — each is an independent leftover
experiment.

---

## 4. Known issues / caveats

- **Cloudflare blocking (all 8 games).** tracker.gg's API is undocumented and unauthenticated from these scripts' point of view, so 403s (Cloudflare) and 429s (rate limit) are expected and handled, but not solved — the fix is "wait" or "different network," not code.
- **Unconfirmed response schemas (TFT, PUBG, R6, CS2, For Honor).** Several `parse_match()` / `parse_profile()` functions are explicitly flagged as **best guesses** based on the Valorant/LoL response shape, not confirmed against a live 200 response. Each has a `PRINT_RAW` flag (or manual `json.dump`) to dump the raw JSON once so field names can be verified/corrected.
- **Rocket League is a heatmap, not matches.** `/aggregated` returns per-day rollups — there's no single-match detail. `rocket_league_db.py` also has two unused/unwired extras (`get_daily_trends`/`parse_trend_day`, `get_rank_history`/`parse_rank_day`) whose URLs are placeholders — scaffolding for future work.
- **For Honor is a profile snapshot, not matches.** Hero-level breakdown is called out as **not confirmed** to exist in the response.
- **LoL player names support arbitrary Unicode** (`quote()`/`unquote()` + `<path:player_name>` Flask routes) — other games' routes use plain `<player_name>` and may not handle special characters as gracefully.
- **No authentication/rate-limiting on the Flask APIs themselves** — local/dev tools (`debug=True`), not production-ready as-is.

---

## 5. ⚠️ `UNRELATED_FILE_REVIEW_NEEDED/` — please read

`groq_chatbot_UNRELATED_hardcoded_key.py` has **nothing to do with
scraping**. It's a small command-line chatbot script that calls the Groq
API — and it has a **live-looking Groq API key hardcoded directly in the
source** (`gsk_...`). This exact file was duplicated in two places in the
original archive.

**You should revoke/rotate that key in your Groq account now if it's real**,
then either delete this file or move the key to an environment variable
before keeping the script around. I moved it out of the main folders so it
doesn't get mistaken for part of the scraping project, but I didn't delete
it in case you still need it.

---

## 6. `legacy_prototype/` — older duplicate

This is an earlier snapshot of everything in `scrapers/valorant_experiments/`
(same files, same new names) plus its own copy of the unrelated Groq script.
Two files (`valorant_alt_api_test_client.py`, `valorant_henrikdev_db.py`)
differ slightly from their `scrapers/valorant_experiments/` counterparts;
everything else is byte-identical. Kept in case the older version has
anything worth salvaging — the actively-relevant copy is in `scrapers/`.

---

## 7. Suggested next steps

1. Set `PRINT_RAW = True` in TFT/PUBG/R6/CS2/For Honor/Rocket League `_db.py` files, run once per game against a known-active player, and diff the assumed field names against the real JSON.
2. Decide whether to wire up Rocket League's `get_daily_trends()`/`get_rank_history()` into the API routes, or remove them.
3. Consider centralizing the duplicated `handle_response()`, `calculate_kda()`, and `serialize_doc()`/`serialize_docs()` helpers (identical across nearly every `_db.py`) into a shared `common.py` module.
4. Rotate the exposed Groq API key, then decide whether to keep, fix, or delete `UNRELATED_FILE_REVIEW_NEEDED/` and `legacy_prototype/`.
