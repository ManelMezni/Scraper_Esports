from flask import Flask, jsonify

app = Flask(__name__)

def performance_rating(kills, deaths, assists):
    score = kills * 2 + assists - deaths

    if score >= 40:
        return "MVP"
    elif score >= 25:
        return "Excellent"
    elif score >= 15:
        return "Good"
    else:
        return "Average"

@app.route("/stats")
def stats():
    kills = 23
    deaths = 12
    assists = 8

    kda = round((kills + assists) / deaths, 2)

    return jsonify({
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "rank": "Radiant",
        "kda": kda,
        "performance": performance_rating(kills, deaths, assists)
    })
if __name__ == "__main__":
    app.run(debug=True)