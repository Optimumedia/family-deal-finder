import unittest
from datetime import date

from trips import validate as v

TODAY = date(2026, 11, 25)


def offer(**kw):
    o = {"hotel": "sani-beach", "source": "Olympic", "url": "https://www.olympic.rs/x/1/", "seen": "2026-11-25",
         "check_in": "2027-06-20", "nights": 7, "board": "HB", "room": "family", "occupancy": "2+2",
         "price_eur": 1865.0}
    o.update(kw)
    return o


class ValidateTest(unittest.TestCase):
    def test_good_offer_passes(self):
        self.assertEqual(v.problems(offer(), TODAY), [])
        self.assertEqual(v.problems(offer(check_in=date(2027, 1, 10), board="?", occupancy="2+0"), TODAY), [])

    def test_check_in_today_ok_past_rejected(self):
        self.assertEqual(v.problems(offer(check_in="2026-11-25"), TODAY), [])
        self.assertIn("past", v.problems(offer(check_in="2026-11-24"), TODAY)[0])

    def test_check_in_horizon_18_months(self):
        self.assertEqual(v.problems(offer(check_in="2028-05-25"), TODAY), [])
        self.assertIn("18 months", v.problems(offer(check_in="2028-05-26"), TODAY)[0])
        self.assertIn("not a date", v.problems(offer(check_in="soon"), TODAY)[0])

    def test_nights_range(self):
        for n in (1, 21, "7", 7.0):
            self.assertEqual(v.problems(offer(nights=n, price_eur=200 * float(n)), TODAY), [], n)
        for n in (0, 22, -3, 2.5, None, "x", True):
            self.assertTrue(any("nights" in r for r in v.problems(offer(nights=n), TODAY)), n)

    def test_price_per_night_sane(self):
        self.assertIn("below", v.problems(offer(price_eur=61), TODAY)[0])        # a per-person-night price
        self.assertIn("above", v.problems(offer(price_eur=186500), TODAY)[0])    # decimal lost
        self.assertIn("positive", v.problems(offer(price_eur=0), TODAY)[0])
        self.assertIn("not a number", v.problems(offer(price_eur="€1.865"), TODAY)[0])
        self.assertIn("not a number", v.problems(offer(price_eur=float("nan")), TODAY)[0])

    def test_limits_from_config(self):
        cfg = {"validate": {"max_eur_per_night": 5000}}
        good, rej = v.split([offer(price_eur=7 * 3000)], TODAY, cfg)
        self.assertEqual((len(good), len(rej)), (1, 0))

    def test_board_occupancy_url_image(self):
        self.assertIn("board", v.problems(offer(board="Half board"), TODAY)[0])
        self.assertIn("occupancy", v.problems(offer(occupancy="2+1"), TODAY)[0])
        self.assertIn("https", v.problems(offer(url="http://www.olympic.rs/x/"), TODAY)[0])
        self.assertIn("https", v.problems(offer(url=None), TODAY)[0])
        self.assertIn("image", v.problems(offer(image="//cdn.x/a.jpg"), TODAY)[0])
        self.assertEqual(v.problems(offer(image=None), TODAY), [])
        self.assertEqual(v.problems(offer(image="https://cdn.x/a.jpg"), TODAY), [])
        self.assertTrue(v.bad_image({"image": "http://x/a.jpg"}))
        self.assertFalse(v.bad_image({"image": None}))

    def test_missing_occupancy_defaults_like_db(self):
        o = offer()
        del o["occupancy"]
        self.assertEqual(v.problems(o, TODAY), [])

    def test_split_and_report_by_source(self):
        offers = [offer(), offer(source="Travelland", board="XX", url="ftp://x"), offer(source="Travelland", nights=0)]
        good, rej = v.split(offers, TODAY)
        self.assertEqual(len(good), 1)
        self.assertEqual([len(r["reasons"]) for r in rej], [2, 1])
        rep = v.by_source(rej)
        self.assertEqual(rep["Travelland"]["rejected"], 2)
        self.assertEqual(rep["Travelland"]["reasons"], {"board": 1, "url": 1, "nights": 1})
        with self.assertLogs("trips.validate", "WARNING") as cm:
            v.log_rejects(rej)
        self.assertIn("2 offer(s) rejected", cm.output[0])

    def test_add_months_end_of_month(self):
        self.assertEqual(v.add_months(date(2026, 8, 31), 18), date(2028, 2, 29))
        self.assertEqual(v.add_months(date(2026, 11, 25), 18), date(2028, 5, 25))


if __name__ == "__main__":
    unittest.main()
