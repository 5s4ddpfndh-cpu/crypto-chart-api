"""Confluence strategy: scores trend, momentum and market structure, then builds
entry zones, stop-loss and take-profit targets from support/resistance zones."""

from .indicators import atr, ema, macd, pivots, rsi
from .levels import build_zones, split_zones

MIN_CANDLES = 60
SIGNAL_THRESHOLD = 30
TARGET_MULTIPLES = (1.5, 2.5, 4.0, 5.0, 6.0)


def analyze(candles, balance=None, risk_pct=1.0, min_rr=1.5):
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"need at least {MIN_CANDLES} candles, got {len(candles)}")

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    price = closes[-1]

    ema20, ema50, ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rsi14 = rsi(closes)
    _, _, hist = macd(closes)
    atr14 = atr(highs, lows, closes)[-1]
    swings = pivots(highs, lows)
    zones = build_zones(swings, atr14, len(candles))
    supports, resistances = split_zones(zones, price)

    score, reasons = _score(closes, ema20, ema50, ema200, rsi14, hist, swings)
    if score >= SIGNAL_THRESHOLD:
        bias = "bullish"
    elif score <= -SIGNAL_THRESHOLD:
        bias = "bearish"
    else:
        bias = "neutral"

    long_plan = _long_plan(price, atr14, supports, resistances, ema20[-1], ema50[-1])
    short_plan = _short_plan(price, atr14, supports, resistances, ema20[-1], ema50[-1])
    for plan in (long_plan, short_plan):
        _add_sizing(plan, balance, risk_pct)

    signal = "WAIT"
    if bias == "bullish" and _best_rr(long_plan) >= min_rr and long_plan["status"] != "invalidated":
        signal = "BUY"
    elif bias == "bearish" and _best_rr(short_plan) >= min_rr and short_plan["status"] != "invalidated":
        signal = "SELL"

    return {
        "price": _r(price),
        "signal": signal,
        "bias": bias,
        "score": score,
        "confidence": min(abs(score), 100),
        "reasons": reasons,
        "indicators": {
            "ema20": _r(ema20[-1]),
            "ema50": _r(ema50[-1]),
            "ema200": _r(ema200[-1]),
            "rsi": _r(rsi14[-1]),
            "macdHist": _r(hist[-1]),
            "atr": _r(atr14),
        },
        "plan": long_plan if signal == "BUY" else short_plan if signal == "SELL" else None,
        "long": long_plan,
        "short": short_plan,
        "zones": {
            "support": [_round_zone(z) for z in supports[:5]],
            "resistance": [_round_zone(z) for z in resistances[:5]],
        },
        "exitRules": [
            "أغلق 50% من الصفقة عند الهدف الأول وانقل وقف الخسارة إلى سعر الدخول",
            "أغلق 30% عند الهدف الثاني وارفع الوقف إلى الهدف الأول",
            "اترك 20% للهدف الثالث مع وقف متحرك بمسافة 2×ATR",
            "اخرج فوراً إذا أغلقت شمعة خلف وقف الخسارة أو انعكس اتجاه الإشارة",
        ],
    }


def _score(closes, ema20, ema50, ema200, rsi14, hist, swings):
    price = closes[-1]
    score, reasons = 0, []

    def add(points, text):
        nonlocal score
        score += points
        reasons.append({"points": points, "text": text})

    if ema200[-1] is not None:
        if price > ema200[-1]:
            add(20, "السعر فوق EMA200 (اتجاه عام صاعد)")
        else:
            add(-20, "السعر تحت EMA200 (اتجاه عام هابط)")
        if ema50[-1] > ema200[-1]:
            add(15, "EMA50 فوق EMA200 (تقاطع ذهبي)")
        else:
            add(-15, "EMA50 تحت EMA200 (تقاطع الموت)")

    if price > ema50[-1]:
        add(10, "السعر فوق EMA50")
    else:
        add(-10, "السعر تحت EMA50")

    if ema20[-6] is not None:
        if ema20[-1] > ema20[-6]:
            add(10, "ميل EMA20 صاعد")
        else:
            add(-10, "ميل EMA20 هابط")

    if hist[-1] is not None and hist[-2] is not None:
        if hist[-1] > 0:
            add(10, "هيستوغرام MACD إيجابي")
        else:
            add(-10, "هيستوغرام MACD سلبي")
        if hist[-1] > hist[-2]:
            add(5, "الزخم يتزايد")
        else:
            add(-5, "الزخم يتناقص")

    r = rsi14[-1]
    if r is not None:
        if r >= 70:
            add(-5, f"RSI في تشبع شرائي ({r:.0f})")
        elif r >= 50:
            add(10, f"RSI فوق 50 ({r:.0f})")
        elif r > 30:
            add(-10, f"RSI تحت 50 ({r:.0f})")
        else:
            add(5, f"RSI في تشبع بيعي ({r:.0f})")

    swing_highs = [s["price"] for s in swings if s["type"] == "high"][-2:]
    swing_lows = [s["price"] for s in swings if s["type"] == "low"][-2:]
    if len(swing_highs) == 2 and len(swing_lows) == 2:
        if swing_highs[1] > swing_highs[0] and swing_lows[1] > swing_lows[0]:
            add(20, "هيكل السوق: قمم وقيعان أعلى (HH/HL)")
        elif swing_highs[1] < swing_highs[0] and swing_lows[1] < swing_lows[0]:
            add(-20, "هيكل السوق: قمم وقيعان أدنى (LH/LL)")

    return score, reasons


