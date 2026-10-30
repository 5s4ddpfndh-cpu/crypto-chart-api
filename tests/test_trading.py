import math
import random
import unittest
from unittest import mock

from trading import analyze, backtest, compare, fetch_candles
from trading.strategies import STRATEGIES, build_context, live_signal
from trading.indicators import atr, ema, rsi


def make_candles(n=400, drift=0.002, seed=1, start=100.0):
    rng = random.Random(seed)
    candles, price = [], start
    for i in range(n):
        wave = math.sin(i / 12) * 0.006
        change = drift + wave + rng.gauss(0, 0.004)
        open_ = price
        close = price * (1 + change)
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.003)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.003)))
        candles.append({"openTime": i * 3_600_000, "open": open_, "high": high,
                        "low": low, "close": close, "volume": 1.0, "closeTime": 0})
        price = close
    return candles


class IndicatorTests(unittest.TestCase):
    def test_ema_constant_series(self):
        self.assertAlmostEqual(ema([5.0] * 30, 10)[-1], 5.0)

    def test_rsi_bounds(self):
        closes = [c["close"] for c in make_candles(100)]
        values = [v for v in rsi(closes) if v is not None]
        self.assertTrue(all(0 <= v <= 100 for v in values))
        self.assertEqual(rsi(list(range(1, 40)))[-1], 100.0)

    def test_atr_positive(self):
        c = make_candles(100)
        self.assertGreater(atr([x["high"] for x in c], [x["low"] for x in c], [x["close"] for x in c])[-1], 0)


class StrategyTests(unittest.TestCase):
    def assert_plan_consistent(self, plan):
        targets = [t["price"] for t in plan["targets"]]
        self.assertEqual(len(targets), 3)
        self.assertLessEqual(plan["entryZone"]["low"], plan["entry"])
        self.assertLessEqual(plan["entry"], plan["entryZone"]["high"])
        if plan["side"] == "long":
            self.assertLess(plan["stopLoss"], plan["entryZone"]["low"])
            self.assertEqual(targets, sorted(targets))
            self.assertGreater(targets[0], plan["entry"])
        else:
            self.assertGreater(plan["stopLoss"], plan["entryZone"]["high"])
            self.assertEqual(targets, sorted(targets, reverse=True))
            self.assertLess(targets[0], plan["entry"])
        self.assertGreaterEqual(plan["targets"][0]["rr"], 0.99)

    def test_uptrend_is_bullish(self):
        result = analyze(make_candles(drift=0.003))
        self.assertEqual(result["bias"], "bullish")
        self.assert_plan_consistent(result["long"])
        self.assert_plan_consistent(result["short"])

    def test_downtrend_is_bearish(self):
        result = analyze(make_candles(drift=-0.003))
        self.assertEqual(result["bias"], "bearish")
        self.assert_plan_consistent(result["short"])

    def test_position_sizing_risks_requested_amount(self):
        result = analyze(make_candles(drift=0.003), balance=10_000, risk_pct=1)
        plan = result["long"]
        loss = plan["position"]["quantity"] * (plan["entry"] - plan["stopLoss"])
        self.assertAlmostEqual(loss, 100, delta=1)

    def test_many_random_series_produce_valid_plans(self):
        for seed in range(20):
            for drift in (-0.002, 0.0, 0.002):
                result = analyze(make_candles(300, drift=drift, seed=seed))
                self.assert_plan_consistent(result["long"])
                self.assert_plan_consistent(result["short"])
                self.assertIn(result["signal"], ("BUY", "SELL", "WAIT"))

    def test_stop_stays_close_to_entry(self):
        for seed in range(20):
            for drift in (-0.002, 0.0, 0.002):
                result = analyze(make_candles(300, drift=drift, seed=seed))
                atr_value = result["indicators"]["atr"]
                for plan in (result["long"], result["short"]):
                    self.assertLessEqual(plan["riskPerUnit"], 1.51 * atr_value)

    def test_too_few_candles(self):
        with self.assertRaises(ValueError):
            analyze(make_candles(30))


