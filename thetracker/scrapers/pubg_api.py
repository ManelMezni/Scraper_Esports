"""
pubg_api.py
------------
PUBG stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.
"""

from flask import Flask, jsonify
from pymongo import MongoClient
from pubg_db import (
    get_all_matches as scrape_matches,
    parse_match,
    upsert_match,
    upsert_player_summary,
)

app = Flask(__name__)

# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.pubg
matches_collection = db.matches
players_collection = db.players


# ── Helper functions ─────────────────────────────────────────────────────────

def performance_rating(placement: int) -> str:
    if placement == 1:
        return "Chicken Dinner"
    if placement <= 10:
        return "Top 10"
    if placement <= 25:
        return "Mid"
    return "Early Death"


def serialize_doc(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def serialize_docs(docs: list) -> list:
    return [serialize_doc(d) for d in docs]


def calculate_player_stats(player_name: str) -> dict | None:
    matches = list(matches_collection.find({"player_name": player_name}))
    if not matches:
        return None

    count = len(matches)
    placements = [m.get("placement", 0) for m in matches if m.get("placement")]

    wins = sum(1 for p in placements if p == 1)
    top10s = sum(1 for p in placements if p <= 10)
    avg_placement = round(sum(placements) / len(placements), 2) if placements else 0

    total_kills = sum(m.get("kills", 0) for m in matches)
    total_dmg = sum(m.get("damage_dealt", 0) for m in matches)

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    most_recent = sorted_matches[0] if sorted_matches else None

    return {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "top10_rate":        round(top10s / count * 100, 1) if count else 0,
        "average_placement": avg_placement,
        "best_placement":    min(placements) if placements else None,
        "total_kills":       total_kills,
        "average_kills":     round(total_kills / count, 2) if count else 0,
        "average_damage":    round(total_dmg / count, 1) if count else 0,
        "last_match_performance": performance_rating(most_recent["placement"]) if most_recent else None,
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "PUBG API is running"})


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


@app.route("/player/<player_name>/stats")
def get_player_stats(player_name):
    stats = calculate_player_stats(player_name)
    if not stats:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404
    return jsonify(stats)


@app.route("/player/<player_name>/matches")
def get_player_matches(player_name):
    matches = list(matches_collection.find({"player_name": player_name}))
    if not matches:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404
    return jsonify({"count": len(matches), "matches": serialize_docs(matches)})


@app.route("/fetch/<player_name>")
def fetch_player(player_name):
    raw_matches = scrape_matches(player_name)
    if not raw_matches:
        return jsonify({"error": f"No matches found for {player_name}"}), 404

    parsed = [parse_match(m, player_name) for m in raw_matches]
    parsed = [m for m in parsed if m]

    inserted = updated = 0
    for match in parsed:
        action = upsert_match(matches_collection, match)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_collection, player_name, parsed)

    return jsonify({
        "player":   player_name,
        "fetched":  len(parsed),
        "inserted": inserted,
        "updated":  updated,
    })


if __name__ == "__main__":
    app.run(debug=True)
