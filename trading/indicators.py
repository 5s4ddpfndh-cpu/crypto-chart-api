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
