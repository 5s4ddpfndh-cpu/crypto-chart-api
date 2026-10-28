"""Walk-forward backtest of the strategy. Results are in R (multiples of the
initial risk) so they are independent of account size.

Position management mirrors the exit rules: 50% at TP1 (stop moves to entry),
30% at TP2, 20% at TP3. Within a bar the stop is checked before targets
(pessimistic)."""

from .strategy import analyze

WINDOW = 300
ORDER_EXPIRY_BARS = 10
PORTIONS = (0.5, 0.3, 0.2)


def backtest(candles, min_rr=1.5, warmup=210):
    trades = []
    i = warmup
    while i < len(candles) - 1:
        result = analyze(candles[max(0, i - WINDOW + 1):i + 1], min_rr=min_rr)
        plan = result["plan"]
        if not plan:
            i += 1
            continue
        trade, exit_index = _simulate(candles, i + 1, plan)
        if trade:
            trade["signalTime"] = candles[i].get("openTime")
            trades.append(trade)
            i = exit_index + 1
        else:
            i += 1
    return {"trades": trades, "stats": _stats(trades)}


def _simulate(candles, start, plan):
    direction = 1 if plan["side"] == "long" else -1
    entry, stop = plan["entry"], plan["stopLoss"]
    risk = abs(entry - stop)
    targets = [t["price"] for t in plan["targets"]]

    fill_index = None
    for j in range(start, min(start + ORDER_EXPIRY_BARS, len(candles))):
        c = candles[j]
        if (direction == 1 and c["low"] <= entry) or (direction == -1 and c["high"] >= entry):
            fill_index = j
            break
    if fill_index is None or risk <= 0:
        return None, start

    realized, hit = 0.0, 0
    for j in range(fill_index, len(candles)):
        c = candles[j]
        adverse = c["low"] if direction == 1 else c["high"]
        favorable = c["high"] if direction == 1 else c["low"]
        if (adverse - stop) * direction <= 0:
            remaining = sum(PORTIONS[hit:])
            realized += remaining * (stop - entry) * direction / risk
            return _trade(plan, fill_index, j, realized, hit, candles), j
        while hit < len(targets) and (favorable - targets[hit]) * direction >= 0:
            realized += PORTIONS[hit] * abs(targets[hit] - entry) / risk
            hit += 1
            stop = entry if hit == 1 else targets[hit - 2]
        if hit == len(targets):
            return _trade(plan, fill_index, j, realized, hit, candles), j

    last = candles[-1]["close"]
    realized += sum(PORTIONS[hit:]) * (last - entry) * direction / risk
    return _trade(plan, fill_index, len(candles) - 1, realized, hit, candles, open_=True), len(candles) - 1


def _trade(plan, fill_index, exit_index, realized, hit, candles, open_=False):
    return {
        "side": plan["side"],
        "entry": plan["entry"],
        "stopLoss": plan["stopLoss"],
        "targets": [t["price"] for t in plan["targets"]],
        "entryTime": candles[fill_index].get("openTime"),
        "exitTime": candles[exit_index].get("openTime"),
        "targetsHit": hit,
        "resultR": round(realized, 3),
        "open": open_,
    }


def _stats(trades):
    closed = [t for t in trades if not t["open"]]
    if not closed:
        return {"trades": 0}
    results = [t["resultR"] for t in closed]
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    equity = peak = max_dd = 0.0
    for r in results:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": len(closed),
        "winRate": round(len(wins) / len(closed) * 100, 1),
        "totalR": round(sum(results), 2),
        "avgR": round(sum(results) / len(closed), 3),
        "profitFactor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "maxDrawdownR": round(max_dd, 2),
    }
