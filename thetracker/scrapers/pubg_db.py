"""
pubg_tracker_mongo.py
-----------------------
Fetches PUBG match data from tracker.gg's internal API and saves to MongoDB.
Same pattern as the CS2/Valorant/TFT scripts — no login/cookies, just
standard headers. tracker.gg's Cloudflare protection may block this
(403/429, or a stalled connection that times out) — that's expected.

Requirements:
    pip install requests pymongo

Usage:
    python pubg_tracker_mongo.py
    → Enter a PUBG name, e.g. 2cut

Notes:
    tracker.gg's internal API is undocumented and can change without notice.
    Field paths in parse_match() are a best guess based on the shape used by
    the other tracker.gg titles (metadata / attributes / segments[0].stats).
    Set PRINT_RAW = True once, inspect raw_sample.json, and adjust field
    names (kills, damage, placement, etc.) before trusting the parsed output.
"""

import json
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "pubg"
GAME_MODE = "tpp"     # "tpp" or "fpp" — matches the type= param
SEASON    = ""        # empty = current/all seasons
PRINT_RAW = False     # set True to dump first page of raw JSON for inspection
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


def placement_bucket(placement: int) -> str:
    if placement == 1:
        return "1st (Chicken Dinner)"
    if placement <= 10:
        return f"Top 10 ({placement}th)"
    return f"{placement}th"


# ── 1. Fetch all matches for a player ────────────────────────────────────────

def get_all_matches(player_name: str) -> list[dict]:
    url = f"https://api.tracker.gg/api/v2/pubg/standard/matches/steam/{player_name}"
    all_matches = []
    cursor = None
    page = 0

    while True:
        params = {"type": GAME_MODE}
        if SEASON:
            params["season"] = SEASON
        if cursor:
            params["next"] = cursor

        try:
            print(f"  Fetching page (cursor={cursor})...")
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Request failed: {e}")
            print("  → Likely Cloudflare stalling the connection instead of a clean 403.")
            break

        data = handle_response(r, f"matches cursor={cursor}")
        if not data:
            break

        if PRINT_RAW and page == 0:
            with open("raw_sample.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("  [DEBUG] Raw sample written to raw_sample.json")

        payload = data.get("data", {})
        matches = payload.get("matches", [])

        if not matches:
            print("  No more matches.")
            break

        all_matches.extend(matches)
        print(f"  Got {len(matches)} matches — total: {len(all_matches)}")

        cursor = payload.get("metadata", {}).get("next")
        page += 1
        if not cursor:
            print("  Reached last page.")
            break

    return all_matches


# ── 2. Parse a single raw match ───────────────────────────────────────────────

def parse_match(match: dict, player_name: str) -> dict | None:
    try:
        meta  = match.get("metadata", {})
        attrs = match.get("attributes", {})
        segs  = match.get("segments", [])

        if not segs:
            return None

        seg      = segs[0]
        seg_meta = seg.get("metadata", {})
        stats    = seg.get("stats", {})

        def val(key: str):
            return stats.get(key, {}).get("value", 0) or 0

        placement = int(val("placement") or val("teamPlacement"))
        kills     = int(val("kills"))
        damage    = float(val("damageDealt") or val("damage"))

        return {
            "match_id":     attrs.get("id", match.get("id", "")),
            "player_name":  player_name,
            "date":         meta.get("timestamp", ""),
            "map":          meta.get("mapName", seg_meta.get("mapName", "")),
            "mode":         GAME_MODE,
            "placement":    placement,
            "result_bucket": placement_bucket(placement) if placement else "",
            "kills":        kills,
            "assists":      int(val("assists")),
            "damage_dealt": round(damage, 1),
            "headshot_kills": int(val("headshotKills")),
            "revives":      int(val("revives")),
            "time_survived_seconds": int(val("timeSurvived")),
            "walk_distance": round(float(val("walkDistance")), 1),
            "ride_distance": round(float(val("rideDistance")), 1),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped match] {e}")
        return None


# ── 3. Upsert match into MongoDB ──────────────────────────────────────────────

def upsert_match(collection, match: dict) -> str:
    result = collection.update_one(
        {"match_id": match["match_id"], "player_name": match["player_name"]},
        {"$set": match},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"


# ── 4. Build and upsert player summary ───────────────────────────────────────

def upsert_player_summary(collection, player_name: str, matches: list[dict]) -> None:
    if not matches:
        return

    count       = len(matches)
    placements  = [m["placement"] for m in matches if m.get("placement")]
    wins        = sum(1 for p in placements if p == 1)
    top10s      = sum(1 for p in placements if p <= 10)
    avg_place   = round(sum(placements) / len(placements), 2) if placements else 0

    total_kills = sum(m["kills"] for m in matches)
    total_dmg   = sum(m["damage_dealt"] for m in matches)

    summary = {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "top10_rate":        round(top10s / count * 100, 1) if count else 0,
        "average_placement": avg_place,
        "best_placement":    min(placements) if placements else None,
        "total_kills":       total_kills,
        "average_kills":     round(total_kills / count, 2) if count else 0,
        "average_damage":    round(total_dmg / count, 1) if count else 0,
        "updated_at":        datetime.now(timezone.utc).isoformat(),
    }

    collection.update_one(
        {"player_name": player_name},
        {"$set": summary},
        upsert=True,
    )
    print(f"[MongoDB]  Player summary upserted for {player_name}")


# ── 5. Full flow for one player ───────────────────────────────────────────────

def get_player(matches_col, players_col, player_name: str) -> None:
    print(f"\n[Tracker]  Fetching matches for {player_name}...")
    raw_matches = get_all_matches(player_name)

    if not raw_matches:
        print(f"  No matches found for {player_name}.")
        return

    parsed = [parse_match(m, player_name) for m in raw_matches]
    parsed = [m for m in parsed if m]

    inserted = updated = 0
    for match in parsed:
        action = upsert_match(matches_col, match)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_col, player_name, parsed)

    print(f"\n── Results for {player_name} ────────────────────────")
    print(f"  Matches fetched : {len(parsed)}")
    print(f"  Inserted        : {inserted}")
    print(f"  Updated         : {updated}")
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

    matches_col = db["matches"]
    players_col = db["players"]

    player_name = input("Enter PUBG player name (e.g. 2cut): ").strip()
    if not player_name:
        print("[ERROR] Please enter a player name.")
        return

    get_player(matches_col, players_col, player_name)


if __name__ == "__main__":
    run()
