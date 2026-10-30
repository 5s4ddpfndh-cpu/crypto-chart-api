"""Technical indicators in pure Python. Each returns a list aligned with the input,
with None where there is not enough history yet."""


def sma(values, period):
    out = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= period:
            total -= values[i - period]
        if i >= period - 1:
            out[i] = total / period
    return out


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    value = sum(values[:period]) / period
    out[period - 1] = value
    for i in range(period, len(values)):
        value = values[i] * k + value * (1 - k)
        out[i] = value
    return out


def rsi(closes, period=14):
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0)
        losses += max(-change, 0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def true_range(highs, lows, closes):
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return tr


def atr(highs, lows, closes, period=14):
    tr = true_range(highs, lows, closes)
    out = [None] * len(tr)
    if len(tr) < period:
        return out
    value = sum(tr[:period]) / period
    out[period - 1] = value
    for i in range(period, len(tr)):
        value = (value * (period - 1) + tr[i]) / period
        out[i] = value
    return out


def macd(closes, fast=12, slow=26, signal=9):
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_ema, slow_ema)
    ]
    start = next((i for i, v in enumerate(line) if v is not None), len(line))
    signal_part = ema(line[start:], signal)
    signal_line = [None] * start + signal_part
    hist = [
        m - s if m is not None and s is not None else None
        for m, s in zip(line, signal_line)
    ]
    return line, signal_line, hist


def bollinger(closes, period=20, mult=2.0):
    mid = sma(closes, period)
    upper, lower = [None] * len(closes), [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        mean = mid[i]
        std = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
        upper[i], lower[i] = mean + mult * std, mean - mult * std
    return upper, mid, lower


def pivots(highs, lows, left=3, right=3):
    """Confirmed swing points: a high/low that is the extreme of `left` bars
    before and `right` bars after it."""
    found = []
    for i in range(left, len(highs) - right):
        window_h = highs[i - left:i + right + 1]
        window_l = lows[i - left:i + right + 1]
        if highs[i] == max(window_h) and window_h.count(highs[i]) == 1:
            found.append({"index": i, "price": highs[i], "type": "high"})
        if lows[i] == min(window_l) and window_l.count(lows[i]) == 1:
            found.append({"index": i, "price": lows[i], "type": "low"})
    return found


def adx(highs, lows, closes, period=14):
    """Wilder's Average Directional Index: trend strength regardless of direction."""
    n = len(closes)
    out = [None] * n
    if n <= 2 * period:
        return out
    tr = true_range(highs, lows, closes)
    plus_dm, minus_dm = [0.0], [0.0]
    for i in range(1, n):
        up, down = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    tr_s = sum(tr[1:period + 1])
    p_s, m_s = sum(plus_dm[1:period + 1]), sum(minus_dm[1:period + 1])
    dx = []
    for i in range(period, n):
        if i > period:
            tr_s = tr_s - tr_s / period + tr[i]
            p_s = p_s - p_s / period + plus_dm[i]
            m_s = m_s - m_s / period + minus_dm[i]
        p_di = 100 * p_s / tr_s if tr_s else 0
        m_di = 100 * m_s / tr_s if tr_s else 0
        dx.append(100 * abs(p_di - m_di) / (p_di + m_di) if p_di + m_di else 0)
        if len(dx) == period:
            value = sum(dx) / period
            out[i] = value
        elif len(dx) > period:
            value = (value * (period - 1) + dx[-1]) / period
            out[i] = value
    return out


def supertrend(highs, lows, closes, period=10, mult=3.0):
    """Returns (line, direction) where direction is 1 for uptrend, -1 for downtrend."""
    n = len(closes)
    line, direction = [None] * n, [None] * n
    atr_values = atr(highs, lows, closes, period)
    upper = lower = None
    for i in range(n):
        a = atr_values[i]
        if a is None:
            continue
        mid = (highs[i] + lows[i]) / 2
        basic_upper, basic_lower = mid + mult * a, mid - mult * a
        if upper is None:
            upper, lower, d = basic_upper, basic_lower, 1
        else:
            prev_upper, prev_lower, prev = upper, lower, direction[i - 1]
            upper = basic_upper if basic_upper < prev_upper or closes[i - 1] > prev_upper else prev_upper
            lower = basic_lower if basic_lower > prev_lower or closes[i - 1] < prev_lower else prev_lower
            if prev == -1 and closes[i] > prev_upper:
                d = 1
            elif prev == 1 and closes[i] < prev_lower:
                d = -1
            else:
                d = prev
        direction[i] = d
        line[i] = lower if d == 1 else upper
    return line, direction
