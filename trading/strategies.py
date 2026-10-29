"""A set of entry strategies that share one backtester, so they can be compared
on the same candles. Every strategy is a function `(ctx, i) -> plan | None`
that may only look at data up to and including bar `i` (no look-ahead)."""

from .indicators import atr, ema, macd, rsi, sma
from .strategy import analyze, _r

TARGET_MULTIPLES = (1.5, 2.5, 4.0)
CONFLUENCE_WINDOW = 300


def build_context(candles):
    o = [c["open"] for c in candles]
    h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]
    c = [x["close"] for x in candles]
    v = [x["volume"] for x in candles]
    line, signal, hist = macd(c)
    return {
        "candles": candles, "o": o, "h": h, "l": l, "c": c, "v": v,
        "ema20": ema(c, 20), "ema50": ema(c, 50), "ema200": ema(c, 200),
        "rsi": rsi(c), "macd": line, "macdSignal": signal, "hist": hist,
        "atr": atr(h, l, c), "volAvg": sma(v, 20),
    }


def market_plan(side, entry, stop, multiples=TARGET_MULTIPLES):
    """A plan entered at market on the next bar's open."""
    direction = 1 if side == "long" else -1
    risk = (entry - stop) * direction
    targets = [entry + direction * m * risk for m in multiples]
    return {
        "side": side,
        "source": "market",
        "status": "in_zone",
        "market": True,
        "entryZone": {"low": _r(entry), "high": _r(entry)},
        "entry": _r(entry),
        "stopLoss": _r(stop),
        "riskPerUnit": _r(risk),
        "riskPct": round(risk / entry * 100, 2),
        "targets": [{"price": _r(t), "rr": m} for t, m in zip(targets, multiples)],
    }


def _bounded_stop(side, entry, raw_stop, a, low=0.5, high=3.0):
    """Clamp the stop distance to [low, high] ATR; None if wider than `high`."""
    direction = 1 if side == "long" else -1
    dist = (entry - raw_stop) * direction
    if dist > high * a:
        return None
    return entry - direction * max(dist, low * a)


def _ready(x, i, lookback=25):
    return i >= lookback and x["ema200"][i] is not None and x["atr"][i]


def confluence(x, i, min_rr=1.5):
    window = x["candles"][max(0, i - CONFLUENCE_WINDOW + 1):i + 1]
    return analyze(window, min_rr=min_rr)["plan"]


def ema_pullback(x, i, **_):
    """Trend pullback: in a trend, price dips into EMA20 and closes back
    beyond it with a candle in the trend direction."""
    if not _ready(x, i):
        return None
    c, o, h, l, a = x["c"][i], x["o"][i], x["h"][i], x["l"][i], x["atr"][i]
    e20, e50, e200, r = x["ema20"][i], x["ema50"][i], x["ema200"][i], x["rsi"][i]
    if c > e200 and e50 > e200 and l <= e20 < c and c > o and r > 50:
        stop = _bounded_stop("long", c, min(x["l"][i - 4:i + 1]) - 0.2 * a, a)
        return stop and market_plan("long", c, stop)
    if c < e200 and e50 < e200 and h >= e20 > c and c < o and r < 50:
        stop = _bounded_stop("short", c, max(x["h"][i - 4:i + 1]) + 0.2 * a, a)
        return stop and market_plan("short", c, stop)
    return None


def breakout(x, i, **_):
    """Fresh close beyond the 20-bar range, with the trend and above-average volume."""
    if not _ready(x, i):
        return None
    c, a = x["c"][i], x["atr"][i]
    e50, e200 = x["ema50"][i], x["ema200"][i]
    vol_ok = x["volAvg"][i] and x["v"][i] > 1.5 * x["volAvg"][i]
    prev_high, prev_low = max(x["h"][i - 20:i]), min(x["l"][i - 20:i])
    was_inside = min(x["l"][i - 21:i - 1]) <= x["c"][i - 1] <= max(x["h"][i - 21:i - 1])
    if not (vol_ok and was_inside):
        return None
    if c > prev_high and e50 > e200:
        return market_plan("long", c, c - 1.5 * a)
    if c < prev_low and e50 < e200:
        return market_plan("short", c, c + 1.5 * a)
    return None


