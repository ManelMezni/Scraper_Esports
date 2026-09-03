"""
r6_api.py
----------
Rainbow Six Siege stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.
"""

from flask import Flask, jsonify
from pymongo import MongoClient
from r6_db import (
    get_all_matches as scrape_matches,
    parse_match,
    upsert_match,
    upsert_player_summary,
    calculate_kda,
)

app = Flask(__name__)

# ── MongoDB connection ──────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.r6siege
matches_collection = db.matches
players_collection = db.players


# ── Helper functions ─────────────────────────────────────────────────────────

def performance_rating(kills: int, deaths: int, assists: int) -> str:
    score = kills * 2 + assists - deaths
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


def calculate_player_stats(player_name: str) -> dict | None:
    matches = list(matches_collection.find({"player_name": player_name}))
    if not matches:
        return None

    count         = len(matches)
    wins          = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    total_kills   = sum(m.get("kills", 0)   for m in matches)
    total_deaths  = sum(m.get("deaths", 0)  for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)

    avg_kills   = round(total_kills   / count, 2)
    avg_deaths  = round(total_deaths  / count, 2)
    avg_assists = round(total_assists / count, 2)

    # Per-operator breakdown
    op_stats: dict[str, dict] = {}
    for m in matches:
        op = m.get("operator", "Unknown") or "Unknown"
        if op not in op_stats:
            op_stats[op] = {"games": 0, "kills": 0, "deaths": 0}
        op_stats[op]["games"]  += 1
        op_stats[op]["kills"]  += m.get("kills", 0)
        op_stats[op]["deaths"] += m.get("deaths", 0)

    operator_breakdown = [
        {"operator": op, "games": s["games"], "kd_ratio": round(s["kills"] / s["deaths"], 2) if s["deaths"] else float(s["kills"])}
        for op, s in sorted(op_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    return {
        "player_name":       player_name,
        "total_matches":     count,
        "wins":              wins,
        "losses":            count - wins,
        "win_rate":          round(wins / count * 100, 1) if count else 0,
        "total_kills":       total_kills,
        "total_deaths":      total_deaths,
        "total_assists":     total_assists,
        "average_kills":     avg_kills,
        "average_deaths":    avg_deaths,
        "average_assists":   avg_assists,
        "average_kda":       calculate_kda(total_kills, total_deaths, total_assists),
        "rank":              latest.get("rank", ""),
        "operator_breakdown": operator_breakdown,
        "performance":       performance_rating(avg_kills, avg_deaths, avg_assists),
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "R6 Siege API is running"})


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


@app.route("/player/<player_name>/operators")
def get_player_operators(player_name):
    stats = calculate_player_stats(player_name)
    if not stats:
        return jsonify({"error": f"Player '{player_name}' not found"}), 404
    return jsonify({"player": player_name, "operators": stats["operator_breakdown"]})


@app.route("/fetch/<platform>/<player_name>")
def fetch_player(platform, player_name):
    if platform not in ("psn", "xbl", "steam"):
        return jsonify({"error": "platform must be one of: psn, xbl, steam"}), 400

    raw_matches = scrape_matches(platform, player_name)
    if not raw_matches:
        return jsonify({"error": f"No matches found for {player_name}"}), 404

    parsed = [parse_match(m, player_name, platform) for m in raw_matches]
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
        "platform": platform,
        "fetched":  len(parsed),
        "inserted": inserted,
        "updated":  updated,
    })


if __name__ == "__main__":
    app.run(debug=True)
