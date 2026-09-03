"""
for_honor_tracker_mongo.py
-----------------------------
Fetches For Honor profile/stats data from tracker.gg's internal API and
saves to MongoDB. Same pattern as the other titles — no login/cookies,
just standard headers. Cloudflare may block this (403/429, or a stalled
connection that times out) — that's expected.

IMPORTANT: like Fortnite, this endpoint returns a STATS SNAPSHOT (segments
of aggregated stats), not a list of individual matches. For Honor's stats
here are split across a few dimensions we've confirmed from real samples:
  - gameType (pvp/pve), each with attacker/defender splits
  - KDA broken down by target type: Player / Minion / Commander / Unk. Enemy
Hero-level breakdown (Warden, Kensei, etc.) is NOT confirmed to be in this
response — if you find it (search the raw JSON for "hero"), tell me and
I'll extend parse_profile() to capture it.

Requirements:
    pip install requests pymongo

Usage:
    python for_honor_tracker_mongo.py
    → Enter platform (psn/xbl/steam/ubi) and player name, e.g. psn / Jupiter_Anan5

Notes:
    tracker.gg's internal API is undocumented and can change without notice.
    Set PRINT_RAW = True once, inspect raw_sample.json, and confirm/adjust
    field names before trusting the parsed output — especially to check
    for hero-level data we haven't confirmed yet.
"""

import json
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "for_honor"
PRINT_RAW = False   # set True to dump the raw JSON for inspection
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


# ── 1. Fetch a player's full profile ─────────────────────────────────────────

def get_profile(platform: str, player_name: str) -> dict | None:
    url = f"https://api.tracker.gg/api/v2/for-honor/standard/profile/{platform}/{player_name}"

    try:
        print(f"  Fetching profile for {player_name} ({platform})...")
        r = requests.get(url, headers=HEADERS, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        print("  → Likely Cloudflare stalling the connection instead of a clean 403.")
        return None

    data = handle_response(r, f"profile {player_name}")

    if PRINT_RAW and data:
        with open("raw_sample.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  [DEBUG] Raw sample written to raw_sample.json")

    return data


# ── 2. Fetch a specific gameType segment (pvp/pve) with attacker/defender ────

def get_game_type_segment(platform: str, player_name: str, game_type: str) -> dict | None:
    """
    game_type: "pvp" or "pve" — matches the URL you found:
    .../profile/{platform}/{name}/segments/gameType?gameType=pve
    """
    url = f"https://api.tracker.gg/api/v2/for-honor/standard/profile/{platform}/{player_name}/segments/gameType"
    params = {"gameType": game_type}

    try:
        print(f"  Fetching {game_type} segment for {player_name} ({platform})...")
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Request failed: {e}")
        return None

    return handle_response(r, f"{game_type} segment for {player_name}")


# ── 3. Extract a stat value out of a stats block (handles category suffixes) ─

def _stat(stats: dict, key: str) -> float:
    return stats.get(key, {}).get("value", 0) or 0


# ── 4. Parse the general profile into a flat stats dict ─────────────────────

def parse_profile(data: dict, player_name: str, platform: str) -> dict | None:
    try:
        payload = data.get("data", {})
        segments = payload.get("segments", [])

        # Overall/general segment (usually the first or type == "overview")
        overall = next((s for s in segments if s.get("type") in ("overview", "general")), segments[0] if segments else {})
        stats = overall.get("stats", {})

        return {
            "player_name": player_name,
            "platform":    platform,
            "matches_played":       int(_stat(stats, "matchesPlayed")),
            "wins":                 int(_stat(stats, "wins")),
            "losses":               int(_stat(stats, "losses")),
            "win_rate":             round(_stat(stats, "winRate") or _stat(stats, "wlPercentage"), 2),
            "kills":                int(_stat(stats, "kills")),
            "deaths":               int(_stat(stats, "deaths")),
            "assists":              int(_stat(stats, "assists")),
            "kda_ratio":            round(_stat(stats, "kdaRatio"), 2),

            # Target-type KDA split (confirmed from real sample)
            "kda_by_target": {
                "player":    round(_stat(stats, "kdaRatioP"), 2),
                "minion":    round(_stat(stats, "kdaRatioM"), 2),
                "commander": round(_stat(stats, "kdaRatioC"), 2),
                "unknown":   round(_stat(stats, "kdaRatioX"), 2),
            },

            # Attacker/Defender role split (confirmed from real sample)
            "attacker_defender": {
                "matches_attacker": int(_stat(stats, "matchesPlayedAttacker")),
                "matches_defender": int(_stat(stats, "matchesPlayedDefender")),
                "ties_attacker":    int(_stat(stats, "tiesAttacker")),
                "ties_defender":    int(_stat(stats, "tiesDefender")),
            },

            "rank":       stats.get("rank", {}).get("metadata", {}).get("name", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"  [Skipped profile] {e}")
        return None


# ── 5. Upsert profile snapshot into MongoDB ──────────────────────────────────

def upsert_profile(collection, profile: dict) -> str:
    result = collection.update_one(
        {"player_name": profile["player_name"], "platform": profile["platform"]},
        {"$set": profile, "$push": {"history": {
            "captured_at": profile["updated_at"],
            "matches_played": profile["matches_played"],
            "kda_ratio": profile["kda_ratio"],
        }}},
        upsert=True,
    )
    return "inserted" if result.upserted_id else "updated"


# ── 6. Full flow for one player ───────────────────────────────────────────────

def get_player(players_col, platform: str, player_name: str) -> None:
    print(f"\n[Tracker]  Fetching For Honor profile for {player_name} ({platform})...")
    raw = get_profile(platform, player_name)

    if not raw:
        print(f"  No profile found for {player_name}.")
        return

    profile = parse_profile(raw, player_name, platform)
    if not profile:
        print("  Could not parse profile response.")
        return

    action = upsert_profile(players_col, profile)

    print(f"\n── Result for {player_name} ────────────────────────")
    print(f"  Matches played : {profile['matches_played']}")
    print(f"  Action         : {action}")
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

    players_col = db["players"]

    platform = input("Enter platform (psn/xbl/steam/ubi): ").strip().lower()
    if platform not in ("psn", "xbl", "steam", "ubi"):
        print("[ERROR] Platform should be one of: psn, xbl, steam, ubi")
        return

    player_name = input("Enter player name (e.g. Jupiter_Anan5): ").strip()
    if not player_name:
        print("[ERROR] Please enter a player name.")
        return

    get_player(players_col, platform, player_name)


if __name__ == "__main__":
    run()
