"""A set of entry strategies that share one backtester, so they can be compared
on the same candles. Every strategy is a function `(ctx, i) -> plan | None`
that may only look at data up to and including bar `i` (no look-ahead)."""

from datetime import datetime, timezone
from statistics import median
from zoneinfo import ZoneInfo

from .indicators import adx, atr, bollinger, ema, macd, rsi, sma, supertrend
from .strategy import analyze, _r

TARGET_MULTIPLES = (1.5, 2.5, 4.0)
CONFLUENCE_WINDOW = 300


def build_context(candles, market=None):
    o = [c["open"] for c in candles]
    h = [c["high"] for c in candles]
    l = [c["low"] for c in candles]
    c = [x["close"] for x in candles]
    v = [x["volume"] for x in candles]
    line, signal, hist = macd(c)
    st_line, st_dir = supertrend(h, l, c)
    bb_upper, bb_mid, bb_lower = bollinger(c)
    gaps = [b["openTime"] - a["openTime"] for a, b in zip(candles[-50:], candles[-49:])]
    return {
        "market": market,
        "barMinutes": median(gaps) / 60000 if gaps else None,
        "_cache": {},
        "candles": candles, "o": o, "h": h, "l": l, "c": c, "v": v,
        "ema20": ema(c, 20), "ema50": ema(c, 50), "ema200": ema(c, 200),
        "rsi": rsi(c), "macd": line, "macdSignal": signal, "hist": hist,
        "atr": atr(h, l, c), "volAvg": sma(v, 20), "adx": adx(h, l, c),
        "stLine": st_line, "stDir": st_dir,
        "bbUpper": bb_upper, "bbMid": bb_mid, "bbLower": bb_lower,
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


def supertrend_trend(x, i, **_):
    """Supertrend flips in the direction of the EMA200 trend, with ADX showing a real trend."""
    if not _ready(x, i) or x["stDir"][i - 1] is None or x["adx"][i] is None:
        return None
    c, a, e200 = x["c"][i], x["atr"][i], x["ema200"][i]
    flipped_up = x["stDir"][i - 1] == -1 and x["stDir"][i] == 1
    flipped_down = x["stDir"][i - 1] == 1 and x["stDir"][i] == -1
    if x["adx"][i] < 20:
        return None
    if flipped_up and c > e200:
        stop = _bounded_stop("long", c, x["stLine"][i], a)
        return stop and market_plan("long", c, stop)
    if flipped_down and c < e200:
        stop = _bounded_stop("short", c, x["stLine"][i], a)
        return stop and market_plan("short", c, stop)
    return None


def bb_reversion(x, i, **_):
    """In a range (ADX < 20), fade a close back inside the Bollinger Bands."""
    if not _ready(x, i) or x["bbLower"][i - 1] is None or x["adx"][i] is None:
        return None
    if x["adx"][i] >= 20:
        return None
    c, a = x["c"][i], x["atr"][i]
    if x["c"][i - 1] < x["bbLower"][i - 1] and c > x["bbLower"][i]:
        stop = _bounded_stop("long", c, min(x["l"][i - 3:i + 1]) - 0.3 * a, a)
        return stop and market_plan("long", c, stop, (1.0, 2.0, 3.0))
    if x["c"][i - 1] > x["bbUpper"][i - 1] and c < x["bbUpper"][i]:
        stop = _bounded_stop("short", c, max(x["h"][i - 3:i + 1]) + 0.3 * a, a)
        return stop and market_plan("short", c, stop, (1.0, 2.0, 3.0))
    return None


def _minutes(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _local(x, tz):
    """(local date, minute of day) of every bar's open, cached per time zone."""
    key = ("local", tz)
    if key not in x["_cache"]:
        zone = ZoneInfo(tz)
        local = []
        for candle in x["candles"]:
            t = datetime.fromtimestamp(candle["openTime"] / 1000, timezone.utc).astimezone(zone)
            local.append((t.date(), t.hour * 60 + t.minute))
        x["_cache"][key] = local
    return x["_cache"][key]


def _htf_trend(x, hours=4):
    """Trend of the higher timeframe built from these candles: 1 up, -1 down,
    0 unclear. Bar i only sees higher-timeframe candles that closed by its own close."""
    key = ("htf", hours)
    if key not in x["_cache"]:
        bucket = hours * 3600 * 1000
        starts, closes = [], []
        for candle in x["candles"]:
            start = candle["openTime"] - candle["openTime"] % bucket
            if starts and starts[-1] == start:
                closes[-1] = candle["close"]
            else:
                starts.append(start)
                closes.append(candle["close"])
        e20, e50 = ema(closes, 20), ema(closes, 50)
        trend, k = [], -1
        bar_ms = (x["barMinutes"] or 0) * 60000
        for candle in x["candles"]:
            while k + 1 < len(starts) and starts[k + 1] + bucket <= candle["openTime"] + bar_ms:
                k += 1
            if k < 0 or e50[k] is None:
                trend.append(0)
            elif e20[k] > e50[k] and closes[k] > e20[k]:
                trend.append(1)
            elif e20[k] < e50[k] and closes[k] < e20[k]:
                trend.append(-1)
            else:
                trend.append(0)
        x["_cache"][key] = trend
    return x["_cache"][key]


def mtf_pullback(x, i, **_):
    """Intraday pullback to EMA20 only in the direction of the 4h trend, and
    only during London and New York hours (07:00-20:00 UTC)."""
    bar = x["barMinutes"]
    if not bar or bar > 60 or not _ready(x, i):
        return None
    minute = _local(x, "UTC")[i][1]
    if not 7 * 60 <= minute < 20 * 60:
        return None
    trend = _htf_trend(x)[i]
    c, o, h, l, a = x["c"][i], x["o"][i], x["h"][i], x["l"][i], x["atr"][i]
    e20, r = x["ema20"][i], x["rsi"][i]
    if trend == 1 and l <= e20 < c and c > o and 40 <= r <= 70:
        stop = _bounded_stop("long", c, min(x["l"][i - 5:i + 1]) - 0.2 * a, a)
        return stop and market_plan("long", c, stop)
    if trend == -1 and h >= e20 > c and c < o and 30 <= r <= 60:
        stop = _bounded_stop("short", c, max(x["h"][i - 5:i + 1]) + 0.2 * a, a)
        return stop and market_plan("short", c, stop)
    return None


def _range_breakout(x, i, cfg):
    """First close outside a session range during its trading window. Stop at
    the middle of the range (or 1.5 ATR when the range is too wide)."""
    bar = x["barMinutes"]
    if not cfg or not bar or bar > 30 or not x["atr"][i]:
        return None
    local = _local(x, cfg["tz"])
    day, minute = local[i]
    start, end, cutoff = _minutes(cfg["start"]), _minutes(cfg["end"]), _minutes(cfg["cutoff"])
    if not (minute >= end and minute + bar <= cutoff):
        return None
    in_range, earlier = [], []
    j = i - 1
    while j >= 0 and local[j][0] == day and local[j][1] >= start:
        (in_range if local[j][1] < end else earlier).append(j)
        j -= 1
    if len(in_range) < 0.8 * (end - start) / bar:
        return None  # session missing from the data (holiday, gap)
    hi = max(x["h"][k] for k in in_range)
    lo = min(x["l"][k] for k in in_range)
    if any(not lo <= x["c"][k] <= hi for k in earlier):
        return None  # only the first breakout of the day counts
    c, a = x["c"][i], x["atr"][i]
    mid = (hi + lo) / 2
    if c > hi:
        stop = _bounded_stop("long", c, mid, a) or c - 1.5 * a
        return market_plan("long", c, stop, (1.0, 2.0, 3.0))
    if c < lo:
        stop = _bounded_stop("short", c, mid, a) or c + 1.5 * a
        return market_plan("short", c, stop, (1.0, 2.0, 3.0))
    return None


def _session_config(x, name):
    from .markets import MARKETS
    return MARKETS.get(x["market"] or "nasdaq", {}).get(name)


def orb(x, i, **_):
    """Opening range breakout: the first 30 minutes of the market's main session."""
    return _range_breakout(x, i, _session_config(x, "orb"))


def session_breakout(x, i, **_):
    """Breakout of the quiet session before the main one (Asian range for gold,
    pre-market for Nasdaq)."""
    return _range_breakout(x, i, _session_config(x, "session_range"))


def combined(x, i, **kwargs):
    """The market's best strategies together: the first one with a setup on
    this bar wins. More trades than any single strategy on its own."""
    from .markets import get_market
    combo = get_market(x["market"])["combo"] if x["market"] else ["breakout", "ema_pullback", "macd_trend"]
    for key in combo:
        plan = STRATEGIES[key]["fn"](x, i, **kwargs)
        if plan:
            return {**plan, "component": key, "componentName": STRATEGIES[key]["name"]}
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
    "supertrend": {
        "fn": supertrend_trend,
        "name": "Supertrend مع الترند",
        "description": "انقلاب مؤشر Supertrend في اتجاه EMA200 بشرط ترند قوي (ADX ≥ 20)",
    },
    "bb_reversion": {
        "fn": bb_reversion,
        "name": "الارتداد داخل بولينجر",
        "description": "في سوق عرضي (ADX < 20)، الدخول عند عودة السعر داخل نطاق بولينجر",
    },
    "mtf_pullback": {
        "fn": mtf_pullback,
        "name": "ارتداد 15m مع ترند 4h",
        "description": "ارتداد إلى EMA20 على الفريم الصغير في اتجاه ترند 4 ساعات فقط، وخلال جلستي لندن ونيويورك",
    },
    "orb": {
        "fn": orb,
        "name": "اختراق نطاق الافتتاح",
        "description": "أول إغلاق خارج نطاق أول 30 دقيقة من الجلسة الرئيسية (فريم 30 دقيقة أو أقل)",
    },
    "session_breakout": {
        "fn": session_breakout,
        "name": "اختراق نطاق الجلسة",
        "description": "أول إغلاق خارج نطاق الجلسة الهادئة (آسيا للذهب، ما قبل الافتتاح لناسداك)",
    },
    "combined": {
        "fn": combined,
        "name": "المدمجة (أفضل استراتيجيات السوق)",
        "description": "تجمع الاستراتيجيات الرابحة لكل سوق: أول استراتيجية تعطي إشارة يتم أخذها",
    },
}


def live_signal(candles, strategy, lookback=3, market=None):
    """Latest setup from the last `lookback` closed bars (the final candle is
    still forming), kept only while price has hit neither the stop nor TP1."""
    x = build_context(candles, market)
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


def new_signal(candles, strategy, market=None):
    """A setup on the most recently closed bar that was not already there on
    the bar before. Used for alerts so the same setup is announced once."""
    x = build_context(candles, market)
    fn = STRATEGIES[strategy]["fn"]
    i = len(candles) - 2
    plan = fn(x, i)
    if not plan:
        return None
    previous = fn(x, i - 1)
    if previous and previous["side"] == plan["side"]:
        return None
    plan["signalTime"] = candles[i]["openTime"]
    return plan
