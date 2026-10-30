"""Walk-forward backtest of the strategies. Results are in R (multiples of the
initial risk) so they are independent of account size, and include trading
fees.

Position management mirrors the exit rules: 50% at TP1 (stop moves to entry),
30% at TP2, 20% at TP3. Within a bar the stop is checked before targets
(pessimistic)."""

from .strategies import STRATEGIES, build_context

ORDER_EXPIRY_BARS = 10
PORTIONS = (0.5, 0.3, 0.2)
DEFAULT_FEE_PCT = 0.1  # round trip, e.g. 0.05% taker fee on entry and on exit


def backtest(candles, strategy="confluence", min_rr=1.5, fee_pct=DEFAULT_FEE_PCT, warmup=210, market=None):
    fn = STRATEGIES[strategy]["fn"]
    x = build_context(candles, market)
    trades = []
    i = warmup
    # The last candle is still forming, so signals come only from closed bars.
    while i < len(candles) - 2:
        plan = fn(x, i, min_rr=min_rr)
        if not plan:
            i += 1
            continue
        trade, exit_index = _simulate(candles, i + 1, plan, fee_pct)
        if trade:
            trade["signalTime"] = candles[i].get("openTime")
            trades.append(trade)
            i = exit_index + 1
        else:
            i += 1
    return {"strategy": strategy, "trades": trades, "stats": _stats(trades)}


def compare(candles, min_rr=1.5, fee_pct=DEFAULT_FEE_PCT, market=None):
    """Backtest every strategy on the same candles, best first."""
    results = []
    for key, meta in STRATEGIES.items():
        stats = backtest(candles, key, min_rr=min_rr, fee_pct=fee_pct, market=market)["stats"]
        results.append({"strategy": key, "name": meta["name"],
                        "description": meta["description"], "stats": stats})
    for r in results:
        r["verdict"] = verdict(r["stats"])
    order = {"strong": 3, "weak": 2, "few_trades": 1, "losing": 0}
    results.sort(key=lambda r: (order[r["verdict"]], r["stats"].get("avgR", -1e9)), reverse=True)
    return results


MIN_TRADES = 30


def verdict(stats):
    """strong: enough trades, profitable in both halves, profit factor >= 1.3.
    Ranking uses expectancy (average R per trade), not win rate: a high win
    rate with small wins and large losses still loses money."""
    trades = stats.get("trades", 0)
    if trades < MIN_TRADES:
        return "few_trades"
    if stats["totalR"] <= 0:
        return "losing"
    pf = stats["profitFactor"]
    if stats.get("consistent") and (pf is None or pf >= 1.3):
        return "strong"
    return "weak"


def _simulate(candles, start, plan, fee_pct):
    direction = 1 if plan["side"] == "long" else -1
    stop = plan["stopLoss"]
    targets = [t["price"] for t in plan["targets"]]

    if plan.get("market"):
        fill_index = start
        entry = candles[start]["open"]
        # Skip if the next open already gapped through the stop or TP1.
        if (entry - stop) * direction <= 0 or (targets[0] - entry) * direction <= 0:
            return None, start
    else:
        entry = plan["entry"]
        fill_index = None
        for j in range(start, min(start + ORDER_EXPIRY_BARS, len(candles))):
            c = candles[j]
            if (direction == 1 and c["low"] <= entry) or (direction == -1 and c["high"] >= entry):
                fill_index = j
                break
        if fill_index is None:
            return None, start

    risk = abs(entry - stop)
    if risk <= 0:
        return None, start
    fee_r = fee_pct / 100 * entry / risk

    realized, hit = -fee_r, 0
    for j in range(fill_index, len(candles)):
        c = candles[j]
        adverse = c["low"] if direction == 1 else c["high"]
        favorable = c["high"] if direction == 1 else c["low"]
        if (adverse - stop) * direction <= 0:
            remaining = sum(PORTIONS[hit:])
            realized += remaining * (stop - entry) * direction / risk
            return _trade(plan, entry, fill_index, j, realized, hit, candles), j
        while hit < len(targets) and (favorable - targets[hit]) * direction >= 0:
            realized += PORTIONS[hit] * abs(targets[hit] - entry) / risk
            hit += 1
            stop = entry if hit == 1 else targets[hit - 2]
        if hit == len(targets):
            return _trade(plan, entry, fill_index, j, realized, hit, candles), j

    last = candles[-1]["close"]
    realized += sum(PORTIONS[hit:]) * (last - entry) * direction / risk
    return _trade(plan, entry, fill_index, len(candles) - 1, realized, hit, candles, open_=True), len(candles) - 1


def _trade(plan, entry, fill_index, exit_index, realized, hit, candles, open_=False):
    return {
        "side": plan["side"],
        "component": plan.get("component"),
        "entry": entry,
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
    stats = _summary([t["resultR"] for t in closed])
    # Same strategy on the older and the newer half: a real edge should hold in both.
    half = len(closed) // 2
    if half >= 5:
        first, second = _summary([t["resultR"] for t in closed[:half]]), _summary([t["resultR"] for t in closed[half:]])
        stats["firstHalfR"], stats["secondHalfR"] = first["totalR"], second["totalR"]
        stats["consistent"] = first["totalR"] > 0 and second["totalR"] > 0
    return stats


def _summary(results):
    wins = [r for r in results if r > 0]
    losses = [r for r in results if r < 0]
    equity = peak = max_dd = 0.0
    for r in results:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": len(results),
        "winRate": round(len(wins) / len(results) * 100, 1),
        "totalR": round(sum(results), 2),
        "avgR": round(sum(results) / len(results), 3),
        "profitFactor": round(sum(wins) / -sum(losses), 2) if losses else None,
        "maxDrawdownR": round(max_dd, 2),
    }
