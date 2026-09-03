"""
lol_tracker_mongo.py
---------------------
Fetches League of Legends match data from tracker.gg internal API and saves to MongoDB.

Requirements:
    pip install requests pymongo

Usage:
    python lol_tracker_mongo.py
    → Enter: Faker#KR1  or  Caps#EUW  or  16 γραμμες#11111  or  Paweł#1111
"""

import requests
from datetime import datetime, timezone
from urllib.parse import quote          # ← FIX: handles ALL unicode/spaces/special chars
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "league"
PLATFORM  = "riot"
# Ranked Solo/Duo = 420, Ranked Flex = 440
RANKED_QUEUE_IDS = {420, 440}
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


# ── 1. Fetch all ranked matches for a player ─────────────────────────────────

def get_all_matches(player_encoded: str) -> list[dict]:
    """
    Hits tracker.gg's LoL matches endpoint page by page.
    Uses cursor-based pagination (string 'next' token).
    Filters to ranked queues (420 Solo/Duo, 440 Flex) via attributes.queueId.
    """
    url = f"https://api.tracker.gg/api/v2/lol/standard/matches/riot/{player_encoded}"
    all_matches = []
    cursor = None

    while True:
        params: dict = {"platform": PLATFORM}
        if cursor:
            params["next"] = cursor

        print(f"  Fetching page (cursor={cursor})...")
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        data = handle_response(r, f"matches cursor={cursor}")

        if not data:
            break

        payload = data.get("data", {})
        matches = payload.get("matches", [])

        if not matches:
            print("  No more matches.")
            break

        # FIX: queueId lives in attributes{}, NOT metadata{}
        ranked = [
            m for m in matches
            if m.get("attributes", {}).get("queueId") in RANKED_QUEUE_IDS
        ]
        all_matches.extend(ranked)
        print(f"  Got {len(ranked)} ranked (of {len(matches)}) — total: {len(all_matches)}")

        # Advance cursor — also lives in data.metadata, not data itself
        cursor = payload.get("metadata", {}).get("next")
        if not cursor:
            print("  Reached last page.")
            break

    return all_matches


# ── 2. Parse a single raw match ───────────────────────────────────────────────

def parse_match(match: dict, player_name: str) -> dict | None:
    try:
        meta     = match.get("metadata", {})
        attrs    = match.get("attributes", {})
        segs     = match.get("segments", [])

        if not segs:
            return None

        seg      = segs[0]
        seg_meta = seg.get("metadata", {})
        stats    = seg.get("stats", {})

        def val(key: str):
            """Safely extract numeric value from a stats entry."""
            return stats.get(key, {}).get("value", 0) or 0

        kills   = int(val("kills"))
        deaths  = int(val("deaths"))
        assists = int(val("assists"))

        # FIX: queueId comes from attributes, map result from metadata
        queue_id   = attrs.get("queueId", 0)
        queue_name = {420: "Ranked Solo/Duo", 440: "Ranked Flex"}.get(queue_id, "Ranked")

        # FIX: result lives in metadata.outcome or segments[0].metadata.outcome
        result = (
            meta.get("outcome")
            or seg_meta.get("outcome")
            or meta.get("result")
            or ""
        )

        return {
            "match_id":           attrs.get("id", ""),
            "player_name":        player_name,
            "date":               meta.get("timestamp", ""),
            "map":                meta.get("mapName", "Summoner's Rift"),
            "queue":              queue_name,
            "champion":           seg_meta.get("championName", ""),
            "role":               seg_meta.get("role", ""),
            "position":           seg_meta.get("individualPosition", ""),
            "result":             result,
            "kills":              kills,
            "deaths":             deaths,
            "assists":            assists,
            "kda":                calculate_kda(kills, deaths, assists),
            "kda_ratio":          round(float(val("kdaRatio")), 2),
            "kill_participation": round(float(val("killParticipation")) * 100, 1),
            "tier":               stats.get("tier", {}).get("metadata", {}).get("tierName", ""),
            "lp":                 int(val("leaguePoints")),
            "lp_change":          int(val("lpChange")),
            "updated_at":         datetime.now(timezone.utc).isoformat(),
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

    # Per-champion breakdown
    champ_stats: dict[str, dict] = {}
    for m in matches:
        c = m.get("champion", "Unknown")
        if c not in champ_stats:
            champ_stats[c] = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0}
        champ_stats[c]["games"]   += 1
        champ_stats[c]["wins"]    += 1 if str(m.get("result", "")).lower() == "win" else 0
        champ_stats[c]["kills"]   += m["kills"]
        champ_stats[c]["deaths"]  += m["deaths"]
        champ_stats[c]["assists"] += m["assists"]

    champion_breakdown = [
        {
            "champion": c,
            "games":    s["games"],
            "win_rate": round(s["wins"] / s["games"] * 100, 1),
            "avg_kda":  calculate_kda(s["kills"], s["deaths"], s["assists"]),
        }
        for c, s in sorted(champ_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    summary = {
        "player_name":        player_name,
        "total_matches":      count,
        "wins":               wins,
        "losses":             count - wins,
        "win_rate":           round(wins / count * 100, 1) if count else 0,
        "total_kills":        total_kills,
        "total_deaths":       total_deaths,
        "total_assists":      total_assists,
        "average_kills":      round(total_kills   / count, 2) if count else 0,
        "average_deaths":     round(total_deaths  / count, 2) if count else 0,
        "average_assists":    round(total_assists / count, 2) if count else 0,
        "average_kda":        calculate_kda(total_kills, total_deaths, total_assists),
        "tier":               latest.get("tier", ""),
        "lp":                 latest.get("lp", 0),
        "champion_breakdown": champion_breakdown,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }

    collection.update_one(
        {"player_name": player_name},
        {"$set": summary},
        upsert=True,
    )
    print(f"[MongoDB]  Player summary upserted for {player_name}")


# ── 5. Full flow for one player ───────────────────────────────────────────────

def get_player(matches_col, players_col, name: str, tag: str) -> None:
    player_name    = f"{name}#{tag}"
    # FIX: use quote() so ANY character (Greek, Polish, spaces, etc.) is encoded
    player_encoded = quote(player_name, safe="")

    print(f"\n[Tracker]  Fetching matches for {player_name}...")
    raw_matches = get_all_matches(player_encoded)

    if not raw_matches:
        print(f"  No ranked matches found for {player_name}.")
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

    riot_id = input("Enter Riot ID (e.g. Faker#KR1): ").strip()
    if "#" not in riot_id:
        print("[ERROR] Please include the tagline, e.g. Faker#KR1")
        return

    name, tag = riot_id.split("#", 1)
    get_player(matches_col, players_col, name, tag)


if __name__ == "__main__":
    run()