class BacktestTests(unittest.TestCase):
    def test_backtest_runs(self):
        result = backtest(make_candles(600, drift=0.001), fee_pct=0)
        self.assertIn("stats", result)
        for t in result["trades"]:
            self.assertGreaterEqual(t["resultR"], -1.0001)

    def test_fees_reduce_results(self):
        candles = make_candles(800, drift=0.001)
        free = backtest(candles, "macd_trend", fee_pct=0)["stats"]
        paid = backtest(candles, "macd_trend", fee_pct=0.1)["stats"]
        self.assertGreater(free["trades"], 0)
        self.assertLess(paid["totalR"], free["totalR"])

    def test_price_unit_cost_reduces_results(self):
        candles = make_candles(800, drift=0.001)
        free = backtest(candles, "macd_trend", fee_pct=0)
        paid = backtest(candles, "macd_trend", fee_pct=0, cost=0.5)
        self.assertGreater(free["stats"]["trades"], 0)
        self.assertLess(paid["stats"]["totalR"], free["stats"]["totalR"])
        # The cost in R is the cost divided by the trade's own risk.
        f, p = free["trades"][0], paid["trades"][0]
        self.assertAlmostEqual(f["resultR"] - p["resultR"], 0.5 / abs(f["entry"] - f["stopLoss"]), places=2)

    def test_stats_report_t_stat_and_sides(self):
        stats = backtest(make_candles(1500, drift=0.0005, seed=3), "macd_trend", fee_pct=0)["stats"]
        self.assertIn("tStat", stats)
        self.assertEqual(stats["longs"]["trades"] + stats["shorts"]["trades"], stats["trades"])

    def test_verdict_needs_significance(self):
        from trading.backtest import verdict
        base = {"trades": 40, "totalR": 4.0, "profitFactor": 1.5, "consistent": True}
        self.assertEqual(verdict({**base, "tStat": 2.5}), "strong")
        self.assertEqual(verdict({**base, "tStat": 0.8}), "weak")

    def test_every_strategy_produces_valid_trades(self):
        candles = make_candles(1500, drift=0.0005, seed=3)
        for key in STRATEGIES:
            result = backtest(candles, key, fee_pct=0)
            for t in result["trades"]:
                direction = 1 if t["side"] == "long" else -1
                self.assertGreater((t["entry"] - t["stopLoss"]) * direction, 0, key)
                self.assertGreater((t["targets"][0] - t["entry"]) * direction, 0, key)
                self.assertGreaterEqual(t["resultR"], -1.0001, key)

    def test_strategies_do_not_look_ahead(self):
        candles = make_candles(700, seed=5)
        full, cut = build_context(candles), build_context(candles[:500])
        for key, meta in STRATEGIES.items():
            if key == "confluence":
                continue
            for i in range(250, 500):
                self.assertEqual(meta["fn"](full, i), meta["fn"](cut, i), (key, i))

    def test_compare_ranks_all_strategies(self):
        results = compare(make_candles(800, drift=0.001))
        self.assertEqual({r["strategy"] for r in results}, set(STRATEGIES))

    def test_live_signal_is_plan_or_none(self):
        candles = make_candles(400, drift=0.003)
        for key in STRATEGIES:
            plan = live_signal(candles, key)
            self.assertTrue(plan is None or plan["side"] in ("long", "short"))