def rsi_reversion(x, i, **_):
    """With the main trend, buy RSI recovering from oversold (sell from overbought)."""
    if not _ready(x, i) or x["rsi"][i - 1] is None:
        return None
    c, a, e200 = x["c"][i], x["atr"][i], x["ema200"][i]
    prev, now = x["rsi"][i - 1], x["rsi"][i]
    if c > e200 and prev < 30 <= now:
        stop = _bounded_stop("long", c, min(x["l"][i - 10:i + 1]) - 0.2 * a, a)
        return stop and market_plan("long", c, stop, (1.0, 2.0, 3.0))
    if c < e200 and prev > 70 >= now:
        stop = _bounded_stop("short", c, max(x["h"][i - 10:i + 1]) + 0.2 * a, a)
        return stop and market_plan("short", c, stop, (1.0, 2.0, 3.0))
    return None


def macd_trend(x, i, **_):
    """MACD crosses its signal line below zero in an uptrend (above zero in a downtrend)."""
    if not _ready(x, i) or x["macdSignal"][i - 1] is None:
        return None
    c, a, e200 = x["c"][i], x["atr"][i], x["ema200"][i]
    m0, s0, m1, s1 = x["macd"][i - 1], x["macdSignal"][i - 1], x["macd"][i], x["macdSignal"][i]
    if c > e200 and m0 <= s0 and m1 > s1 and m1 < 0:
        return market_plan("long", c, c - 1.5 * a)
    if c < e200 and m0 >= s0 and m1 < s1 and m1 > 0:
        return market_plan("short", c, c + 1.5 * a)
    return None


STRATEGIES = {
    "confluence": {
        "fn": confluence,
        "name": "الدعم والمقاومة (الأصلية)",
        "description": "أمر حد عند أقوى منطقة دعم/مقاومة قريبة مع توافق عدة مؤشرات",
    },
    "ema_pullback": {
        "fn": ema_pullback,
        "name": "الارتداد من EMA20",
        "description": "في اتجاه واضح، ادخل عند ارتداد السعر من EMA20 بشمعة في اتجاه الترند",
    },
    "breakout": {
        "fn": breakout,
        "name": "الاختراق مع الحجم",
        "description": "إغلاق فوق أعلى قمة لآخر 20 شمعة (أو تحت أدنى قاع) مع حجم تداول مرتفع",
    },
    "rsi_reversion": {
        "fn": rsi_reversion,
        "name": "ارتداد RSI مع الترند",
        "description": "في ترند صاعد، شراء عند خروج RSI من منطقة التشبع البيعي (والعكس)",
    },
    "macd_trend": {
        "fn": macd_trend,
        "name": "تقاطع MACD مع الترند",
        "description": "تقاطع MACD لخط الإشارة تحت الصفر في ترند صاعد (والعكس)",
    },
}


def live_signal(candles, strategy, lookback=3):
    """Latest setup from the last `lookback` closed bars (the final candle is
    still forming), kept only while price has hit neither the stop nor TP1."""
    x = build_context(candles)
    fn = STRATEGIES[strategy]["fn"]
    last = len(candles) - 1
    for i in range(last - 1, last - 1 - lookback, -1):
        plan = fn(x, i)
        if not plan:
            continue
        direction = 1 if plan["side"] == "long" else -1
        tp1 = plan["targets"][0]["price"]
        for j in range(i + 1, last + 1):
            if (x["l"][j] if direction == 1 else x["h"][j]) * direction <= plan["stopLoss"] * direction:
                return None
            if (x["h"][j] if direction == 1 else x["l"][j]) * direction >= tp1 * direction:
                return None
        plan["barsAgo"] = last - i
        return plan
    return None
