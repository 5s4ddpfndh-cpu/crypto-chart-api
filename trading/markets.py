"""Tradable markets and where their data comes from.

Trading costs used by the backtest, per round trip:
- `fee_pct`: percent of price (exchange fees, e.g. Binance).
- `cost`: spread + commission + slippage in price units, as on Exness
  (dollars per ounce for gold, index points for Nasdaq). These are estimates:
  read the real spread in your MT5 (Ask - Bid) and enter it in the dashboard.
  Exness Raw Spread: spread + $7 commission per lot = $0.07 per ounce of gold."""

MARKETS = {
    "gold": {
        "name": "الذهب",
        "provider": "yahoo",
        "symbol": "GC=F",
        "fee_pct": 0.0,
        "cost": 0.30,  # $/oz round trip: ~0.15-0.25 spread (+0.07 commission on Raw) + slippage
        # Strategies that were profitable on gold 4h in the research run.
        "combo": ["breakout", "ema_pullback", "macd_trend"],
        # Intraday sessions (local time of `tz`; DST handled by zoneinfo).
        # orb: first 30 min of the COMEX day session; range: the Asian session before London.
        "orb": {"tz": "America/New_York", "start": "08:30", "end": "09:00", "cutoff": "11:30"},
        "session_range": {"tz": "Europe/London", "start": "00:00", "end": "07:00", "cutoff": "11:00"},
        "exness": "XAUUSD",
        "note": "أسعار عقود الذهب الآجلة (GC=F) متأخرة ~10 دقائق وتختلف قليلاً عن سعر XAUUSD في منصتك",
    },
    "btc": {
        "name": "بيتكوين",
        "provider": "binance",
        "symbol": "BTCUSDT",
        "fee_pct": 0.1,
        "cost": 0.0,
        "combo": ["breakout", "macd_trend"],
        "orb": {"tz": "America/New_York", "start": "09:30", "end": "10:00", "cutoff": "12:00"},
        "session_range": {"tz": "Europe/London", "start": "00:00", "end": "07:00", "cutoff": "11:00"},
        "exness": "BTCUSD",
        "note": "أسعار Binance مباشرة",
    },
    "nasdaq": {
        "name": "ناسداك 100",
        "provider": "yahoo",
        "symbol": "NQ=F",
        "fee_pct": 0.0,
        "cost": 2.0,  # index points round trip on USTEC (spread + slippage)
        "combo": ["confluence", "breakout", "ema_pullback", "macd_trend"],
        # orb: first 30 min of the cash session; range: US pre-market.
        "orb": {"tz": "America/New_York", "start": "09:30", "end": "10:00", "cutoff": "12:00"},
        "session_range": {"tz": "America/New_York", "start": "04:00", "end": "09:30", "cutoff": "12:00"},
        "exness": "USTEC",
        "note": "أسعار عقود ناسداك الآجلة (NQ=F) متأخرة ~10 دقائق وتختلف قليلاً عن سعر NAS100 في منصتك",
    },
}

TIMEFRAMES = ("15m", "1h", "4h", "1d")


def get_market(key):
    if key not in MARKETS:
        raise ValueError(f"unknown market '{key}', choose one of {list(MARKETS)}")
    return MARKETS[key]
