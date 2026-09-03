"""
TFT stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.
"""

from bson import ObjectId
from flask import Flask, jsonify
from pymongo import MongoClient
from tft_db import (
    get_all_matches as scrape_matches,
    parse_match,
    upsert_match,
    upsert_player_summary
)


# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.tft
matches_collection = db.matches
players_collection = db.players

app = Flask(__name__)


# ── Helper functions ─────────────────────────────────────────────────────────

def performance_rating(placement: int) -> str:
    """Simple performance label based on TFT placement (1-8)."""
    if placement == 1:
        return "Win"
    if placement <= 4:
        return "Top 4"
    if placement <= 6:
        return "Mid"
    return "Bottom 2"


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

    count = len(matches)
    placements = [m.get("placement", 0) for m in matches if m.get("placement")]

    wins = sum(1 for p in placements if p == 1)
    top4s = sum(1 for p in placements if p <= 4)
    avg_placement = round(sum(placements) / len(placements), 2) if placements else 0

    # Most recent match (by date if available)
    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    most_recent = sorted_matches[0] if sorted_matches else None

    trait_counts: dict[str, int] = {}
    for m in matches:
        for t in m.get("traits", []):
            trait_counts[t] = trait_counts.get(t, 0) + 1
    top_traits = sorted(trait_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "top4_rate":         round(top4s / count * 100, 1) if count else 0,
        "average_placement": avg_placement,
        "best_placement":    min(placements) if placements else None,
        "worst_placement":   max(placements) if placements else None,
        "favorite_traits":   [t[0] for t in top_traits],
        "last_match_performance": performance_rating(most_recent["placement"]) if most_recent else None,
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "TFT API is running"})


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
    full_riot_id = f"{player_name}#{tagline}"
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