def _pick_zone(candidates, price, atr_value):
    # Prefer strong zones, but penalise distance so the zone is likely to be reached.
    return max(candidates, key=lambda z: z["strength"] - abs(price - z["mid"]) / atr_value * 0.5)


def _long_plan(price, atr_value, supports, resistances, ema20, ema50):
    near = [z for z in supports if price - z["high"] <= 3 * atr_value]
    if near:
        zone, source = _pick_zone(near, price, atr_value), "support"
        low, high = zone["low"], min(zone["high"], price)
    elif max(ema20, ema50) < price:
        low, high, source = min(ema20, ema50), max(ema20, ema50), "ema"
    else:
        low, high, source = price - atr_value, price - 0.3 * atr_value, "atr"
    low, high = _min_width(low, high, atr_value)

    stop = low - 0.5 * atr_value
    entry = price if low <= price <= high else (low + high) / 2
    risk = entry - stop
    levels = sorted(z["low"] for z in resistances if z["low"] >= entry + risk)
    targets = _fill_targets(levels, entry, risk, direction=1)

    if price < stop:
        status = "invalidated"
    elif low <= price <= high:
        status = "in_zone"
    else:
        status = "waiting"
    return _plan("long", source, status, low, high, entry, stop, targets, risk)


def _short_plan(price, atr_value, supports, resistances, ema20, ema50):
    near = [z for z in resistances if z["low"] - price <= 3 * atr_value]
    if near:
        zone, source = _pick_zone(near, price, atr_value), "resistance"
        low, high = max(zone["low"], price), zone["high"]
    elif min(ema20, ema50) > price:
        low, high, source = min(ema20, ema50), max(ema20, ema50), "ema"
    else:
        low, high, source = price + 0.3 * atr_value, price + atr_value, "atr"
    low, high = _min_width(low, high, atr_value)

    stop = high + 0.5 * atr_value
    entry = price if low <= price <= high else (low + high) / 2
    risk = stop - entry
    levels = sorted((z["high"] for z in supports if z["high"] <= entry - risk), reverse=True)
    targets = _fill_targets(levels, entry, risk, direction=-1)

    if price > stop:
        status = "invalidated"
    elif low <= price <= high:
        status = "in_zone"
    else:
        status = "waiting"
    return _plan("short", source, status, low, high, entry, stop, targets, risk)


def _min_width(low, high, atr_value, width=0.3):
    if high - low < width * atr_value:
        mid = (low + high) / 2
        return mid - width * atr_value / 2, mid + width * atr_value / 2
    return low, high


def _fill_targets(levels, entry, risk, direction):
    """Use S/R zones as targets first, then fall back to R-multiples, keeping
    targets at least 0.5R apart."""
    targets = []
    for level in levels:
        if not targets or abs(level - targets[-1]) >= 0.5 * risk:
            targets.append(level)
        if len(targets) == 3:
            return targets
    for multiple in TARGET_MULTIPLES:
        candidate = entry + direction * multiple * risk
        last = targets[-1] if targets else entry
        if (candidate - last) * direction >= 0.5 * risk:
            targets.append(candidate)
        if len(targets) == 3:
            return targets
    while len(targets) < 3:
        targets.append(targets[-1] + direction * risk)
    return targets


def _plan(side, source, status, low, high, entry, stop, targets, risk):
    return {
        "side": side,
        "source": source,
        "status": status,
        "entryZone": {"low": _r(low), "high": _r(high)},
        "entry": _r(entry),
        "stopLoss": _r(stop),
        "riskPerUnit": _r(risk),
        "riskPct": round(risk / entry * 100, 2),
        "targets": [
            {"price": _r(t), "rr": round(abs(t - entry) / risk, 2)} for t in targets
        ],
    }


def _add_sizing(plan, balance, risk_pct):
    if not balance or plan["riskPerUnit"] <= 0:
        return
    risk_amount = balance * risk_pct / 100
    quantity = risk_amount / plan["riskPerUnit"]
    plan["position"] = {
        "riskAmount": _r(risk_amount),
        "quantity": _r(quantity),
        "notional": _r(quantity * plan["entry"]),
        "leverageNeeded": round(quantity * plan["entry"] / balance, 2),
    }


def _best_rr(plan):
    return plan["targets"][1]["rr"] if len(plan["targets"]) > 1 else 0


def _round_zone(zone):
    return {**zone, "low": _r(zone["low"]), "high": _r(zone["high"]), "mid": _r(zone["mid"])}


def _r(value):
    if value is None:
        return None
    if abs(value) >= 1000:
        return round(value, 2)
    if abs(value) >= 1:
        return round(value, 4)
    return round(value, 8)
