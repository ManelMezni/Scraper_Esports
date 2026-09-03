
"""
cs2_tracker_mongo.py
---------------------
Fetches Counter-Strike 2 match data from tracker.gg's internal API and saves to MongoDB.

Requirements:
    pip install requests pymongo

Usage:
    python cs2_tracker_mongo.py
    → Enter a Steam64 ID, e.g. 76561198106274751

Notes:
    tracker.gg's internal API is undocumented and can change without notice.
    The field paths used in parse_match() below are best-guess based on the
    LoL endpoint's structure (metadata / attributes / segments[0].stats).
    Run with PRINT_RAW = True once and inspect the JSON in raw_sample.json
    to confirm/adjust field names for kills, deaths, assists, etc. before
    relying on the parsed output.
"""

import json
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "cs2"
GAME_TYPE = "scrimcomp2v2"   # matches the type= param in the URL you gave; change as needed
SEASON    = ""               # empty = all seasons
MODE      = "all"
PRINT_RAW = False            # set True to dump first page of raw JSON for inspection
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


def calculate_kda(kills: int, deaths: int, assists: int) -> float:
    if deaths == 0:
        return float(kills + assists)
    return round((kills + assists) / deaths, 2)


# ── 1. Fetch all matches for a player ────────────────────────────────────────

def get_all_matches(steam_id: str) -> list[dict]:
    """
    Hits tracker.gg's CS2 matches endpoint page by page using cursor-based
    pagination (the 'next' query param).
    """
    url = f"https://api.tracker.gg/api/v2/cs2/standard/matches/steam/{steam_id}"
    all_matches = []
    cursor = None
    page = 0

    while True:
        params = {
            "type":   GAME_TYPE,
            "season": SEASON,
            "mode":   MODE,
        }
        if cursor:
            params["next"] = cursor

        print(f"  Fetching page (cursor={cursor})...")
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
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

def parse_match(match: dict, steam_id: str) -> dict | None:
    """
    Best-effort parse following the same metadata/attributes/segments shape
    tracker.gg uses for other titles. Verify field names against
    raw_sample.json (set PRINT_RAW = True) and adjust the `val()` keys below
    if CS2's stat keys differ (e.g. "kills" vs "kills_avg" vs "kdRatio").
    """
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

        kills   = int(val("kills"))
        deaths  = int(val("deaths"))
        assists = int(val("assists"))

        result = (
            meta.get("outcome")
            or seg_meta.get("outcome")
            or meta.get("result")
            or ""
        )

        return {
            "match_id":     attrs.get("id", match.get("id", "")),
            "steam_id":     steam_id,
            "date":         meta.get("timestamp", ""),
            "map":          meta.get("mapName", seg_meta.get("mapName", "")),
            "game_type":    GAME_TYPE,
            "result":       result,
            "kills":        kills,
            "deaths":       deaths,
            "assists":      assists,
            "kda":          calculate_kda(kills, deaths, assists),
            "kd_ratio":     round(float(val("kdRatio")), 2),
            "headshots":    int(val("headshots")),
            "headshot_pct": round(float(val("headshotsPercentage")), 1),
            "mvps":         int(val("mvps")),
            "score":        int(val("score")),
            "rounds_won":   int(val("roundsWon")),
            "rounds_lost":  int(val("roundsLost")),
            "rating":       round(float(val("rating")), 2),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped match] {e}")
        return None


# ── 3. Upsert match into MongoDB ──────────────────────────────────────────────

def upsert_match(collection, match: dict) -> str:
    result = collection.update_one(
        {"match_id": match["match_id"], "steam_id": match["steam_id"]},
        {"$set": match},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"


# ── 4. Build and upsert player summary ───────────────────────────────────────

def upsert_player_summary(collection, steam_id: str, matches: list[dict]) -> None:
    if not matches:
        return

    count         = len(matches)
    wins          = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    total_kills   = sum(m["kills"]   for m in matches)
    total_deaths  = sum(m["deaths"]  for m in matches)
    total_assists = sum(m["assists"] for m in matches)
    total_hs      = sum(m.get("headshots", 0) for m in matches)

    # Per-map breakdown
    map_stats: dict[str, dict] = {}
    for m in matches:
        mp = m.get("map", "Unknown")
        if mp not in map_stats:
            map_stats[mp] = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0}
        map_stats[mp]["games"]   += 1
        map_stats[mp]["wins"]    += 1 if str(m.get("result", "")).lower() == "win" else 0
        map_stats[mp]["kills"]   += m["kills"]
        map_stats[mp]["deaths"]  += m["deaths"]
        map_stats[mp]["assists"] += m["assists"]

    map_breakdown = [
        {
            "map":      mp,
            "games":    s["games"],
            "win_rate": round(s["wins"] / s["games"] * 100, 1),
            "avg_kda":  calculate_kda(s["kills"], s["deaths"], s["assists"]),
        }
        for mp, s in sorted(map_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    summary = {
        "steam_id":         steam_id,
        "total_matches":    count,
        "wins":             wins,
        "losses":           count - wins,
        "win_rate":         round(wins / count * 100, 1) if count else 0,
        "total_kills":      total_kills,
        "total_deaths":     total_deaths,
        "total_assists":    total_assists,
        "average_kills":    round(total_kills   / count, 2) if count else 0,
        "average_deaths":   round(total_deaths  / count, 2) if count else 0,
        "average_assists":  round(total_assists / count, 2) if count else 0,
        "average_kda":      calculate_kda(total_kills, total_deaths, total_assists),
        "headshot_pct":     round(total_hs / total_kills * 100, 1) if total_kills else 0,
        "latest_rating":    latest.get("rating", 0),
        "map_breakdown":    map_breakdown,
        "updated_at":       datetime.now(timezone.utc).isoformat(),
    }

    collection.update_one(
        {"steam_id": steam_id},
        {"$set": summary},
        upsert=True,
    )
    print(f"[MongoDB]  Player summary upserted for {steam_id}")


# ── 5. Full flow for one player ───────────────────────────────────────────────

def get_player(matches_col, players_col, steam_id: str) -> None:
    print(f"\n[Tracker]  Fetching matches for steam_id={steam_id}...")
    raw_matches = get_all_matches(steam_id)

    if not raw_matches:
        print(f"  No matches found for {steam_id}.")
        return

    parsed = [parse_match(m, steam_id) for m in raw_matches]
    parsed = [m for m in parsed if m]

    inserted = updated = 0
    for match in parsed:
        action = upsert_match(matches_col, match)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_col, steam_id, parsed)

    print(f"\n── Results for {steam_id} ────────────────────────")
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

    steam_id = input("Enter Steam64 ID (e.g. 76561198106274751): ").strip()
    if not steam_id.isdigit():
        print("[ERROR] Steam64 ID should be numeric, e.g. 76561198106274751")
        return

    get_player(matches_col, players_col, steam_id)


if __name__ == "__main__":
    run()
