"""Candle providers: Binance for crypto, Yahoo Finance for gold and indices.
All return candles oldest first; the last candle may still be forming."""

import time

import requests

from .markets import get_market

BINANCE_BASE = "https://data-api.binance.vision/api/v3/klines"
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
PAGE_SIZE = 1000
MAX_CANDLES = 6000
CACHE_SECONDS = 60

# Yahoo limits how far back intraday data goes, so each interval asks for the
# longest range Yahoo allows. 4h is not offered and is built from 1h.
YAHOO_RANGES = {"15m": ("15m", "60d"), "1h": ("60m", "730d"), "4h": ("60m", "730d"), "1d": ("1d", "10y")}

_cache = {}


def fetch_market(market, interval="1h", limit=500):
    info = get_market(market)
    limit = max(1, min(int(limit), MAX_CANDLES))
    key = (info["provider"], info["symbol"], interval)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS and len(hit[1]) >= limit:
        return hit[1][-limit:]
    if info["provider"] == "binance":
        candles = fetch_candles(info["symbol"], interval, limit)
    else:
        candles = fetch_yahoo(info["symbol"], interval)
    _cache[key] = (time.time(), candles)
    return candles[-limit:]


def fetch_candles(symbol="BTCUSDT", interval="1h", limit=500):
    """Latest `limit` Binance candles. Binance returns at most 1000 per
    request, so larger requests page backwards with `endTime`."""
    limit = max(1, min(int(limit), MAX_CANDLES))
    rows, end_time = [], None
    while len(rows) < limit:
        params = {"symbol": symbol.upper(), "interval": interval,
                  "limit": min(PAGE_SIZE, limit - len(rows))}
        if end_time is not None:
            params["endTime"] = end_time
        response = requests.get(BINANCE_BASE, params=params, timeout=10)
        response.raise_for_status()
        page = response.json()
        if not page:
            break
        rows = page + rows
        end_time = page[0][0] - 1
        if len(page) < params["limit"]:
            break
    return [
        {
            "openTime": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "closeTime": row[6],
        }
        for row in rows
    ]


def fetch_yahoo(symbol, interval="1h"):
    if interval not in YAHOO_RANGES:
        raise ValueError(f"interval must be one of {list(YAHOO_RANGES)}")
    yahoo_interval, yahoo_range = YAHOO_RANGES[interval]
    response = requests.get(
        YAHOO_BASE + symbol,
        params={"interval": yahoo_interval, "range": yahoo_range},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    response.raise_for_status()
    chart = response.json()["chart"]
    if chart.get("error"):
        raise ValueError(f"Yahoo: {chart['error']}")
    result = chart["result"][0]
    quote = result["indicators"]["quote"][0]
    candles = []
    for i, t in enumerate(result.get("timestamp") or []):
        o, h, l, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
        if None in (o, h, l, c):
            continue
        candles.append({
            "openTime": t * 1000,
            "open": o, "high": h, "low": l, "close": c,
            "volume": quote["volume"][i] or 0,
            "closeTime": None,
        })
    return resample_4h(candles) if interval == "4h" else candles


def resample_4h(candles):
    """Group 1h candles into 4h candles aligned to UTC 00/04/08/12/16/20."""
    bucket_ms = 4 * 3600 * 1000
    out = []
    for c in candles:
        start = c["openTime"] - c["openTime"] % bucket_ms
        if out and out[-1]["openTime"] == start:
            bar = out[-1]
            bar["high"] = max(bar["high"], c["high"])
            bar["low"] = min(bar["low"], c["low"])
            bar["close"] = c["close"]
            bar["volume"] += c["volume"]
        else:
            out.append({**c, "openTime": start})
    return out
