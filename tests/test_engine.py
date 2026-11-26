"""Engine tests (no network): price history, real-vs-stated discount, family gates, caps, alerts once."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import db, run, score

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)

HOTEL = {"id": "h1", "name": "Test Beach", "stars": 4, "season": "summer", "area": "X", "lat": 40.0, "lng": 23.5,
         "border": True, "family": {"sand_beach": True, "beach_m": 20, "half_board": True, "verified": []}}


def offer(price, seen, was=None, valid_until=None, hotel="h1", occ="2+2", board="HB"):
    return {"hotel": hotel, "source": "test", "url": "https://example.test/offer", "seen": seen, "check_in": "2027-06-20", "nights": 7,
            "board": board, "room": "Family", "occupancy": occ, "price_eur": price, "was_eur": was,
            "valid_until": valid_until}


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")
        db.upsert_hotel(self.con, HOTEL)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _rate(self, drive=200, today=date(2026, 11, 25)):
        o = db.offers(self.con)[0]
        return score.rate(db.hotels(self.con)["h1"], o, db.offers(self.con), CFG, drive, today)

    def test_history_dedupes_same_day(self):
        self.assertTrue(db.add_sighting(self.con, offer(1000, "2026-11-20")))
        self.assertFalse(db.add_sighting(self.con, offer(1000, "2026-11-20")))
        self.assertTrue(db.add_sighting(self.con, offer(900, "2026-11-25")))
        self.assertEqual([h["price_eur"] for h in db.offers(self.con)[0]["history"]], [1000, 900])

    def test_stated_discount_counts_less_than_real(self):
        db.add_sighting(self.con, offer(800, "2026-11-25", was=1000))
        stated = self._rate()["deal"]
        self.assertEqual(stated["verdict"], "stated")
        db.add_sighting(self.con, offer(1000, "2026-11-01"))
        self.assertEqual(self._rate()["deal"]["verdict"], "unconfirmed")   # 2 checks: too thin to call "real"
        db.add_sighting(self.con, offer(1000, "2026-11-10"))
        real = self._rate()["deal"]
        self.assertEqual(real["verdict"], "real")
        self.assertEqual(real["real_pct"], 20.0)
        self.assertGreater(real["score"], stated["score"])

    def test_fake_discount_flagged_and_capped(self):
        db.add_sighting(self.con, offer(800, "2026-11-10"))
        db.add_sighting(self.con, offer(900, "2026-11-25", was=1200))    # "−25%" but dearer than before
        r = self._rate()
        self.assertEqual(r["deal"]["verdict"], "fake?")
        self.assertLessEqual(r["overall"], 54)

    def test_too_far_is_excluded_borderline_is_not(self):
        db.add_sighting(self.con, offer(1000, "2026-11-25"))
        self.assertTrue(self._rate(drive=400)["excluded"])
        r = self._rate(drive=290)               # 290 + 30 border = 320: within tolerance
        self.assertFalse(r["excluded"])
        self.assertIn("Direct flight or ≤5h drive", r["family"]["unknown_musts"])

    def test_bb_board_fails_summer(self):
        db.add_sighting(self.con, offer(700, "2026-11-25", board="BB"))
        self.assertIn("Breakfast + dinner", self._rate()["family"]["failed"])

    def test_unknown_cots_cap_rating_and_ask_hotel(self):
        db.add_sighting(self.con, offer(500, "2026-11-25", was=1000, valid_until="2026-11-27"))
        r = self._rate()
        self.assertLessEqual(r["overall"], CFG["score"]["unknown_cap"])
        self.assertTrue(any("cots" in q for q in r["family"]["questions"]))

    def test_cot_age_limit_vs_trip_age(self):
        h = dict(HOTEL, family=dict(HOTEL["family"], cots_max=2, cot_age_max=3))
        db.upsert_hotel(self.con, h)
        db.add_sighting(self.con, offer(1000, "2026-11-25"))
        cfg = {**CFG, "family": {**CFG["family"], "kids_birthdate": "2023-09-01"}}
        o = db.offers(self.con)[0]
        r = score.family_fit(db.hotels(self.con)["h1"], o, cfg, 200)
        self.assertIn("2 cots for twins aged 3 years 9 months", r["failed"])   # 3y9m > cot limit 3

    def test_alerts_go_out_once(self):
        db.add_sighting(self.con, offer(1000, "2026-11-25", valid_until="2026-11-27"))
        items, alerts = run.build(self.con, CFG, date(2026, 11, 25), offline=True)
        self.assertTrue(any(a["icon"] == "⏰" for a in alerts))
        _, again = run.build(self.con, CFG, date(2026, 11, 25), offline=True)
        self.assertFalse(any(a["icon"] == "⏰" for a in again))


if __name__ == "__main__":
    unittest.main()


class LocalConfig(unittest.TestCase):
    def test_private_file_overrides_public(self):
        with tempfile.TemporaryDirectory() as d:
            pub = Path(d) / "config.toml"
            pub.write_text('[family]\nkids = 2\nkids_birthdate = ""\n', encoding="utf-8")
            (Path(d) / "config.local.toml").write_text('[family]\nkids_birthdate = "2021-03-03"\n', encoding="utf-8")
            cfg = run.load_config(pub)
            self.assertEqual(cfg["family"], {"kids": 2, "kids_birthdate": "2021-03-03"})
            self.assertEqual(run.load_config(pub, local=None)["family"]["kids_birthdate"], "")
            self.assertAlmostEqual(score.kids_age_on(cfg, "2027-06-20"), 6.3, places=1)
