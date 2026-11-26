"""The family's rating rule (4.3+/5, 8.2+/10) and the Google Places lookup (no network)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import ratings, run, score

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
ST = ratings.settings(CFG)


class Rule(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(ratings.threshold(5, ST), 4.3)
        self.assertEqual(ratings.threshold(10, ST), 8.2)
        self.assertAlmostEqual(ratings.threshold(100, ST), 82)

    def test_verdicts(self):
        self.assertIsNone(ratings.verdict([], ST)[0])
        self.assertTrue(ratings.verdict([{"source": "Google", "score": 4.5, "scale": 5, "count": 300}], ST)[0])
        self.assertFalse(ratings.verdict([{"source": "Google", "score": 4.2, "scale": 5, "count": 300}], ST)[0])
        self.assertFalse(ratings.verdict([{"source": "Booking", "score": 8.1, "scale": 10, "count": 90}], ST)[0])
        # any credible low rating fails, even when another site is high
        both = [{"source": "Google", "score": 4.6, "scale": 5, "count": 500},
                {"source": "Booking", "score": 7.9, "scale": 10, "count": 200}]
        ok, why = ratings.verdict(both, ST)
        self.assertFalse(ok)
        self.assertIn("Booking", why)
        # too few reviews: ignored, so unknown
        self.assertIsNone(ratings.verdict([{"source": "Google", "score": 3.0, "scale": 5, "count": 3}], ST)[0])

    def test_low_rating_excludes_in_scoring(self):
        h = {"id": "h", "name": "Test", "season": "summer", "stars": 4, "border": True,
             "family": {"sand_beach": True, "beach_m": 20, "verified": [],
                        "ratings": [{"source": "Google", "score": 4.0, "scale": 5, "count": 120}]}}
        o = {"check_in": "2027-06-20", "board": "HB", "occupancy": "2+2", "nights": 7}
        f = score.family_fit(h, o, CFG, 200)
        self.assertTrue(any("Rated 4/5 on Google" in x for x in f["failed"]))


class Fake:
    def __init__(self, places):
        self.places, self.calls = places, 0

    def __call__(self, url, json=None, timeout=None, headers=None):
        self.calls += 1
        places = self.places

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return {"places": places}
        return R()


class Google(unittest.TestCase):
    H = {"id": "h1", "name": "Xenios Anastasia Resort & Spa", "area": "Nea Skioni, Kassandra", "lat": 39.95, "lng": 23.53}

    def test_match_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {**CFG, "ratings": {**CFG.get("ratings", {}), "google_api_key": "k", "cache": str(Path(d) / "c.json")}}
            fake = Fake([{"displayName": {"text": "Some Other Hotel"}, "rating": 3.1, "userRatingCount": 50,
                          "location": {"latitude": 39.95, "longitude": 23.53}},
                         {"displayName": {"text": "Anastasia Resort & Spa"}, "rating": 4.6, "userRatingCount": 1200,
                          "location": {"latitude": 39.951, "longitude": 23.531}, "id": "p1"}])
            hotels = {"h1": {**self.H, "family": {"verified": []}}}
            ratings.apply(hotels, cfg, date(2026, 11, 26), post=fake)
            self.assertEqual(hotels["h1"]["family"]["ratings"][0]["score"], 4.6)
            # second run: served from cache, no new call
            hotels2 = {"h1": {**self.H, "family": {"verified": []}}}
            ratings.apply(hotels2, cfg, date(2026, 11, 27), post=fake)
            self.assertEqual(fake.calls, 1)
            self.assertEqual(hotels2["h1"]["family"]["ratings"][0]["count"], 1200)

    def test_no_key_no_calls(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {**CFG, "ratings": {**CFG.get("ratings", {}), "google_api_key": "", "cache": str(Path(d) / "c.json")}}
            fake = Fake([])
            st = ratings.apply({"h1": dict(self.H)}, cfg, date(2026, 11, 26), post=fake)
            self.assertTrue(st["skipped_no_key"])
            self.assertEqual(fake.calls, 0)


if __name__ == "__main__":
    unittest.main()