class DataTests(unittest.TestCase):
    def yahoo_payload(self, start, count, step=3600):
        ts = [start + i * step for i in range(count)]
        closes = [100 + i for i in range(count)]
        closes[3] = None  # Yahoo sometimes returns gaps
        return {"chart": {"error": None, "result": [{
            "timestamp": ts,
            "indicators": {"quote": [{
                "open": closes, "high": [c and c + 1 for c in closes],
                "low": [c and c - 1 for c in closes], "close": closes,
                "volume": [10] * count,
            }]},
        }]}}

    def test_yahoo_parses_and_skips_gaps(self):
        from trading.data import fetch_yahoo
        response = mock.Mock()
        response.json.return_value = self.yahoo_payload(1_700_000_000 - 1_700_000_000 % 14400, 12)
        with mock.patch("trading.data.requests.get", return_value=response) as get:
            candles = fetch_yahoo("GC=F", "1h")
        self.assertEqual(len(candles), 11)
        self.assertEqual(get.call_args.kwargs["params"], {"interval": "60m", "range": "730d"})
        self.assertEqual(candles[0]["openTime"] % 1000, 0)

    def test_yahoo_4h_resamples(self):
        from trading.data import fetch_yahoo
        response = mock.Mock()
        response.json.return_value = self.yahoo_payload(1_700_000_000 - 1_700_000_000 % 14400, 12)
        with mock.patch("trading.data.requests.get", return_value=response):
            bars = fetch_yahoo("GC=F", "4h")
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0]["open"], 100)
        self.assertEqual(bars[0]["close"], 102)  # the hour at index 3 is a gap
        self.assertEqual(bars[1]["high"], 108)
        self.assertEqual(bars[1]["volume"], 40)

    def test_fetch_market_uses_cache(self):
        from trading import data
        data._cache.clear()
        with mock.patch("trading.data.fetch_yahoo", return_value=make_candles(300)) as fy:
            data.fetch_market("gold", "1h", 200)
            data.fetch_market("gold", "1h", 100)
        self.assertEqual(fy.call_count, 1)
        data._cache.clear()

    def test_fetch_pages_backwards(self):
        def fake_get(url, params, timeout):
            end = params.get("endTime", 10_000)
            rows = [[t, "1", "2", "0.5", "1.5", "10", t + 1] for t in range(end - params["limit"] + 1, end + 1)]
            response = mock.Mock()
            response.json.return_value = rows
            return response

        with mock.patch("trading.data.requests.get", side_effect=fake_get) as get:
            candles = fetch_candles("BTCUSDT", "15m", 2500)
        self.assertEqual(len(candles), 2500)
        self.assertEqual(get.call_count, 3)
        times = [c["openTime"] for c in candles]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(set(times)), 2500)


class ApiTests(unittest.TestCase):
    def setUp(self):
        import app
        self.client = app.app.test_client()
        self.patch = mock.patch("app.fetch_market", return_value=make_candles(drift=0.003))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_analyze(self):
        for market, symbol in (("btc", "BTCUSDT"), ("gold", "GC=F"), ("nasdaq", "NQ=F")):
            data = self.client.get(f"/analyze?market={market}&balance=1000").get_json()
            self.assertEqual(data["symbol"], symbol)
            self.assertIn("long", data)

    def test_unknown_market(self):
        self.assertEqual(self.client.get("/analyze?market=oil").status_code, 500)

    def test_markets(self):
        data = self.client.get("/markets").get_json()
        self.assertEqual(set(data["markets"]), {"gold", "btc", "nasdaq"})
        self.assertEqual(set(data["strategies"]), set(STRATEGIES))

    def test_mtf(self):
        data = self.client.get("/mtf").get_json()
        self.assertTrue(data["aligned"])
        self.assertEqual(data["bias"], "bullish")

    def test_analyze_with_strategy(self):
        data = self.client.get("/analyze?strategy=ema_pullback").get_json()
        self.assertEqual(data["strategy"], "ema_pullback")
        self.assertIn(data["signal"], ("BUY", "SELL", "WAIT"))

    def test_unknown_strategy(self):
        self.assertEqual(self.client.get("/backtest?strategy=nope").status_code, 500)

    def test_compare(self):
        data = self.client.get("/compare?market=gold").get_json()
        self.assertEqual(len(data["results"]), len(STRATEGIES))
        self.assertEqual(data["feePct"], 0.0)
        self.assertEqual(data["cost"], 0.30)
        self.assertEqual(self.client.get("/compare?market=gold&cost=0.13").get_json()["cost"], 0.13)
        for r in data["results"]:
            self.assertIn(r["verdict"], ("strong", "weak", "few_trades", "losing"))

    def test_dashboard(self):
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)


