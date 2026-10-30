"""Higher-timeframe setup, lower-timeframe entry.

The setup (direction, entry zone, stop, targets) comes from a strategy on the
higher timeframe (e.g. 4h), where the backtests found an edge. The entry is
timed on the lower timeframe (e.g. 15m): wait until price reaches the 4h entry
zone, then enter only when a 15m candle confirms (closes in the trade direction
beyond the previous candle). The stop goes behind the 15m swing, which is
tighter than the 4h stop, so the 4h targets are worth more R.

`hybrid_backtest` compares this with the plain higher-timeframe strategy on the
same period, so you can see whether the lower-timeframe entry actually helps."""

from .backtest import ORDER_EXPIRY_BARS, _simulate, _stats, backtest, verdict
from .indicators import atr
from .strategies import STRATEGIES, build_context
from .strategy import _r

SETUP_EXPIRY_BARS = ORDER_EXPIRY_BARS  # higher-timeframe bars a setup stays valid
STOP_BUFFER_ATR = 0.1
MIN_STOP_ATR = 0.5
MIN_TP1_R = 1.0


def _bar_ms(candles):
    gaps = sorted(b["openTime"] - a["openTime"] for a, b in zip(candles[-50:], candles[-49:]))
    return gaps[len(gaps) // 2] if gaps else 0


def _setup(x, j, strategy, min_rr):
    plan = STRATEGIES[strategy]["fn"](x, j, min_rr=min_rr)
    if not plan:
        return None
    if "entryZone" not in plan or plan["entryZone"]["low"] == plan["entryZone"]["high"]:
        # Market-entry strategies: use the band between the signal close and
        # halfway to the stop as the zone to buy (sell) the pullback into.
        e, s = plan["entry"], plan["stopLoss"]
        lo, hi = sorted((e, e + (s - e) / 2))
        plan = {**plan, "entryZone": {"low": lo, "high": hi}}
    return plan


def _find_entry(ltf, ltf_atr, k0, expires, plan):
    """Walk lower-timeframe bars from k0 until `expires` (ms). Returns
    (state, index, entry_plan): state is 'triggered', 'cancelled' (stop or
    TP1 reached first), 'expired', or 'waiting_zone' / 'waiting_trigger' when
    the data ends first (live use)."""
    d = 1 if plan["side"] == "long" else -1
    zlo, zhi = plan["entryZone"]["low"], plan["entryZone"]["high"]
    htf_stop, tp1 = plan["stopLoss"], plan["targets"][0]["price"]
    touched = None
    k = k0
    # The last candle is still forming: only closed bars can trigger.
    while k < len(ltf) - 1 and ltf[k]["openTime"] < expires:
        c = ltf[k]
        adverse, favorable = (c["low"], c["high"]) if d == 1 else (c["high"], c["low"])
        if (adverse - htf_stop) * d <= 0:
            return "cancelled", k, None
        if touched is None and (favorable - tp1) * d >= 0:
            return "cancelled", k, None
        in_zone = adverse <= zhi if d == 1 else adverse >= zlo
        if touched is None and in_zone:
            touched = k
        if touched is not None and k > touched:
            prev = ltf[k - 1]
            confirms = (c["close"] - c["open"]) * d > 0 and \
                (c["close"] - (prev["high"] if d == 1 else prev["low"])) * d > 0
            still_valid = (c["close"] - (zlo if d == 1 else zhi)) * d >= 0
            if confirms and still_valid:
                entry_plan = _entry_plan(ltf, ltf_atr, touched, k, plan)
                if entry_plan:
                    return "triggered", k, entry_plan
        k += 1
    if k < len(ltf) - 1 or (k < len(ltf) and ltf[k]["openTime"] >= expires):
        return "expired", k, None
    return ("waiting_trigger" if touched is not None else "waiting_zone"), k, None


def _entry_plan(ltf, ltf_atr, touched, k, plan):
    d = 1 if plan["side"] == "long" else -1
    entry = ltf[k]["close"]
    a = ltf_atr[k] or 0
    swing = min(c["low"] for c in ltf[touched:k + 1]) if d == 1 else max(c["high"] for c in ltf[touched:k + 1])
    stop = swing - d * STOP_BUFFER_ATR * a
    if (stop - plan["stopLoss"]) * d < 0:
        stop = plan["stopLoss"]  # never wider than the higher-timeframe stop
    if (entry - stop) * d < MIN_STOP_ATR * a:
        stop = entry - d * MIN_STOP_ATR * a
    risk = (entry - stop) * d
    if risk <= 0:
        return None
    targets = [t["price"] for t in plan["targets"]]
    if (targets[0] - entry) * d < MIN_TP1_R * risk:
        return None  # not enough room left to the first target
    return {
        "side": plan["side"],
        "source": "market",
        "status": "in_zone",
        "market": True,
        "entryZone": {"low": _r(entry), "high": _r(entry)},
        "entry": _r(entry),
        "stopLoss": _r(stop),
        "riskPerUnit": _r(risk),
        "riskPct": round(risk / entry * 100, 2),
        "targets": [{"price": _r(t), "rr": round(abs(t - entry) / risk, 2)} for t in targets],
        "htfStop": plan["stopLoss"],
        "htfZone": plan["entryZone"],
    }


def hybrid_backtest(htf, ltf, strategy="confluence", market=None, min_rr=1.5,
                    fee_pct=0.0, cost=0.0, warmup=210):
    """Trades of the hybrid entry, and of the plain higher-timeframe strategy,
    both over the period covered by the lower-timeframe candles."""
    if not htf or not ltf:
        return {"hybrid": {"trades": [], "stats": {"trades": 0}}, "baseline": {"trades": [], "stats": {"trades": 0}}}
    x = build_context(htf, market)
    htf_ms = _bar_ms(htf)
    ltf_atr = atr([c["high"] for c in ltf], [c["low"] for c in ltf], [c["close"] for c in ltf])
    start = ltf[0]["openTime"]
    trades, k = [], 0
    j = max(warmup, 1)
    while j < len(htf) - 1:
        active_from = htf[j + 1]["openTime"]  # the setup is known once bar j closed
        if active_from < start:
            j += 1
            continue
        plan = _setup(x, j, strategy, min_rr)
        if not plan:
            j += 1
            continue
        k = max(k, next((n for n in range(k, len(ltf)) if ltf[n]["openTime"] >= active_from), len(ltf)))
        state, idx, entry_plan = _find_entry(ltf, ltf_atr, k, active_from + SETUP_EXPIRY_BARS * htf_ms, plan)
        if state != "triggered":
            j += 1
            continue
        trade, exit_index = _simulate(ltf, idx + 1, entry_plan, fee_pct, cost)
        if not trade:
            j += 1
            continue
        trade["signalTime"] = htf[j]["openTime"]
        trades.append(trade)
        k = exit_index + 1
        exit_time = ltf[min(exit_index, len(ltf) - 1)]["openTime"]
        while j < len(htf) - 1 and htf[j + 1]["openTime"] <= exit_time:
            j += 1
        j += 1
    base = backtest(htf, strategy, min_rr=min_rr, fee_pct=fee_pct, market=market, cost=cost, warmup=warmup)
    base_trades = [t for t in base["trades"] if t["entryTime"] is not None and t["entryTime"] >= start]
    hybrid_stats, base_stats = _stats(trades), _stats(base_trades)
    return {
        "hybrid": {"trades": trades, "stats": hybrid_stats, "verdict": verdict(hybrid_stats)},
        "baseline": {"trades": base_trades, "stats": base_stats, "verdict": verdict(base_stats)},
    }


def hybrid_live(htf, ltf, strategy="confluence", market=None, min_rr=1.5):
    """Current state of the newest higher-timeframe setup:
    none / waiting_zone / waiting_trigger / triggered / cancelled / expired / done."""
    x = build_context(htf, market)
    htf_ms = _bar_ms(htf)
    last_closed = len(htf) - 2
    for j in range(last_closed, max(last_closed - SETUP_EXPIRY_BARS, 0), -1):
        plan = _setup(x, j, strategy, min_rr)
        if not plan:
            continue
        active_from = htf[j + 1]["openTime"]
        expires = active_from + SETUP_EXPIRY_BARS * htf_ms
        k0 = next((n for n in range(len(ltf)) if ltf[n]["openTime"] >= active_from), len(ltf))
        ltf_atr = atr([c["high"] for c in ltf], [c["low"] for c in ltf], [c["close"] for c in ltf])
        state, idx, entry_plan = _find_entry(ltf, ltf_atr, k0, expires, plan)
        result = {"state": state, "setup": plan, "setupTime": htf[j]["openTime"], "entry": None}
        if state == "triggered":
            entry_plan["signalTime"] = ltf[idx]["openTime"]
            entry_plan["barsAgo"] = len(ltf) - 1 - idx
            # Still tradable only while price has hit neither the stop nor TP1.
            d = 1 if entry_plan["side"] == "long" else -1
            for c in ltf[idx + 1:]:
                if ((c["low"] if d == 1 else c["high"]) - entry_plan["stopLoss"]) * d <= 0 or \
                        ((c["high"] if d == 1 else c["low"]) - entry_plan["targets"][0]["price"]) * d >= 0:
                    result["state"] = "done"
                    break
            result["entry"] = entry_plan
        return result
    return {"state": "none", "setup": None, "setupTime": None, "entry": None}
