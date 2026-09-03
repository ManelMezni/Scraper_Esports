"""
Valorant stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.
"""

from bson import ObjectId
from flask import Flask, jsonify
from pymongo import MongoClient
from valorant_db import (
    get_all_matches as scrape_matches,
    parse_match,
    upsert_match,
    upsert_player_summary
)


# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.valorant
matches_collection = db.matches
players_collection = db.players

app = Flask(__name__)


# ── Helper functions ─────────────────────────────────────────────────────────

def calculate_kda(kills: int, deaths: int, assists: int) -> float:
    """KDA = (kills + assists) / deaths. Avoid division by zero."""
    if deaths == 0:
        return float(kills + assists)
    return round((kills + assists) / deaths, 2)


def performance_rating(kills: int, deaths: int, assists: int) -> str:
    """
    Simple performance label based on a score:
    score = kills * 2 + assists - deaths
    """
    score = kills * 2 + assists - deaths

    if score >= 40:
        return "MVP"
    if score >= 25:
        return "Excellent"
    if score >= 10:
        return "Good"
    if score >= 0:
        return "Average"
    return "Poor"


def serialize_doc(doc: dict | None) -> dict | None:
    """Convert MongoDB document to JSON-friendly dict (ObjectId -> string)."""
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def serialize_docs(docs: list) -> list:
    """Serialize a list of MongoDB documents."""
    return [serialize_doc(d) for d in docs]


def calculate_player_stats(player_name: str) -> dict | None:
    """Aggregate player stats from all matches in MongoDB."""
    matches = list(matches_collection.find({"player_name": player_name}))
    if not matches:
        return None

    wins = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    losses = len(matches) - wins
    total_kills = sum(m.get("kills", 0) for m in matches)
    total_deaths = sum(m.get("deaths", 0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)
    count = len(matches)

    acs_values = [m["acs"] for m in matches if m.get("acs") is not None]
    avg_acs = round(sum(acs_values) / len(acs_values), 1) if acs_values else None

    # Most recent rank (by date if available, else last document)
    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    rank = sorted_matches[0].get("rank") if sorted_matches else None

    avg_kills = round(total_kills / count, 2)
    avg_deaths = round(total_deaths / count, 2)
    avg_assists = round(total_assists / count, 2)
    avg_kda = calculate_kda(total_kills, total_deaths, total_assists)

    return {
        "player_name": player_name,
        "total_matches": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / count * 100, 1) if count else 0,
        "total_kills": total_kills,
        "total_deaths": total_deaths,
        "total_assists": total_assists,
        "average_kills": avg_kills,
        "average_deaths": avg_deaths,
        "average_assists": avg_assists,
        "average_kda": avg_kda,
        "average_acs": avg_acs,
        "rank": rank,
        "performance": performance_rating(avg_kills, avg_deaths, avg_assists),
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "Valorant API is running"})


@app.route("/matches")
def get_all_matches():
    matches = serialize_docs(list(matches_collection.find()))
    return jsonify({"count": len(matches), "matches": matches})


@app.route("/matches/<match_id>")
def get_match(match_id):
    match = matches_collection.find_one({"match_id": match_id})
    if not match:
        return jsonify({"error": f"Match '{match_id}' not found"}), 404
    return jsonify(serialize_doc(match))


@app.route("/players")
def get_all_players():
    players = serialize_docs(list(players_collection.find()))
    return jsonify({"count": len(players), "players": players})


@app.route("/player/<player_name>/<tagline>/stats")
def get_player_stats(player_name, tagline):
    # Combine them back to match your database format (e.g., "Michmich#ACE")
    full_riot_id = f"{player_name}#{tagline}"
    
    # Pass the full string to your data function
    stats = calculate_player_stats(full_riot_id)
    
    if not stats:
        return jsonify({"error": f"Player '{full_riot_id}' not found"}), 404
    return jsonify(stats)

@app.route("/player/<player_name>/<tagline>/matches")
def get_player_matches(player_name, tagline):
    full_riot_id = f"{player_name}#{tagline}"
    matches = list(matches_collection.find({"player_name": full_riot_id}))
    if not matches:
        return jsonify({"error": f"Player '{full_riot_id}' not found"}), 404
    return jsonify({"count": len(matches), "matches": serialize_docs(matches)})


@app.route("/fetch/<player_name>/<tagline>")
def fetch_player(player_name, tagline):
    player_encoded = f"{player_name}%23{tagline}"
    full_riot_id = f"{player_name}#{tagline}"

    raw_matches = scrape_matches(player_encoded) 
    if not raw_matches:
        return jsonify({"error": f"No matches found for {full_riot_id}"}), 404

    parsed = [parse_match(m, full_riot_id) for m in raw_matches]
    parsed = [m for m in parsed if m]

    inserted = updated = 0
    for match in parsed:
        action = upsert_match(matches_collection, match)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_collection, full_riot_id, parsed)

    return jsonify({
        "player": full_riot_id,
        "fetched": len(parsed),
        "inserted": inserted,
        "updated": updated,
    })



if __name__ == "__main__":
    app.run(debug=True)
