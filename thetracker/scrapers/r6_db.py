"""
r6_tracker_mongo.py
---------------------
Fetches Rainbow Six Siege match data from tracker.gg's internal API and
saves to MongoDB. Same pattern as the PUBG/CS2/Valorant/TFT scripts — no
login/cookies, just standard headers. Cloudflare may block this (403/429,
or a stalled connection that times out) — that's expected.

Requirements:
    pip install requests pymongo

Usage:
    python r6_tracker_mongo.py
    → Enter platform (psn/xbl/steam) and player name, e.g. psn / jba8107z

Notes:
    tracker.gg's internal API is undocumented and can change without notice.
    Field paths in parse_match() are a best guess based on the shape used by
    the other tracker.gg titles (metadata / attributes / segments[0].stats).
    Set PRINT_RAW = True once, inspect raw_sample.json, and adjust field
    names (kills, deaths, rounds, result, etc.) before trusting the output.
"""

import json
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "r6siege"
MODE      = "ranked"   # "ranked", "casual", "unranked", etc. — matches type= param
SEASON    = ""         # empty = current/all seasons
PRINT_RAW = False      # set True to dump first page of raw JSON for inspection
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

def get_all_matches(platform: str, player_name: str) -> list[dict]:
    url = f"https://api.tracker.gg/api/v2/r6siege/standard/matches/{platform}/{player_name}"
    all_matches = []
    cursor = None
    page = 0

    while True:
        params = {"type": MODE}
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

def parse_match(match: dict, player_name: str, platform: str) -> dict | None:
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
        assists = int(val("assists") or val("kdAssists"))

        result = (
            meta.get("result")
            or seg_meta.get("result")
            or meta.get("outcome")
            or ""
        )

        return {
            "match_id":     attrs.get("id", match.get("id", "")),
            "player_name":  player_name,
            "platform":     platform,
            "date":         meta.get("timestamp", ""),
            "map":          meta.get("mapName", seg_meta.get("mapName", "")),
            "mode":         MODE,
            "result":       result,
            "kills":        kills,
            "deaths":       deaths,
            "assists":      assists,
            "kda":          calculate_kda(kills, deaths, assists),
            "kd_ratio":     round(float(val("kdRatio")), 2),
            "rounds_won":   int(val("roundsWon")),
            "rounds_lost":  int(val("roundsLost")),
            "operator":     seg_meta.get("operatorName", ""),
            "rank":         stats.get("rank", {}).get("metadata", {}).get("name", ""),
            "mmr":          int(val("mmr")),
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

    count         = len(matches)
    wins          = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    total_kills   = sum(m["kills"]   for m in matches)
    total_deaths  = sum(m["deaths"]  for m in matches)
    total_assists = sum(m["assists"] for m in matches)

    # Per-operator breakdown
    op_stats: dict[str, dict] = {}
    for m in matches:
        op = m.get("operator", "Unknown") or "Unknown"
        if op not in op_stats:
            op_stats[op] = {"games": 0, "kills": 0, "deaths": 0}
        op_stats[op]["games"]  += 1
        op_stats[op]["kills"]  += m["kills"]
        op_stats[op]["deaths"] += m["deaths"]

    operator_breakdown = [
        {"operator": op, "games": s["games"], "kd_ratio": round(s["kills"] / s["deaths"], 2) if s["deaths"] else float(s["kills"])}
        for op, s in sorted(op_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    summary = {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "losses":            count - wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "total_kills":       total_kills,
        "total_deaths":      total_deaths,
        "total_assists":     total_assists,
        "average_kills":     round(total_kills   / count, 2) if count else 0,
        "average_deaths":    round(total_deaths  / count, 2) if count else 0,
        "average_assists":   round(total_assists / count, 2) if count else 0,
        "average_kda":       calculate_kda(total_kills, total_deaths, total_assists),
        "rank":              latest.get("rank", ""),
        "operator_breakdown": operator_breakdown,
        "updated_at":        datetime.now(timezone.utc).isoformat(),
    }

    collection.update_one(
        {"player_name": player_name},
        {"$set": summary},
        upsert=True,
    )
    print(f"[MongoDB]  Player summary upserted for {player_name}")


# ── 5. Full flow for one player ───────────────────────────────────────────────

def get_player(matches_col, players_col, platform: str, player_name: str) -> None:
    print(f"\n[Tracker]  Fetching matches for {player_name} ({platform})...")
    raw_matches = get_all_matches(platform, player_name)

    if not raw_matches:
        print(f"  No matches found for {player_name}.")
        return

    parsed = [parse_match(m, player_name, platform) for m in raw_matches]
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

    platform = input("Enter platform (psn/xbl/steam): ").strip().lower()
    if platform not in ("psn", "xbl", "steam"):
        print("[ERROR] Platform should be one of: psn, xbl, steam")
        return

    player_name = input("Enter player name (e.g. jba8107z): ").strip()
    if not player_name:
        print("[ERROR] Please enter a player name.")
        return

    get_player(matches_col, players_col, platform, player_name)


if __name__ == "__main__":
    run()
