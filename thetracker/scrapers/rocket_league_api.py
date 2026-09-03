"""
rocket_league_api.py
-----------------------
Rocket League stats Flask API.
Reads daily activity heatmap data from MongoDB and exposes JSON endpoints.

Unlike CS2/Valorant/PUBG/R6/Marvel Rivals, this data is a per-day
activity heatmap (matches played + rating change per day), not
individual matches — so there's no /matches/<id> endpoint here.
"""

from flask import Flask, jsonify
from pymongo import MongoClient
from rocket_league_db import (
    get_heatmap,
    parse_day,
    upsert_day,
    upsert_player_summary,
   
)

app = Flask(__name__)

# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.rocket_league
days_collection = db.daily_activity
trends_collection = db.daily_trends
rank_history_collection = db.rank_history
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
    return jsonify({"message": "Rocket League API is running"})


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


@app.route("/player/<platform>/<player_name>/heatmap")
def get_player_heatmap(platform, player_name):
    days = list(days_collection.find({"player_name": player_name, "platform": platform}).sort("date", 1))
    if not days:
        return jsonify({"error": f"Player '{player_name}' ({platform}) not found"}), 404
    return jsonify({"player": player_name, "platform": platform, "count": len(days), "days": serialize_docs(days)})

@app.route("/fetch/<platform>/<player_name>")
def fetch_player(platform, player_name):
    if platform not in ("psn", "xbl", "steam", "epic"):
        return jsonify({"error": "platform must be one of: psn, xbl, steam, epic"}), 400

    raw_days = get_heatmap(platform, player_name)
    if not raw_days:
        return jsonify({"error": f"No data found for {player_name}"}), 404

    parsed = [parse_day(d, player_name, platform) for d in raw_days]
    parsed = [d for d in parsed if d]

    inserted = updated = 0
    for day in parsed:
        action = upsert_day(days_collection, day)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_collection, player_name, platform, parsed)

    return jsonify({
        "player":   player_name,
        "platform": platform,
        "fetched":  len(parsed),
        "inserted": inserted,
        "updated":  updated,
    })


if __name__ == "__main__":
    app.run(debug=True)
