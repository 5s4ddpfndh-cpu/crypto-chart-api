import os
import time

from flask import Flask, jsonify, render_template, request
import requests

from trading import alerts, analyze, backtest, compare
from trading.data import BINANCE_BASE, fetch_market
from trading.markets import MARKETS, TIMEFRAMES, get_market
from trading.strategies import STRATEGIES, live_signal
from trading.strategy import _add_sizing

app = Flask(__name__)
app.json.ensure_ascii = False  # show Arabic text as-is in JSON responses

@app.route("/")
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

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


def _strategy_arg():
    strategy = request.args.get("strategy", "confluence")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}', choose one of {list(STRATEGIES)}")
    return strategy


def _market_arg():
    market = request.args.get("market", "btc")
    return market, get_market(market)


def _float_arg(name, default=None):
    value = request.args.get(name)
    return float(value) if value not in (None, "") else default


@app.route("/markets")
def markets_route():
    """Markets, timeframes and strategies, so the dashboard can build its menus."""
    return jsonify({
        "markets": {k: {"name": m["name"], "symbol": m["symbol"], "exness": m["exness"],
                        "feePct": m["fee_pct"], "cost": m["cost"], "note": m["note"]}
                    for k, m in MARKETS.items()},
        "timeframes": TIMEFRAMES,
        "strategies": {k: {"name": s["name"], "description": s["description"]} for k, s in STRATEGIES.items()},
    })


@app.route("/analyze")
def analyze_route():
    interval = request.args.get("interval", "1h")
    try:
        market, info = _market_arg()
        candles = fetch_market(market, interval, request.args.get("limit", 500))
        strategy = _strategy_arg()
        balance, risk_pct = _float_arg("balance"), _float_arg("risk", 1.0)
        result = analyze(candles, balance=balance, risk_pct=risk_pct,
                         min_rr=_float_arg("minRR", 1.5))
        if strategy != "confluence":
            # Zones, score and reasons still come from the main analysis as
            # context; the signal and plan come from the chosen strategy.
            plan = live_signal(candles, strategy, market=market)
            if plan:
                _add_sizing(plan, balance, risk_pct)
            result["plan"] = plan
            result["signal"] = {"long": "BUY", "short": "SELL"}[plan["side"]] if plan else "WAIT"
        result["strategy"] = strategy
        result["strategyName"] = STRATEGIES[strategy]["name"]
        result["lastCandleTime"] = candles[-1]["openTime"]
        if request.args.get("candles") == "1":
            result["candles"] = candles
        return jsonify({"market": market, "symbol": info["symbol"], "name": info["name"],
                        "note": info["note"], "interval": interval, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/mtf")
def multi_timeframe():
    """Multi-timeframe confluence: a trade is strongest when all timeframes agree."""
    intervals = request.args.get("intervals", "4h,1h,15m").split(",")
    try:
        market, info = _market_arg()
        frames = {}
        for interval in intervals:
            result = analyze(fetch_market(market, interval, 500))
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
            "market": market,
            "symbol": info["symbol"],
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
    interval = request.args.get("interval", "1h")
    try:
        market, info = _market_arg()
        candles = fetch_market(market, interval, request.args.get("limit", 5000))
        fee, cost = _float_arg("fee", info["fee_pct"]), _float_arg("cost", info["cost"])
        result = backtest(candles, _strategy_arg(), min_rr=_float_arg("minRR", 1.5),
                          fee_pct=fee, market=market, cost=cost)
        return jsonify({"market": market, "symbol": info["symbol"], "interval": interval,
                        "candleCount": len(candles), "feePct": fee, "cost": cost, **result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/compare")
def compare_route():
    """Backtest every strategy on the same candles and rank them."""
    interval = request.args.get("interval", "1h")
    try:
        market, info = _market_arg()
        fee, cost = _float_arg("fee", info["fee_pct"]), _float_arg("cost", info["cost"])
        candles = fetch_market(market, interval, request.args.get("limit", 5000))
        results = compare(candles, min_rr=_float_arg("minRR", 1.5), fee_pct=fee, market=market, cost=cost)
        return jsonify({
            "market": market,
            "symbol": info["symbol"],
            "interval": interval,
            "feePct": fee,
            "cost": cost,
            "candleCount": len(candles),
            "from": candles[0]["openTime"],
            "to": candles[-1]["openTime"],
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _alert_key_ok():
    key = os.environ.get("ALERT_KEY")
    return not key or request.args.get("key") == key


@app.route("/alerts/status")
def alerts_status():
    """What is configured, without revealing any secret."""
    try:
        watched = [{"market": m, "interval": i, "strategy": s} for m, i, s in alerts.watchlist()]
        error = None
    except Exception as e:
        watched, error = [], str(e)
    return jsonify({
        "botToken": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        "chatId": bool(os.environ.get("TELEGRAM_CHAT_ID")),
        "alertKey": bool(os.environ.get("ALERT_KEY")),
        "watchlist": watched,
        "error": error,
        # Resets when the server restarts; a recent time means the scheduler is calling us.
        "lastCheckMinutesAgo": round((time.time() - alerts.last_check["time"]) / 60, 1)
                               if alerts.last_check["time"] else None,
        "checksSinceRestart": alerts.last_check["count"],
        "lastResults": alerts.last_check["results"],
    })


@app.route("/alerts/chat-id")
def alerts_chat_id():
    if not _alert_key_ok():
        return jsonify({"error": "wrong key"}), 403
    try:
        chats = alerts.recent_chats()
        hint = None if chats else "أرسل أي رسالة لبوتك في Telegram ثم حدّث هذه الصفحة"
        return jsonify({"chats": chats, "hint": hint})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/alerts/test")
def alerts_test():
    if not _alert_key_ok():
        return jsonify({"error": "wrong key"}), 403
    try:
        alerts.send_message("✅ التنبيهات تعمل! ستصلك هنا إشارات الذهب وناسداك على فريم 4 ساعات.")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/alerts/check")
def alerts_check():
    """Called every 10-15 minutes by an external scheduler."""
    if not _alert_key_ok():
        return jsonify({"error": "wrong key"}), 403
    try:
        return jsonify({"results": alerts.check_alerts(dashboard_url=request.host_url)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
