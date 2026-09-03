"""
for_honor_api.py
-------------------
For Honor stats Flask API.
Reads player profile snapshots from MongoDB and exposes JSON endpoints.

Like Fortnite, this is a STATS SNAPSHOT per player, not individual matches —
so there's no /matches endpoint, just profile + gameType segment breakdown.
"""

from flask import Flask, jsonify
from pymongo import MongoClient
from for_honor_db import (
    get_profile,
    get_game_type_segment,
    parse_profile,
    upsert_profile,
)

app = Flask(__name__)

# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.for_honor
players_collection = db.players


# ── Helper functions ─────────────────────────────────────────────────────────

def serialize_doc(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def serialize_docs(docs: list) -> list:
    return [serialize_doc(d) for d in docs]


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "For Honor API is running"})


@app.route("/players")
def get_all_players():
    players = serialize_docs(list(players_collection.find()))
    return jsonify({"count": len(players), "players": players})


@app.route("/player/<platform>/<player_name>/stats")
def get_player_stats(platform, player_name):
    doc = players_collection.find_one({"player_name": player_name, "platform": platform})
    if not doc:
        return jsonify({"error": f"Player '{player_name}' ({platform}) not found"}), 404
    return jsonify(serialize_doc(doc))


@app.route("/player/<platform>/<player_name>/history")
def get_player_history(platform, player_name):
    doc = players_collection.find_one({"player_name": player_name, "platform": platform})
    if not doc:
        return jsonify({"error": f"Player '{player_name}' ({platform}) not found"}), 404
    return jsonify({"player": player_name, "platform": platform, "history": doc.get("history", [])})


@app.route("/fetch/<platform>/<player_name>")
def fetch_player(platform, player_name):
    raw = get_profile(platform, player_name)
    if not raw:
        return jsonify({"error": f"No profile found for {player_name}"}), 404

    profile = parse_profile(raw, player_name, platform)
    if not profile:
        return jsonify({"error": "Could not parse profile response"}), 500

    action = upsert_profile(players_collection, profile)

    return jsonify({
        "player":   player_name,
        "platform": platform,
        "action":   action,
        "stats":    profile,
    })


@app.route("/player/<platform>/<player_name>/gametype/<game_type>")
def get_gametype_segment(platform, player_name, game_type):
    """Raw pass-through of the gameType segment (pvp/pve) — not yet parsed
    into a clean shape since we're still confirming the full field set."""
    if game_type not in ("pvp", "pve"):
        return jsonify({"error": "game_type must be 'pvp' or 'pve'"}), 400

    data = get_game_type_segment(platform, player_name, game_type)
    if not data:
        return jsonify({"error": f"No {game_type} data found for {player_name}"}), 404
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True)
