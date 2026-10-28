import requests

BINANCE_BASE = "https://data-api.binance.vision/api/v3/klines"


def fetch_candles(symbol="BTCUSDT", interval="1h", limit=500):
    limit = max(1, min(int(limit), 1000))
    response = requests.get(
        BINANCE_BASE,
        params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
        timeout=10,
    )
    response.raise_for_status()
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
        for row in response.json()
    ]
