"""
rocket_league_tracker_mongo.py
---------------------------------
Fetches Rocket League activity data from tracker.gg's internal API and
saves it to MongoDB. Same pattern as the other titles — no login/cookies,
just standard headers. Cloudflare may block this (403/429, or a stalled
connection that times out) — that's expected.

IMPORTANT — different shape than CS2/Valorant/PUBG/R6/Marvel Rivals:
This endpoint (`/aggregated`) returns a per-day HEATMAP (matches played +
rating change per day), not individual match documents. There is no
per-match detail (map, teammates, goals in a single game, etc.) in this
response — just daily rollups. Each day becomes one document in MongoDB.

Requirements:
    pip install requests pymongo

Usage:
    python rocket_league_tracker_mongo.py
    → Enter platform (psn/xbl/steam/epic) and player name, e.g. psn / Nwpov1

Notes:
    tracker.gg's internal API is undocumented and can change without notice.
    The heatmap shape (date + values.matches/ratingChange/goals/etc.) is
    confirmed from a real sample response, so this parser should be
    accurate — but if tracker.gg changes the shape, set PRINT_RAW = True
    and re-check against raw_sample.json.
"""

import json
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI     = "mongodb://localhost:27017"
DB_NAME       = "rocket_league"
LOCAL_OFFSET  = -120   # minutes, matches the localOffset= param (e.g. -120 = UTC+2)
PRINT_RAW     = False  # set True to dump the raw JSON for inspection

# NOTE: this URL is a placeholder guess — I don't have your confirmed request
# for this "trends" endpoint (goals/assists/saves/shots/mvPs/wins/score per
# day). Replace TRENDS_URL_TEMPLATE with the real URL from your Network tab
# once you have it (Fetch/XHR filter, visit the player's stats/trends page).
TRENDS_URL_TEMPLATE = "https://api.tracker.gg/api/v1/rocket-league/matches/{platform}/{player_name}/trends"

# Confirmed real endpoint — note this uses a numeric tracker.gg internal
# player_id, NOT platform/name like the other endpoints. You'll need to
# resolve that ID first (likely returned by a profile lookup call).
RANK_HISTORY_URL_TEMPLATE = "https://api.tracker.gg/api/v1/rocket-league/player-history/mmr/{player_id}"
# ─────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://tracker.gg/",
    "Accept":     "application/json",
}


def handle_response(r: requests.Response, context: str) -> dict | None:
    if r.status_code == 200:
        return r.json()
    elif r.status_code == 403:
        print(f"[ERROR 403] Blocked by Cloudflare: {context}")
        print("  → Try again later or from a different network.")
    elif r.status_code == 429:
        print(f"[ERROR 429] Rate limited: {context}. Wait a few minutes.")
    elif r.status_code == 404:
        print(f"[ERROR 404] Not found: {context}")
    else:
        print(f"[ERROR {r.status_code}] {context}: {r.text[:200]}")
    return None


# ── 1. Fetch the aggregated heatmap for a player ─────────────────────────────

def get_heatmap(platform: str, player_name: str) -> list[dict]:
    url = f"https://api.tracker.gg/api/v1/rocket-league/matches/{platform}/{player_name}/aggregated"
    params = {"localOffset": LOCAL_OFFSET}

    try:
        print(f"  Fetching aggregated heatmap for {player_name} ({platform})...")
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        print("  → Likely Cloudflare stalling the connection instead of a clean 403.")
        return []

    data = handle_response(r, f"aggregated {player_name}")
    if not data:
        return []

    if PRINT_RAW:
        with open("raw_sample.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  [DEBUG] Raw sample written to raw_sample.json")

    payload = data.get("data", {})
    if not payload.get("found", False):
        print("  Player not found.")
        return []

    return payload.get("heatmap", [])


# ── 2. Parse a single day's heatmap entry ────────────────────────────────────

def parse_day(entry: dict, player_name: str, platform: str) -> dict | None:
    try:
        date   = entry.get("date", "")
        values = entry.get("values", {})

        return {
            "player_name":   player_name,
            "platform":      platform,
            "date":          date,
            "matches":       values.get("matches") or 0,
            "wins":          values.get("wins"),
            "win_pct":       values.get("winPct"),
            "goals":         values.get("goals"),
            "assists":       values.get("assists"),
            "saves":         values.get("saves"),
            "shots":         values.get("shots"),
            "mvps":          values.get("mvps"),
            "rating_change": values.get("ratingChange") or 0,
            "updated_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped day] {e}")
        return None


# ── 2b. Fetch the daily trends (goals/assists/saves/shots/wins/score) ───────