class CombinedAndAlertTests(unittest.TestCase):
    def test_combined_takes_trades_from_components(self):
        candles = make_candles(1500, drift=0.0005, seed=3)
        combo = backtest(candles, "combined", fee_pct=0, market="gold")
        components = {t["component"] for t in combo["trades"]}
        self.assertTrue(components)
        self.assertTrue(components <= {"breakout", "ema_pullback", "macd_trend"})
        single = max(backtest(candles, k, fee_pct=0)["stats"].get("trades", 0) for k in components)
        self.assertGreaterEqual(combo["stats"]["trades"], single)

    def test_new_signal_only_on_fresh_setup(self):
        from trading.strategies import new_signal
        candles = make_candles(600, drift=0.001, seed=9)
        x = build_context(candles, "gold")
        fn = STRATEGIES["combined"]["fn"]
        for end in range(300, 600):
            plan = new_signal(candles[:end], "combined", "gold")
            if plan:
                self.assertEqual(plan["signalTime"], candles[end - 2]["openTime"])
                prev = fn(x, end - 3)
                self.assertFalse(prev and prev["side"] == plan["side"])

    def test_check_alerts_sends_once_per_signal(self):
        from trading import alerts
        from trading.strategies import new_signal
        candles = make_candles(600, drift=0.001, seed=9)
        end = next(e for e in range(300, 600) if new_signal(candles[:e], "combined", "gold"))
        sent = []
        alerts._sent.clear()
        with mock.patch.dict("os.environ", {"ALERT_WATCHLIST": "gold:4h:combined"}):
            fetch = lambda m, iv, limit: candles[:end]
            first = alerts.check_alerts("https://x/", send=sent.append, fetch=fetch)
            second = alerts.check_alerts("https://x/", send=sent.append, fetch=fetch)
        self.assertEqual(first[0]["status"], "sent")
        self.assertEqual(second[0]["status"], "already_sent")
        self.assertEqual(len(sent), 1)
        self.assertIn("XAUUSD", sent[0])
        self.assertIn("الوقف", sent[0])
        alerts._sent.clear()

    def test_bad_watchlist_reports_error(self):
        from trading import alerts
        with mock.patch.dict("os.environ", {"ALERT_WATCHLIST": "oil:4h:combined"}):
            with self.assertRaises(ValueError):
                alerts.watchlist()

    def test_alert_routes_require_key(self):
        import app
        client = app.app.test_client()
        with mock.patch.dict("os.environ", {"ALERT_KEY": "s3cret"}):
            self.assertEqual(client.get("/alerts/check").status_code, 403)
            self.assertEqual(client.get("/alerts/test?key=nope").status_code, 403)
            with mock.patch("app.alerts.check_alerts", return_value=[]):
                self.assertEqual(client.get("/alerts/check?key=s3cret").status_code, 200)
        status = client.get("/alerts/status").get_json()
        self.assertEqual(len(status["watchlist"]), 2)

    def test_status_reports_last_check(self):
        import app
        from trading import alerts
        with mock.patch.dict("os.environ", {"ALERT_WATCHLIST": "gold:4h:combined"}):
            alerts.check_alerts(send=lambda text: None, fetch=lambda m, iv, limit: make_candles(400))
        status = app.app.test_client().get("/alerts/status").get_json()
        self.assertLess(status["lastCheckMinutesAgo"], 1)
        self.assertGreaterEqual(status["checksSinceRestart"], 1)
        self.assertEqual(status["lastResults"][0]["market"], "gold")

    def test_json_keeps_arabic(self):
        import app
        body = app.app.test_client().get("/markets").get_data(as_text=True)
        self.assertIn("الذهب", body)


