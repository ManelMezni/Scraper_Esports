
"""
cs2_api.py
-----------
Counter-Strike 2 stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.

Run:
    python cs2_api.py

Endpoints:
    GET  /                                  → health check
    GET  /players                           → all players
    GET  /matches                           → all matches
    GET  /matches/<match_id>                → single match
    GET  /player/<steam_id>/stats           → player summary + map breakdown
    GET  /player/<steam_id>/matches         → all matches for a player
    GET  /player/<steam_id>/maps            → map breakdown only
    GET  /fetch/<steam_id>                  → scrape tracker.gg + upsert to MongoDB
"""

from flask import Flask, jsonify, json
from pymongo import MongoClient
from cs2_db import (
    get_all_matches as scrape_matches,
    parse_match,
    upsert_match,
    upsert_player_summary,
    calculate_kda,
)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


# ── MongoDB connection ────────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.cs2
matches_collection = db.matches
players_collection = db.players


# ── Helper functions ──────────────────────────────────────────────────────────

def performance_rating(avg_kills: float, avg_deaths: float, avg_assists: float) -> str:
    score = avg_kills * 2 + avg_assists - avg_deaths
    if score >= 15:
        return "Godlike"
    if score >= 10:
        return "Excellent"
    if score >= 5:
        return "Good"
    if score >= 0:
        return "Average"
    return "Poor"


def serialize_doc(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    result = dict(doc)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result


def serialize_docs(docs: list) -> list:
    return [serialize_doc(d) for d in docs]


def calculate_player_stats(steam_id: str) -> dict | None:
    matches = list(matches_collection.find({"steam_id": steam_id}))
    if not matches:
        return None

    count         = len(matches)
    wins          = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    total_kills   = sum(m.get("kills",   0) for m in matches)
    total_deaths  = sum(m.get("deaths",  0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)
    total_hs      = sum(m.get("headshots", 0) for m in matches)

    avg_kills   = round(total_kills   / count, 2)
    avg_deaths  = round(total_deaths  / count, 2)
    avg_assists = round(total_assists / count, 2)

    # Per-map breakdown
    map_stats: dict[str, dict] = {}
    for m in matches:
        mp = m.get("map", "Unknown")
        if mp not in map_stats:
            map_stats[mp] = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0}
        map_stats[mp]["games"]   += 1
        map_stats[mp]["wins"]    += 1 if str(m.get("result", "")).lower() == "win" else 0
        map_stats[mp]["kills"]   += m.get("kills", 0)
        map_stats[mp]["deaths"]  += m.get("deaths", 0)
        map_stats[mp]["assists"] += m.get("assists", 0)

    map_breakdown = [
        {
            "map":      mp,
            "games":    s["games"],
            "win_rate": round(s["wins"] / s["games"] * 100, 1),
            "avg_kda":  calculate_kda(s["kills"], s["deaths"], s["assists"]),
        }
        for mp, s in sorted(map_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    return {
        "steam_id":         steam_id,
        "total_matches":    count,
        "wins":             wins,
        "losses":           count - wins,
        "win_rate":         round(wins / count * 100, 1) if count else 0,
        "total_kills":      total_kills,
        "total_deaths":     total_deaths,
        "total_assists":    total_assists,
        "average_kills":    avg_kills,
        "average_deaths":   avg_deaths,
        "average_assists":  avg_assists,
        "average_kda":      calculate_kda(total_kills, total_deaths, total_assists),
        "headshot_pct":     round(total_hs / total_kills * 100, 1) if total_kills else 0,
        "latest_rating":    latest.get("rating", 0),
        "map_breakdown":    map_breakdown,
        "performance":      performance_rating(avg_kills, avg_deaths, avg_assists),
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "CS2 API is running"})


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
    return app.response_class(
        response=json.dumps({"count": len(players), "players": players}, ensure_ascii=False, indent=2),
        mimetype="application/json"
    )


@app.route("/player/<steam_id>/stats")
def get_player_stats(steam_id):
    stats = calculate_player_stats(steam_id)
    if not stats:
        return jsonify({"error": f"Player '{steam_id}' not found"}), 404
    return jsonify(stats)


@app.route("/player/<steam_id>/matches")
def get_player_matches(steam_id):
    matches = list(matches_collection.find({"steam_id": steam_id}))
    if not matches:
        return jsonify({"error": f"Player '{steam_id}' not found"}), 404
    return jsonify({"count": len(matches), "matches": serialize_docs(matches)})


@app.route("/player/<steam_id>/maps")
def get_player_maps(steam_id):
    stats = calculate_player_stats(steam_id)
    if not stats:
        return jsonify({"error": f"Player '{steam_id}' not found"}), 404
    return jsonify({
        "player": steam_id,
        "maps":   stats["map_breakdown"],
    })


@app.route("/fetch/<steam_id>")
def fetch_player(steam_id):
    raw_matches = scrape_matches(steam_id)
    if not raw_matches:
        return jsonify({"error": f"No matches found for {steam_id}"}), 404

    parsed = [parse_match(m, steam_id) for m in raw_matches]
    parsed = [m for m in parsed if m]

    inserted = updated = 0
    for match in parsed:
        action = upsert_match(matches_collection, match)
        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    upsert_player_summary(players_collection, steam_id, parsed)

    return jsonify({
        "player":   steam_id,
        "fetched":  len(parsed),
        "inserted": inserted,
        "updated":  updated,
    })


if __name__ == "__main__":
    app.run(debug=True)