def get_daily_trends(platform: str, player_name: str) -> list[dict]:
    """
    Fetches the richer daily-stats endpoint (confirmed field names: goals,
    assists, saves, shots, mvPs, wins, score, goalShotRatio, collectDate).
    URL is a best guess (see TRENDS_URL_TEMPLATE) — adjust if it 404s.
    """
    url = TRENDS_URL_TEMPLATE.format(platform=platform, player_name=player_name)

    try:
        print(f"  Fetching daily trends for {player_name} ({platform})...")
        r = requests.get(url, headers=HEADERS, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        print("  → Likely Cloudflare stalling the connection instead of a clean 403.")
        return []

    data = handle_response(r, f"trends {player_name}")
    if not data:
        return []

    if PRINT_RAW:
        with open("raw_sample_trends.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  [DEBUG] Raw sample written to raw_sample_trends.json")

    return data.get("data", [])


def parse_trend_day(entry: dict, player_name: str, platform: str) -> dict | None:
    try:
        return {
            "player_name":    player_name,
            "platform":       platform,
            "date":           entry.get("collectDate", ""),
            "wins":           entry.get("wins", 0),
            "goals":          entry.get("goals", 0),
            "assists":        entry.get("assists", 0),
            "saves":          entry.get("saves", 0),
            "shots":          entry.get("shots", 0),
            "mvps":           entry.get("mvPs", 0),
            "score":          round(entry.get("score", 0), 2),
            "goal_shot_ratio": round(entry.get("goalShotRatio", 0), 2),
            "updated_at":     datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped trend day] {e}")
        return None


def upsert_trend_day(collection, day: dict) -> str:
    result = collection.update_one(
        {"player_name": day["player_name"], "platform": day["platform"], "date": day["date"]},
        {"$set": day},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"


# ── 2c. Fetch the daily rank history (rating/tier/division per day) ─────────

def get_rank_history(player_id: str) -> list[dict]:
    """
    Fetches the daily rank progression endpoint using tracker.gg's internal
    numeric player_id (NOT platform/name — that's a different identifier
    system than the other endpoints). Confirmed field names: rating, tier,
    division, tierId, divisionId, collectDate.
    """
    url = RANK_HISTORY_URL_TEMPLATE.format(player_id=player_id)

    try:
        print(f"  Fetching rank history for player_id={player_id}...")
        r = requests.get(url, headers=HEADERS, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        print("  → Likely Cloudflare stalling the connection instead of a clean 403.")
        return []

    data = handle_response(r, f"rank history player_id={player_id}")
    if not data:
        return []

    if PRINT_RAW:
        with open("raw_sample_rank_history.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  [DEBUG] Raw sample written to raw_sample_rank_history.json")

    return data.get("data", [])


def parse_rank_day(entry: dict, player_id: str, player_name: str = "", platform: str = "") -> dict | None:
    try:
        return {
            "player_id":   player_id,
            "player_name": player_name,   # optional, fill in if you know it
            "platform":    platform,       # optional, fill in if you know it
            "date":        entry.get("collectDate", ""),
            "rating":      entry.get("rating", 0),
            "tier":        entry.get("tier", ""),
            "division":    entry.get("division", ""),
            "tier_id":     entry.get("tierId", 0),
            "division_id": entry.get("divisionId", 0),
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped rank day] {e}")
        return None


def upsert_rank_day(collection, day: dict) -> str:
    result = collection.update_one(
        {"player_id": day["player_id"], "date": day["date"]},
        {"$set": day},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"




def upsert_day(collection, day: dict) -> str:
    result = collection.update_one(
        {"player_name": day["player_name"], "platform": day["platform"], "date": day["date"]},
        {"$set": day},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"


# ── 4. Build and upsert player summary ───────────────────────────────────────

def upsert_player_summary(collection, player_name: str, platform: str, days: list[dict]) -> None:
    if not days:
        return

    total_matches = sum(d["matches"] for d in days)
    total_rating_change = sum(d["rating_change"] for d in days)
    active_days = len(days)

    best_day = max(days, key=lambda d: d["rating_change"], default=None)
    worst_day = min(days, key=lambda d: d["rating_change"], default=None)
    busiest_day = max(days, key=lambda d: d["matches"], default=None)

    summary = {
        "player_name":        player_name,
        "platform":           platform,
        "active_days":        active_days,
        "total_matches":      total_matches,
        "average_matches_per_active_day": round(total_matches / active_days, 2) if active_days else 0,
        "total_rating_change": total_rating_change,
        "best_day":           {"date": best_day["date"], "rating_change": best_day["rating_change"]} if best_day else None,
        "worst_day":          {"date": worst_day["date"], "rating_change": worst_day["rating_change"]} if worst_day else None,
        "busiest_day":        {"date": busiest_day["date"], "matches": busiest_day["matches"]} if busiest_day else None,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }

    collection.update_one(
        {"player_name": player_name, "platform": platform},
        {"$set": summary},
        upsert=True,
    )
    print(f"[MongoDB]  Player summary upserted for {player_name}")


# ── 5. Full flow for one player ───────────────────────────────────────────────

def get_player(days_col, players_col, platform: str, player_name: str) -> None:
    print(f"\n[Tracker]  Fetching Rocket League heatmap for {player_name} ({platform})...")
    raw_days = get_heatmap(platform, player_name)

    if not raw_days:
        print(f"  No data found for {player_name}.")
        return

    parsed = [parse_day(d, player_name, platform) for d in raw_days]
    parsed = [d for d in parsed if d]

    inserted = updated = 0
    for day in parsed:
        action = upsert_day(days_col, day)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_col, player_name, platform, parsed)

    print(f"\n── Results for {player_name} ────────────────────────")
    print(f"  Days fetched : {len(parsed)}")
    print(f"  Inserted     : {inserted}")
    print(f"  Updated      : {updated}")
    print(f"────────────────────────────────────────────────────\n")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        db = client[DB_NAME]
        print(f"[MongoDB]  Connected to '{DB_NAME}'\n")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        return

    days_col = db["daily_activity"]
    players_col = db["players"]

    platform = input("Enter platform (psn/xbl/steam/epic): ").strip().lower()
    if platform not in ("psn", "xbl", "steam", "epic"):
        print("[ERROR] Platform should be one of: psn, xbl, steam, epic")
        return

    player_name = input("Enter player name (e.g. Nwpov1): ").strip()
    if not player_name:
        print("[ERROR] Please enter a player name.")
        return

    get_player(days_col, players_col, platform, player_name)


if __name__ == "__main__":
    run()
