"""
tft_tracker_mongo.py
--------------------------
Fetches TFT match data from tracker.gg's internal API and saves to MongoDB.
Same pattern as valorant_tracker_mongo.py — no login/cookies, just standard
headers. Because of that, tracker.gg's Cloudflare protection may block this
frequently (403s) — that's expected and handled below, same as the Valorant
version.

NOTE: I couldn't verify tracker.gg's exact TFT response schema (unlike the
Valorant one you already had working), so parse_match() below is a best
guess based on tracker.gg's usual conventions (metadata/segments/stats).
Once you get a live 200 response, print the raw JSON once and adjust the
field names in parse_match() to match what actually comes back.

Requirements:
    pip install requests pymongo

Usage:
    python tft_tracker_mongo.py
    → Enter: CookieMonster274#EUNE
"""

import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "tft"
QUEUE     = "RANKED_TFT"     # tracker.gg queue filter
SEASON    = None             # e.g. "2026-04-15T08:00:00+00:00" — leave None to skip
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
        return "1st (Win)"
    if placement <= 4:
        return f"Top 4 ({placement}th)"
    return f"Bottom 4 ({placement}th)"


# ── 1. Fetch all matches for a player ────────────────────────────────────────

def get_all_matches(player_encoded: str) -> list[dict]:
    url = f"https://api.tracker.gg/api/v2/tft/standard/matches/riot/{player_encoded}"
    all_matches = []
    page = 0

    while True:
        params = {"queue": QUEUE, "next": page}
        if SEASON:
            params["season"] = SEASON

        print(f"  Fetching page {page}...")
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Request failed on page {page}: {e}")
            print("  → This is usually Cloudflare stalling the connection instead of returning a clean 403.")
            break

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
        meta  = match["metadata"]
        stats = match["segments"][0]["stats"]

        placement = int(stats.get("placement", {}).get("value", 0))

        traits = [
            t.get("name", "")
            for t in match["segments"][0].get("metadata", {}).get("traits", [])
            if t.get("tierCurrent", 0) > 0
        ]
        units = [
            u.get("name", "")
            for u in match["segments"][0].get("metadata", {}).get("units", [])
        ]

        return {
            "match_id":     match.get("attributes", {}).get("id", ""),
            "player_name":  player_name,
            "date":         meta.get("timestamp", ""),
            "queue":        meta.get("queueType", QUEUE),
            "placement":    placement,
            "result_bucket": placement_bucket(placement) if placement else "",
            "level":        int(stats.get("level", {}).get("value", 0)),
            "gold_left":    int(stats.get("goldLeft", {}).get("value", 0)),
            "damage_dealt": int(stats.get("totalDamageToPlayers", {}).get("value", 0)),
            "traits":       traits,
            "units":        units,
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

    count      = len(matches)
    placements = [m["placement"] for m in matches if m.get("placement")]
    wins       = sum(1 for p in placements if p == 1)
    top4s      = sum(1 for p in placements if p <= 4)
    avg_place  = round(sum(placements) / len(placements), 2) if placements else 0

    trait_counts: dict[str, int] = {}
    for m in matches:
        for t in m.get("traits", []):
            trait_counts[t] = trait_counts.get(t, 0) + 1
    top_traits = sorted(trait_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    summary = {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "top4_rate":         round(top4s / count * 100, 1) if count else 0,
        "average_placement": avg_place,
        "best_placement":    min(placements) if placements else None,
        "worst_placement":   max(placements) if placements else None,
        "favorite_traits":   [t[0] for t in top_traits],
        "updated_at":        datetime.now(timezone.utc).isoformat(),
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

    riot_id = input("Enter Riot ID (e.g. CookieMonster274#EUNE): ").strip()
    if "#" not in riot_id:
        print("[ERROR] Please include the tagline, e.g. CookieMonster274#EUNE")
        return

    name, tag = riot_id.split("#", 1)
    get_player(matches_col, players_col, name, tag)


if __name__ == "__main__":
    run()