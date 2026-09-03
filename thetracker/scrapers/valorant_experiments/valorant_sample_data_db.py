"""
Valorant data updater / scraper.
Fetches match data (sample data for now), parses it, and upserts into MongoDB.
Optionally exports to CSV for testing.
"""

import csv
from datetime import datetime, timezone

from pymongo import MongoClient

# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.valorant
matches_collection = db.matches
players_collection = db.players


def calculate_kda(kills: int, deaths: int, assists: int) -> float:
    """KDA = (kills + assists) / deaths. Avoid division by zero."""
    if deaths == 0:
        return float(kills + assists)
    return round((kills + assists) / deaths, 2)


# ── Sample dataset (used when live scraping/API is not ready) ────────────────
SAMPLE_MATCHES = [
    {
        "match_id": "match_001",
        "player_name": "TenZ",
        "map": "Ascent",
        "agent": "Jett",
        "result": "Win",
        "kills": 23,
        "deaths": 12,
        "assists": 8,
        "acs": 290,
        "headshot_percent": 31.4,
        "rank": "Radiant",
        "date": "2026-06-22",
    },
    {
        "match_id": "match_002",
        "player_name": "TenZ",
        "map": "Bind",
        "agent": "Reyna",
        "result": "Loss",
        "kills": 18,
        "deaths": 16,
        "assists": 5,
        "acs": 245,
        "headshot_percent": 28.0,
        "rank": "Radiant",
        "date": "2026-06-21",
    },
    {
        "match_id": "match_003",
        "player_name": "TenZ",
        "map": "Haven",
        "agent": "Jett",
        "result": "Win",
        "kills": 27,
        "deaths": 10,
        "assists": 6,
        "acs": 310,
        "headshot_percent": 35.2,
        "rank": "Radiant",
        "date": "2026-06-20",
    },
    {
        "match_id": "match_004",
        "player_name": "ScreaM",
        "map": "Lotus",
        "agent": "Raze",
        "result": "Win",
        "kills": 21,
        "deaths": 14,
        "assists": 7,
        "acs": 275,
        "headshot_percent": 29.5,
        "rank": "Immortal 3",
        "date": "2026-06-22",
    },
    {
        "match_id": "match_005",
        "player_name": "ScreaM",
        "map": "Split",
        "agent": "Phoenix",
        "result": "Loss",
        "kills": 14,
        "deaths": 18,
        "assists": 4,
        "acs": 198,
        "headshot_percent": 22.1,
        "rank": "Immortal 3",
        "date": "2026-06-21",
    },
]


def parse_match(raw: dict) -> dict:
    """Normalize a raw match dict into a clean MongoDB-friendly structure."""
    kills = int(raw["kills"])
    deaths = int(raw["deaths"])
    assists = int(raw["assists"])

    return {
        "match_id": raw["match_id"],
        "player_name": raw["player_name"],
        "map": raw["map"],
        "agent": raw["agent"],
        "result": raw["result"],
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "kda": calculate_kda(kills, deaths, assists),
        "acs": raw.get("acs"),
        "headshot_percent": raw.get("headshot_percent"),
        "rank": raw.get("rank"),
        "date": raw.get("date"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_matches():
    """
    Fetch match data from an external source.
    For now, returns sample data. Replace with Tracker.gg / Riot API later.
    """
    print("Using sample match data (live scraping not configured).")
    return SAMPLE_MATCHES


def upsert_match(match: dict) -> None:
    """Insert or update a match document keyed by match_id + player_name."""
    matches_collection.update_one(
        {"match_id": match["match_id"], "player_name": match["player_name"]},
        {"$set": match},
        upsert=True,
    )


def build_player_summary(player_name: str, matches: list[dict]) -> dict:
    """Build a player summary document from their match list."""
    wins = sum(1 for m in matches if m["result"].lower() == "win")
    losses = len(matches) - wins
    total_kills = sum(m["kills"] for m in matches)
    total_deaths = sum(m["deaths"] for m in matches)
    total_assists = sum(m["assists"] for m in matches)
    count = len(matches)

    acs_values = [m["acs"] for m in matches if m.get("acs") is not None]
    avg_acs = round(sum(acs_values) / len(acs_values), 1) if acs_values else None

    # Use the most recent rank from matches (last in list)
    rank = matches[-1].get("rank") if matches else None

    return {
        "player_name": player_name,
        "total_matches": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / count * 100, 1) if count else 0,
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_assists": total_assists,
        "average_kills": round(total_kills / count, 2) if count else 0,
        "average_deaths": round(total_deaths / count, 2) if count else 0,
        "average_assists": round(total_assists / count, 2) if count else 0,
        "average_kda": calculate_kda(total_kills, total_deaths, total_assists),
        "average_acs": avg_acs,
        "rank": rank,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def upsert_players(parsed_matches: list[dict]) -> None:
    """Upsert player summary documents into the players collection."""
    players: dict[str, list[dict]] = {}
    for match in parsed_matches:
        players.setdefault(match["player_name"], []).append(match)

    for player_name, player_matches in players.items():
        summary = build_player_summary(player_name, player_matches)
        players_collection.update_one(
            {"player_name": player_name},
            {"$set": summary},
            upsert=True,
        )


def save_to_csv(matches: list[dict], filename: str = "valorant_stats.csv") -> None:
    """Optional CSV export for testing / debugging."""
    if not matches:
        print("No matches to export.")
        return

    fieldnames = [
        "match_id", "player_name", "map", "agent", "result",
        "kills", "deaths", "assists", "kda", "acs",
        "headshot_percent", "rank", "date",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            writer.writerow({k: match.get(k) for k in fieldnames})

    print(f"Exported {len(matches)} matches to {filename}")


def run():
    """Main entry point: fetch, parse, upsert to MongoDB, optionally export CSV."""
    raw_matches = fetch_matches()
    parsed_matches = [parse_match(m) for m in raw_matches]

    for match in parsed_matches:
        upsert_match(match)

    upsert_players(parsed_matches)
    save_to_csv(parsed_matches)

    print(f"\nDone! Upserted {len(parsed_matches)} matches into MongoDB.")
    print(f"  Database: valorant")
    print(f"  Collections: matches, players")


if __name__ == "__main__":
    run()
