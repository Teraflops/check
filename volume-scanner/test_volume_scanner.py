import unittest

from volume_scanner import analyze, score

NOW = 1_800_000_000 // 60 * 60


def candle(minutes_ago, vol, open_=1.0, close=1.0):
    # [time, low, high, open, close, volume]; minutes_ago=1 is the last closed minute
    t = NOW - 60 * minutes_ago
    return [t, min(open_, close), max(open_, close), open_, close, vol]


class AnalyzeTest(unittest.TestCase):
    def test_flat_volume_has_ratio_near_one(self):
        candles = [candle(i, 100) for i in range(1, 66)]
        m = analyze(candles, NOW)
        self.assertAlmostEqual(m["ratio_5m"], 1.0)
        self.assertAlmostEqual(m["ratio_1m"], 1.0)

    def test_surge_with_buying_is_detected(self):
        candles = [candle(i, 100) for i in range(6, 66)]
        candles += [candle(i, 1000, open_=1.0, close=1.02) for i in range(1, 6)]
        m = analyze(candles, NOW)
        self.assertAlmostEqual(m["ratio_5m"], 10.0)
        self.assertEqual(m["buy_share_5m"], 1.0)
        self.assertGreater(m["price_change_5m"], 0)
        self.assertGreater(score(m), m["ratio_5m"])

    def test_forming_minute_is_ignored(self):
        candles = [candle(i, 100) for i in range(1, 66)]
        candles.append(candle(0, 1_000_000))  # current, still-forming minute
        self.assertAlmostEqual(analyze(candles, NOW)["ratio_1m"], 1.0)

    def test_missing_minutes_count_as_zero_volume(self):
        candles = [candle(i, 100) for i in range(1, 66) if i % 2]
        m = analyze(candles, NOW)
        self.assertIsNotNone(m)
        self.assertLess(m["ratio_5m"], 2)

    def test_too_little_history_returns_none(self):
        self.assertIsNone(analyze([candle(i, 100) for i in range(1, 5)], NOW))


if __name__ == "__main__":
    unittest.main()