class IntradayTests(unittest.TestCase):
    @staticmethod
    def day_of_15m(start_utc, opening_hi=101.0, breakout_close=102.0, bars=96):
        """A flat day of 15m candles starting at `start_utc` (a datetime), with a
        price range of 99-101 and one bar that closes at `breakout_close` at 10:00 New York."""
        from zoneinfo import ZoneInfo
        candles = []
        for k in range(bars):
            t = start_utc + __import__("datetime").timedelta(minutes=15 * k)
            ny = t.astimezone(ZoneInfo("America/New_York"))
            close = 100.0 + (0.5 if k % 2 else -0.5)
            if (ny.hour, ny.minute) == (10, 0):
                close = breakout_close
            candles.append({"openTime": int(t.timestamp() * 1000), "open": 100.0,
                            "high": max(close, opening_hi if (ny.hour, ny.minute) == (9, 30) else 100.6),
                            "low": min(close, 99.0), "close": close, "volume": 1.0, "closeTime": None})
        return candles

    def signals(self, candles, key="orb"):
        x = build_context(candles, "nasdaq")
        fn = STRATEGIES[key]["fn"]
        return [(i, fn(x, i)) for i in range(len(candles)) if fn(x, i)]

    def test_orb_fires_once_at_ny_open_across_dst(self):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        for day in (datetime(2026, 7, 15, tzinfo=timezone.utc), datetime(2026, 1, 15, tzinfo=timezone.utc)):
            prev = self.day_of_15m(datetime(day.year, day.month, day.day - 1, tzinfo=timezone.utc), breakout_close=100.5)
            today = self.day_of_15m(day)
            candles = prev + today
            found = self.signals(candles)
            self.assertEqual(len(found), 1, day)
            i, plan = found[0]
            ny = datetime.fromtimestamp(candles[i]["openTime"] / 1000, timezone.utc).astimezone(ZoneInfo("America/New_York"))
            self.assertEqual((ny.hour, ny.minute), (10, 0))
            self.assertEqual(plan["side"], "long")
            self.assertLess(plan["stopLoss"], plan["entry"])

    def test_orb_ignores_hourly_candles(self):
        candles = make_candles(400)
        x = build_context(candles, "nasdaq")
        self.assertTrue(all(STRATEGIES["orb"]["fn"](x, i) is None for i in range(250, 400)))

    def test_intraday_strategies_do_not_look_ahead(self):
        candles = [{**c, "openTime": 1_780_000_000_000 + i * 900_000} for i, c in enumerate(make_candles(1600, seed=4))]
        full, cut = build_context(candles, "gold"), build_context(candles[:1200], "gold")
        for key in ("mtf_pullback", "orb", "session_breakout", "sweep_mss"):
            fn = STRATEGIES[key]["fn"]
            for i in range(300, 1200):
                self.assertEqual(fn(full, i), fn(cut, i), (key, i))

    def test_sweep_mss_finds_sweep_then_shift(self):
        """Uptrend on 1h; at 10:00 UTC a wick sweeps the recent lows, then the
        next 15m candle closes above the leg's high: one long, entry on the retest."""
        from datetime import datetime, timezone
        start = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)
        candles = []
        for k in range(1200):
            p = 100 + 0.01 * k + (0.15 if k % 2 else -0.15)
            candles.append({"openTime": start + k * 900_000, "open": p - 0.05, "high": p + 0.2,
                            "low": p - 0.2, "close": p, "volume": 1.0, "closeTime": None})
        hour = lambda k: datetime.fromtimestamp(candles[k]["openTime"] / 1000, timezone.utc)
        t = next(k for k in range(1100, 1200) if (hour(k).hour, hour(k).minute) == (10, 0))
        base = candles[t - 7]["close"]
        for n, k in enumerate(range(t - 6, t)):
            p = base - 0.1 * (n + 1)
            candles[k].update(open=p + 0.2, high=p + 0.3, low=p - 0.1, close=p)
        swept = min(c["low"] for c in candles[t - 40:t]) - 0.3
        candles[t].update(open=candles[t - 1]["close"], high=candles[t - 1]["close"] + 0.1,
                          low=swept, close=candles[t - 1]["close"] + 0.05)
        leg_high = max(c["high"] for c in candles[t - 6:t + 1])
        candles[t + 1].update(open=candles[t]["close"], low=candles[t]["close"] - 0.1,
                              close=leg_high + 0.5, high=leg_high + 0.6)
        found = self.signals(candles[:t + 2], "sweep_mss")
        self.assertEqual([i for i, _ in found], [t + 1])
        plan = found[0][1]
        self.assertEqual(plan["side"], "long")
        self.assertFalse(plan["market"])
        self.assertAlmostEqual(plan["entry"], leg_high, places=4)
        self.assertLess(plan["stopLoss"], swept)

    def test_intraday_backtest_runs(self):
        candles = [{**c, "openTime": 1_780_000_000_000 + i * 900_000} for i, c in enumerate(make_candles(3000, drift=0.0003, seed=4))]
        for key in ("mtf_pullback", "orb", "session_breakout", "sweep_mss"):
            result = backtest(candles, key, fee_pct=0, market="gold")
            for t in result["trades"]:
                self.assertGreaterEqual(t["resultR"], -1.0001, key)
        self.assertGreater(backtest(candles, "mtf_pullback", market="gold")["stats"]["trades"], 0)


if __name__ == "__main__":
    unittest.main()
