"""
update.py
---------
Run this manually whenever you want fresh data:

    python update.py

What it does:
  1. Calls Tracker.gg using the existing get_all_matches() logic
  2. Connects to local MongoDB (mongodb://localhost:27017)
  3. Upserts each match (insert if new, skip/update if it already exists)
  4. Prints a summary of how many matches were new vs already in the DB

This script is the ONLY part of the project that talks to Tracker.gg.
The Flask API never calls Tracker.gg directly.
"""

import requests
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

PLAYER   = "TenZ%2300005"
SEASON   = "ce2783e8-44fc-dd48-3da3-33b5ba6c4a22"
PLATFORM = "pc"
MODE     = "competitive"

BASE_URL = f"https://api.tracker.gg/api/v2/valorant/standard/matches/riot/{PLAYER}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    "https://tracker.gg/",
    "Accept":     "application/json",
}

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "valorant"
COLLECTION_NAME = "matches"


def get_all_matches():
    """Pulls every page of match history from Tracker.gg. Unchanged from
    the original collector script."""
    all_matches = []
    page = 0

    while True:
        params = {
            "platform": PLATFORM,
            "season":   SEASON,
            "type":     MODE,
            "next":     page,
        }

        print(f"Fetching page {page}...")
        r = requests.get(BASE_URL, headers=HEADERS, params=params)

        if r.status_code != 200:
            print(f"Error {r.status_code}: {r.text[:200]}")
            break

        data = r.json()
        matches = data.get("data", {}).get("matches", [])

        if not matches:
            print("No more matches!")
            break

        all_matches.extend(matches)
        print(f"  Got {len(matches)} matches (total: {len(all_matches)})")
        page += 1

    return all_matches


def parse_match(match):
    """Turns one raw Tracker.gg match into a clean dict ready for MongoDB.
    Returns None if the match is malformed and should be skipped."""
    try:
        meta     = match["metadata"]
        seg_meta = match["segments"][0]["metadata"]
        stats    = match["segments"][0]["stats"]

        kills  = stats.get("kills",  {}).get("value", 0)
        deaths = stats.get("deaths", {}).get("value", 1)

        # match_id is what we de-duplicate on. Tracker.gg matches have
        # their own id in metadata; fall back to a composite key if missing.
        match_id = match.get("attributes", {}).get("id") or meta.get("id")
        if not match_id:
            match_id = f"{meta.get('timestamp')}_{seg_meta.get('agentName')}_{kills}_{deaths}"

        return {
            "match_id":     match_id,
            "date":         meta.get("timestamp", ""),
            "map":          meta.get("mapName", ""),
            "agent":        seg_meta.get("agentName", ""),
            "result":       meta.get("result", ""),
            "kills":        kills,
            "deaths":       deaths,
            "assists":      stats.get("assists", {}).get("value", 0),
            "kd":           round(kills / deaths, 2) if deaths else kills,
            "acs":          round(stats.get("scorePerRound", {}).get("value", 0), 1),
            "hs_percent":   round(stats.get("headshotsPercentage", {}).get("value", 0), 1),
            "dd_delta":     stats.get("damageDelta", {}).get("value", 0),
            "damage":       stats.get("damage", {}).get("value", 0),
            "headshots":    stats.get("dealtHeadshots", {}).get("value", 0),
            "first_bloods": stats.get("firstBloods", {}).get("value", 0),
            "plants":       stats.get("plants", {}).get("value", 0),
            "defuses":      stats.get("defuses", {}).get("value", 0),
            "kast":         stats.get("kAST", {}).get("displayValue", ""),
            "rank_name":    stats.get("rank", {}).get("metadata", {}).get("tierName", ""),
        }
    except Exception as e:
        print(f"Skipped a match while parsing: {e}")
        return None


def update_database(matches):
    """Upserts parsed matches into MongoDB using match_id as the unique key.
    New matches are inserted, existing ones are updated in place, nothing
    is ever duplicated."""
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")  # forces a connection check now
    except ConnectionFailure:
        print("\n Could not connect to MongoDB at", MONGO_URI)
        print("   Is the MongoDB service running? Check Compass or your services list.")
        return

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    # Unique index on match_id -> guarantees no duplicates even if this
    # script is run many times. Safe to call every run, it's a no-op if
    # the index already exists.
    collection.create_index("match_id", unique=True)

    inserted = 0
    updated = 0
    skipped = 0

    for raw_match in matches:
        doc = parse_match(raw_match)
        if doc is None:
            skipped += 1
            continue

        result = collection.update_one(
            {"match_id": doc["match_id"]},
            {"$set": doc},
            upsert=True,
        )

        if result.upserted_id is not None:
            inserted += 1
        elif result.modified_count > 0:
            updated += 1
        # else: matched but nothing changed, data was already identical

    client.close()

    print("\n--- Update summary ---")
    print(f"  New matches inserted : {inserted}")
    print(f"  Existing matches updated: {updated}")
    print(f"  Skipped (parse errors)  : {skipped}")
    print(f"  Total processed       : {len(matches)}")


if __name__ == "__main__":
    matches = get_all_matches()
    if matches:
        update_database(matches)
    else:
        print("\nNo matches fetched from Tracker.gg - database not touched.")
