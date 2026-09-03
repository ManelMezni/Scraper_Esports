"""
lol_api.py
-----------
League of Legends stats Flask API.
Reads match and player data from MongoDB and exposes JSON endpoints.

Run:
    python lol_api.py

Endpoints:
    GET  /                                      → health check
    GET  /players                               → all players
    GET  /matches                               → all matches
    GET  /matches/<match_id>                    → single match
    GET  /player/<name>/<tag>/stats             → player summary + champion breakdown
    GET  /player/<name>/<tag>/matches           → all matches for a player
    GET  /player/<name>/<tag>/champions         → champion breakdown only
    GET  /fetch?id=<Name#TAG>                   → scrape tracker.gg + upsert to MongoDB
"""

from urllib.parse import quote, unquote 
from flask import Flask, jsonify, request, json 
from pymongo import MongoClient 
from lol_db import ( get_all_matches as scrape_matches, parse_match, upsert_match, upsert_player_summary, calculate_kda, ) 
app = Flask(__name__) 
app.config["JSON_AS_ASCII"] = False 



# ── MongoDB connection ────────────────────────────────────────────────────────
client = MongoClient("mongodb://localhost:27017")
db = client.league
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


def calculate_player_stats(player_name: str) -> dict | None:
    matches = list(matches_collection.find({"player_name": player_name}))
    if not matches:
        return None

    count         = len(matches)
    wins          = sum(1 for m in matches if str(m.get("result", "")).lower() == "win")
    total_kills   = sum(m.get("kills",   0) for m in matches)
    total_deaths  = sum(m.get("deaths",  0) for m in matches)
    total_assists = sum(m.get("assists", 0) for m in matches)

    avg_kills   = round(total_kills   / count, 2)
    avg_deaths  = round(total_deaths  / count, 2)
    avg_assists = round(total_assists / count, 2)

    # Per-champion breakdown
    champ_stats: dict[str, dict] = {}
    for m in matches:
        c = m.get("champion", "Unknown")
        if c not in champ_stats:
            champ_stats[c] = {"games": 0, "wins": 0, "kills": 0, "deaths": 0, "assists": 0}
        champ_stats[c]["games"]   += 1
        champ_stats[c]["wins"]    += 1 if str(m.get("result", "")).lower() == "win" else 0
        champ_stats[c]["kills"]   += m.get("kills", 0)
        champ_stats[c]["deaths"]  += m.get("deaths", 0)
        champ_stats[c]["assists"] += m.get("assists", 0)

    champion_breakdown = [
        {
            "champion": c,
            "games":    s["games"],
            "win_rate": round(s["wins"] / s["games"] * 100, 1),
            "avg_kda":  calculate_kda(s["kills"], s["deaths"], s["assists"]),
        }
        for c, s in sorted(champ_stats.items(), key=lambda x: -x[1]["games"])
    ]

    sorted_matches = sorted(matches, key=lambda m: m.get("date", ""), reverse=True)
    latest = sorted_matches[0] if sorted_matches else {}

    return {
        "player_name":        player_name,
        "total_matches":      count,
        "wins":               wins,
        "losses":             count - wins,
        "win_rate":           round(wins / count * 100, 1) if count else 0,
        "total_kills":        total_kills,
        "total_deaths":       total_deaths,
        "total_assists":      total_assists,
        "average_kills":      avg_kills,
        "average_deaths":     avg_deaths,
        "average_assists":    avg_assists,
        "average_kda":        calculate_kda(total_kills, total_deaths, total_assists),
        "tier":               latest.get("tier", ""),
        "lp":                 latest.get("lp", 0),
        "champion_breakdown": champion_breakdown,
        "performance":        performance_rating(avg_kills, avg_deaths, avg_assists),
    }


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return jsonify({"message": "League of Legends API is running"})


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



# FIX: use <path:...> so names with spaces/unicode don't break Flask routing
@app.route("/player/<path:player_name>/<tagline>/stats")
def get_player_stats(player_name, tagline):
    full_riot_id = unquote(f"{player_name}#{tagline}")
    stats = calculate_player_stats(full_riot_id)
    if not stats:
        return jsonify({"error": f"Player '{full_riot_id}' not found"}), 404
    return jsonify(stats)


@app.route("/player/<path:player_name>/<tagline>/matches")
def get_player_matches(player_name, tagline):
    full_riot_id = unquote(f"{player_name}#{tagline}")
    matches = list(matches_collection.find({"player_name": full_riot_id}))
    if not matches:
        return jsonify({"error": f"Player '{full_riot_id}' not found"}), 404
    return jsonify({"count": len(matches), "matches": serialize_docs(matches)})


@app.route("/player/<path:player_name>/<tagline>/champions")
def get_player_champions(player_name, tagline):
    full_riot_id = unquote(f"{player_name}#{tagline}")
    stats = calculate_player_stats(full_riot_id)
    if not stats:
        return jsonify({"error": f"Player '{full_riot_id}' not found"}), 404
    return jsonify({
        "player":    full_riot_id,
        "champions": stats["champion_breakdown"],
    })


# FIX: switched from path segments to query param → works for ALL riot IDs
# Usage: /fetch?id=Faker#KR1   or   /fetch?id=16 γραμμες#11111
@app.route("/fetch/<player_name>/<tagline>")
def fetch_player(player_name, tagline):
    player_encoded = f"{quote(player_name)}%23{quote(tagline)}"
    full_riot_id = f"{player_name}#{tagline}"

    raw_matches = scrape_matches(player_encoded)
    if not raw_matches:
        return jsonify({"error": f"No ranked matches found for {full_riot_id}"}), 404

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
        "player":   full_riot_id,
        "fetched":  len(parsed),
        "inserted": inserted,
        "updated":  updated,
    })





if __name__ == "__main__":
    app.run(debug=True)