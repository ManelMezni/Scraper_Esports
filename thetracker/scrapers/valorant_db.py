"""
valorant_tracker_mongo.py
--------------------------
Fetches Valorant match data from tracker.gg internal API and saves to MongoDB.

Requirements:
    pip install requests pymongo

Usage:
    python valorant_tracker_mongo.py
    → Enter: TenZ#00005  or  Michmich#ACE
"""

import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "valorant"
PLATFORM  = "pc"
MODE      = "competitive"
SEASON    = "ce2783e8-44fc-dd48-3da3-33b5ba6c4a22"
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

def get_all_matches(player_encoded: str) -> list[dict]:
    url = f"https://api.tracker.gg/api/v2/valorant/standard/matches/riot/{player_encoded}"
    all_matches = []
    page = 0

    while True:
        params = {
            "platform": PLATFORM,
            "season":   SEASON,
            "type":     MODE,
            "next":     page,
        }

        print(f"  Fetching page {page}...")
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        data = handle_response(r, f"matches page {page}")

        if not data:
            break

        matches = data.get("data", {}).get("matches", [])
        if not matches:
            print("  No more matches.")
            break

        all_matches.extend(matches)
        print(f"  Got {len(matches)} matches (total: {len(all_matches)})")
        page += 1

    return all_matches


# ── 2. Parse a single raw match ───────────────────────────────────────────────

def parse_match(match: dict, player_name: str) -> dict | None:
    try:
        meta     = match["metadata"]
        seg_meta = match["segments"][0]["metadata"]
        stats    = match["segments"][0]["stats"]

        kills   = int(stats.get("kills",   {}).get("value", 0))
        deaths  = int(stats.get("deaths",  {}).get("value", 0))
        assists = int(stats.get("assists", {}).get("value", 0))

        return {
            "match_id":         match.get("attributes", {}).get("id", ""),
            "player_name":      player_name,
            "date":             meta.get("timestamp", ""),
            "map":              meta.get("mapName", ""),
            "agent":            seg_meta.get("agentName", ""),
            "result":           meta.get("result", ""),
            "kills":            kills,
            "deaths":           deaths,
            "assists":          assists,
            "kda":              calculate_kda(kills, deaths, assists),
            "acs":              round(stats.get("scorePerRound",        {}).get("value", 0), 1),
            "headshot_percent": round(stats.get("headshotsPercentage",  {}).get("value", 0), 1),
            "damage":           stats.get("damage",       {}).get("value", 0),
            "damage_delta":     stats.get("damageDelta",  {}).get("value", 0),
            "first_bloods":     stats.get("firstBloods",  {}).get("value", 0),
            "plants":           stats.get("plants",       {}).get("value", 0),
            "defuses":          stats.get("defuses",      {}).get("value", 0),
            "kast":             stats.get("kAST",         {}).get("displayValue", ""),
            "rank":             stats.get("rank", {}).get("metadata", {}).get("tierName", ""),
            "updated_at":       datetime.now(timezone.utc).isoformat(),
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
    wins          = sum(1 for m in matches if m["result"].lower() == "win")
    total_kills   = sum(m["kills"]   for m in matches)
    total_deaths  = sum(m["deaths"]  for m in matches)
    total_assists = sum(m["assists"] for m in matches)
    acs_values    = [m["acs"] for m in matches if m.get("acs")]

    summary = {
        "player_name":     player_name,
        "total_matches":   count,
        "wins":            wins,
        "losses":          count - wins,
        "win_rate":        round(wins / count * 100, 1) if count else 0,
        "total_kills":     total_kills,
        "total_deaths":    total_deaths,
        "total_assists":   total_assists,
        "average_kills":   round(total_kills   / count, 2) if count else 0,
        "average_deaths":  round(total_deaths  / count, 2) if count else 0,
        "average_assists": round(total_assists / count, 2) if count else 0,
        "average_kda":     calculate_kda(total_kills, total_deaths, total_assists),
        "average_acs":     round(sum(acs_values) / len(acs_values), 1) if acs_values else 0,
        "rank":            matches[-1].get("rank", ""),
        "updated_at":      datetime.now(timezone.utc).isoformat(),
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
    player_encoded = f"{name}%23{tag}"

    print(f"\n[Tracker]  Fetching matches for {player_name}...")
    raw_matches = get_all_matches(player_encoded)

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

    riot_id = input("Enter Riot ID (e.g. TenZ#00005): ").strip()
    if "#" not in riot_id:
        print("[ERROR] Please include the tagline, e.g. TenZ#00005")
        return

    name, tag = riot_id.split("#", 1)
    get_player(matches_col, players_col, name, tag)


if __name__ == "__main__":
    run()
