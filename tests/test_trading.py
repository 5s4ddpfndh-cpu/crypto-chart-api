import math
import random
import unittest
from unittest import mock

from trading import analyze, backtest
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
        result = backtest(make_candles(600, drift=0.001))
        self.assertIn("stats", result)
        for t in result["trades"]:
            self.assertGreaterEqual(t["resultR"], -1.0001)


class ApiTests(unittest.TestCase):
    def setUp(self):
        import app
        self.client = app.app.test_client()
        self.patch = mock.patch("app.fetch_candles", return_value=make_candles(drift=0.003))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_analyze(self):
        data = self.client.get("/analyze?symbol=btcusdt&balance=1000").get_json()
        self.assertEqual(data["symbol"], "BTCUSDT")
        self.assertIn("long", data)

    def test_mtf(self):
        data = self.client.get("/mtf").get_json()
        self.assertTrue(data["aligned"])
        self.assertEqual(data["bias"], "bullish")

    def test_dashboard(self):
        self.assertEqual(self.client.get("/dashboard").status_code, 200)


if __name__ == "__main__":
    unittest.main()
