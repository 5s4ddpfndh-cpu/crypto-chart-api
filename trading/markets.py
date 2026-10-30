"""Tradable markets and where their data comes from.

`fee_pct` is the estimated round-trip cost (commission + spread) used by the
backtest, as a percent of price."""

MARKETS = {
    "gold": {
        "name": "الذهب",
        "provider": "yahoo",
        "symbol": "GC=F",
        "fee_pct": 0.03,
        # Strategies that were profitable on gold 4h in the research run.
        "combo": ["breakout", "ema_pullback", "macd_trend"],
        "exness": "XAUUSD",
        "note": "أسعار عقود الذهب الآجلة (GC=F) متأخرة ~10 دقائق وتختلف قليلاً عن سعر XAUUSD في منصتك",
    },
    "btc": {
        "name": "بيتكوين",
        "provider": "binance",
        "symbol": "BTCUSDT",
        "fee_pct": 0.1,
        "combo": ["breakout", "macd_trend"],
        "exness": "BTCUSD",
        "note": "أسعار Binance مباشرة",
    },
    "nasdaq": {
        "name": "ناسداك 100",
        "provider": "yahoo",
        "symbol": "NQ=F",
        "fee_pct": 0.02,
        "combo": ["confluence", "breakout", "ema_pullback", "macd_trend"],
        "exness": "USTEC",
        "note": "أسعار عقود ناسداك الآجلة (NQ=F) متأخرة ~10 دقائق وتختلف قليلاً عن سعر NAS100 في منصتك",
    },
}

TIMEFRAMES = ("15m", "1h", "4h", "1d")


def get_market(key):
    if key not in MARKETS:
        raise ValueError(f"unknown market '{key}', choose one of {list(MARKETS)}")
    return MARKETS[key]
