"""
app.py
------
The Flask API. This NEVER calls Tracker.gg. It only reads data that
update.py already stored in MongoDB.

Run with:
    python app.py

Then visit:
    http://127.0.0.1:5000/
    http://127.0.0.1:5000/matches
    http://127.0.0.1:5000/matches/<match_id>
    http://127.0.0.1:5000/player/TenZ/stats
"""

from flask import Flask, jsonify
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

app = Flask(__name__)

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "valorant"
COLLECTION_NAME = "matches"


def get_collection():
    """Opens a fresh connection to the matches collection. Raises if
    MongoDB isn't reachable, so callers can return a clean error instead
    of a raw stack trace."""
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    return client[DB_NAME][COLLECTION_NAME], client


@app.route("/")
def home():
    return jsonify({"status": "ok", "service": "valorant-stats-api"})


@app.route("/matches")
def matches():
    try:
        collection, client = get_collection()
        docs = list(collection.find({}, {"_id": 0}))  # hide Mongo's internal _id
        client.close()
        return jsonify({"count": len(docs), "matches": docs})
    except ConnectionFailure:
        return jsonify({"error": "Database unavailable"}), 503


@app.route("/matches/<match_id>")
def match_by_id(match_id):
    try:
        collection, client = get_collection()
        doc = collection.find_one({"match_id": match_id}, {"_id": 0})
        client.close()
        if doc is None:
            return jsonify({"error": "Match not found"}), 404
        return jsonify(doc)
    except ConnectionFailure:
        return jsonify({"error": "Database unavailable"}), 503


@app.route("/player/TenZ/stats")
def player_stats():
    try:
        collection, client = get_collection()
        docs = list(collection.find({}, {"_id": 0}))
        client.close()

        if not docs:
            return jsonify({"error": "No matches stored yet. Run update.py first."}), 404

        total = len(docs)
        wins = sum(1 for d in docs if str(d.get("result", "")).lower() == "win")

        avg_kills  = sum(d.get("kills", 0) for d in docs) / total
        avg_deaths = sum(d.get("deaths", 0) for d in docs) / total
        avg_assists = sum(d.get("assists", 0) for d in docs) / total
        avg_acs    = sum(d.get("acs", 0) for d in docs) / total
        avg_hs     = sum(d.get("hs_percent", 0) for d in docs) / total

        return jsonify({
            "total_matches": total,
            "wins": wins,
            "win_rate_percent": round(wins / total * 100, 1),
            "avg_kills": round(avg_kills, 2),
            "avg_deaths": round(avg_deaths, 2),
            "avg_assists": round(avg_assists, 2),
            "avg_acs": round(avg_acs, 1),
            "avg_hs_percent": round(avg_hs, 1),
        })
    except ConnectionFailure:
        return jsonify({"error": "Database unavailable"}), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
