from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "ok"})

@app.route("/player/TenZ")
def tenz():
    return jsonify({
        "kills": 23,
        "deaths": 12,
        "assists": 8,
        "rank": "Radiant"
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)