from flask import Flask, jsonify, render_template, request
import requests

from trading import analyze, backtest, fetch_candles
from trading.data import BINANCE_BASE

app = Flask(__name__)

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


def _float_arg(name, default=None):
    value = request.args.get(name)
    return float(value) if value not in (None, "") else default


@app.route("/analyze")
def analyze_route():
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    interval = request.args.get("interval", "1h")
    try:
        candles = fetch_candles(symbol, interval, request.args.get("limit", 500))
        result = analyze(
            candles,
            balance=_float_arg("balance"),
            risk_pct=_float_arg("risk", 1.0),
            min_rr=_float_arg("minRR", 1.5),
        )
        if request.args.get("candles") == "1":
            result["candles"] = candles
        return jsonify({"symbol": symbol, "interval": interval, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/mtf")
def multi_timeframe():
    """Multi-timeframe confluence: a trade is strongest when all timeframes agree."""
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    intervals = request.args.get("intervals", "4h,1h,15m").split(",")
    try:
        frames = {}
        for interval in intervals:
            result = analyze(fetch_candles(symbol, interval, 500))
            frames[interval] = {
                "signal": result["signal"],
                "bias": result["bias"],
                "score": result["score"],
                "plan": result["plan"],
            }
        biases = {f["bias"] for f in frames.values()}
        aligned = len(biases) == 1 and "neutral" not in biases
        lowest = frames[intervals[-1]]
        return jsonify({
            "symbol": symbol,
            "aligned": aligned,
            "bias": biases.pop() if aligned else "mixed",
            "averageScore": round(sum(f["score"] for f in frames.values()) / len(frames), 1),
            "entryTimeframe": intervals[-1],
            "plan": lowest["plan"] if aligned else None,
            "frames": frames,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/backtest")
def backtest_route():
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    interval = request.args.get("interval", "1h")
    try:
        candles = fetch_candles(symbol, interval, request.args.get("limit", 1000))
        result = backtest(candles, min_rr=_float_arg("minRR", 1.5))
        return jsonify({"symbol": symbol, "interval": interval, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")
