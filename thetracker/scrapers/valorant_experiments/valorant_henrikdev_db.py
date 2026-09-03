"""
Valorant match scraper using the Henrik Dev API.
Fetches matches, upserts into MongoDB, rebuilds player summaries, and exports CSV.
"""

import csv
from collections import defaultdict
from datetime import datetime, timezone

import requests
from pymongo import MongoClient

# ── Config ───────────────────────────────────────────────────────────────────
API_KEY = "PUT_YOUR_HENRIK_API_KEY_HERE"
GAME_NAME = "Michmich"
TAG_LINE = "ACE"
REGION = "eu"
NUM_MATCHES = 10

HENRIK_BASE_URL = "https://api.henrikdev.xyz/valorant/v3/matches"
HEADERS = {"Authorization": API_KEY}

# ── MongoDB ────────────────────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017/")
db = client["valorant"]
matches_col = db["matches"]
players_col = db["players"]

MATCH_CSV = "valorant_stats.csv"
PLAYERS_CSV = "players_export.csv"


def calculate_kda(kills: int, deaths: int, assists: int) -> float:
    """KDA = (kills + assists) / deaths. Avoid division by zero."""
    if deaths == 0:
        return float(kills + assists)
    return round((kills + assists) / deaths, 2)


def fetch_matches() -> list:
    """
    Fetch recent matches from the Henrik Dev API.
    No PUUID required — uses region, game name, and tag directly.
    """
    url = f"{HENRIK_BASE_URL}/{REGION}/{GAME_NAME}/{TAG_LINE}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as exc:
        print(f"[ERROR] Request failed: {exc}")
        return []

    if response.status_code != 200:
        print(f"[ERROR] Henrik API returned {response.status_code}")
        print(response.text)
        return []

    data = response.json().get("data", [])
    matches = data[:NUM_MATCHES]
    print(f"[OK] Fetched {len(matches)} match(es) for {GAME_NAME}#{TAG_LINE}")
    return matches


def parse_match(raw: dict) -> dict | None:
    """
    Parse a Henrik API match into a clean MongoDB document.
    Uses match['metadata'] and match['players']['all_players'].
    """
    metadata = raw.get("metadata", {})
    all_players = raw.get("players", {}).get("all_players", [])

    match_id = metadata.get("matchid")
    if not match_id:
        print("[WARN] Skipping match with no match_id")
        return None

    winner = metadata.get("winner")
    parsed_players = []

    for player in all_players:
        stats = player.get("stats", {})
        kills = int(stats.get("kills", 0))
        deaths = int(stats.get("deaths", 0))
        assists = int(stats.get("assists", 0))
        team = player.get("team")
        won = team == winner if winner else False

        parsed_players.append({
            "name": f"{player.get('name', 'unknown')}#{player.get('tag', '')}",
            "agent": player.get("character"),
            "team": team,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "score": stats.get("score", 0),
            "headshots": stats.get("headshots", 0),
            "rank": player.get("currenttier_patched"),
            "won": won,
            "result": "Win" if won else "Loss",
            "kda": calculate_kda(kills, deaths, assists),
        })

    return {
        "match_id": match_id,
        "map": metadata.get("map"),
        "mode": metadata.get("mode"),
        "region": metadata.get("region"),
        "date": metadata.get("game_start"),
        "rounds_played": metadata.get("rounds_played"),
        "winner": winner,
        "players": parsed_players,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def upsert_match(match_doc: dict) -> None:
    """Insert or update a match document keyed by match_id."""
    matches_col.update_one(
        {"match_id": match_doc["match_id"]},
        {"$set": match_doc},
        upsert=True,
    )


def rebuild_player_summaries() -> list[dict]:
    """
    Rebuild all player summaries from the matches collection.
    Avoids double-counting when the scraper is run multiple times.
    """
    aggregates: dict[str, dict] = defaultdict(lambda: {
        "total_kills": 0,
        "total_deaths": 0,
        "total_assists": 0,
        "matches_played": 0,
        "wins": 0,
    })

    for match in matches_col.find():
        for player in match.get("players", []):
            name = player["name"]
            agg = aggregates[name]
            agg["total_kills"] += player.get("kills", 0)
            agg["total_deaths"] += player.get("deaths", 0)
            agg["total_assists"] += player.get("assists", 0)
            agg["matches_played"] += 1
            if player.get("won"):
                agg["wins"] += 1
            if player.get("rank"):
                agg["rank"] = player["rank"]

    summaries = []
    for name, agg in aggregates.items():
        mp = agg["matches_played"]
        summary = {
            "name": name,
            "total_kills": agg["total_kills"],
            "total_deaths": agg["total_deaths"],
            "total_assists": agg["total_assists"],
            "matches_played": mp,
            "wins": agg["wins"],
            "kda": calculate_kda(agg["total_kills"], agg["total_deaths"], agg["total_assists"]),
            "win_rate": round(agg["wins"] / mp * 100, 1) if mp else 0.0,
            "avg_kills": round(agg["total_kills"] / mp, 2) if mp else 0.0,
            "avg_deaths": round(agg["total_deaths"] / mp, 2) if mp else 0.0,
            "rank": agg.get("rank"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        players_col.update_one({"name": name}, {"$set": summary}, upsert=True)
        summaries.append(summary)

    return summaries


def export_csv() -> None:
    """Export flat match rows and player summaries to CSV files."""
    # ── Matches: one row per player per match ──────────────────────────────
    match_rows = []
    for match in matches_col.find({}, {"_id": 0}):
        for player in match.get("players", []):
            match_rows.append({
                "match_id": match.get("match_id"),
                "map": match.get("map"),
                "mode": match.get("mode"),
                "date": match.get("date"),
                "player_name": player.get("name"),
                "agent": player.get("agent"),
                "result": player.get("result"),
                "kills": player.get("kills"),
                "deaths": player.get("deaths"),
                "assists": player.get("assists"),
                "kda": player.get("kda"),
                "rank": player.get("rank"),
            })

    if match_rows:
        match_fields = list(match_rows[0].keys())
        with open(MATCH_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=match_fields)
            writer.writeheader()
            writer.writerows(match_rows)
        print(f"[OK] Exported {len(match_rows)} match rows to {MATCH_CSV}")
    else:
        print("[WARN] No match data to export.")

    # ── Players: summary stats ─────────────────────────────────────────────
    player_rows = list(players_col.find({}, {"_id": 0}))
    if player_rows:
        player_fields = list(player_rows[0].keys())
        with open(PLAYERS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=player_fields)
            writer.writeheader()
            writer.writerows(player_rows)
        print(f"[OK] Exported {len(player_rows)} players to {PLAYERS_CSV}")
    else:
        print("[WARN] No player data to export.")


def main() -> None:
    print("=== Henrik Valorant Scraper ===\n")

    raw_matches = fetch_matches()
    if not raw_matches:
        print("[ERROR] No matches found. Check your API key, region, or Riot ID.")
        return

    stored = 0
    for raw in raw_matches:
        match_doc = parse_match(raw)
        if not match_doc:
            continue
        upsert_match(match_doc)
        stored += 1
        print(f"  Upserted match {match_doc['match_id']} ({match_doc.get('map')})")

    summaries = rebuild_player_summaries()
    export_csv()

    print(f"\n[DONE] {stored} match(es) stored in MongoDB.")
    print(f"       {len(summaries)} player summary(s) updated.")


if __name__ == "__main__":
    main()
