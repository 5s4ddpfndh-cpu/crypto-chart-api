import requests

BINANCE_BASE = "https://data-api.binance.vision/api/v3/klines"
PAGE_SIZE = 1000
MAX_CANDLES = 6000


def fetch_candles(symbol="BTCUSDT", interval="1h", limit=500):
    """Latest `limit` candles, oldest first. Binance returns at most 1000 per
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
