from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

BINANCE_BASE = "https://data-api.binance.vision/api/v3/klines"

@app.route("/")
def home():
    return jsonify({"message": "Crypto Chart API is running"})

@app.route("/klines")
def klines():
    symbol = request.args.get("symbol", "BTCUSDT")
    interval = request.args.get("interval", "1h")
    limit = request.args.get("limit", "200")

    try:
        response = requests.get(
            BINANCE_BASE,
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            },
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        candles = []
        for row in data:
            candles.append({
                "openTime": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "closeTime": row[6]
            })

        return jsonify({
            "symbol": symbol,
            "interval": interval,
            "candles": candles
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
