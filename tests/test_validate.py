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

    def test_was_price_must_be_above_price_and_sane(self):
        self.assertEqual(v.problems(offer(was_eur=2400.0), TODAY), [])
        self.assertEqual(v.problems(offer(was_eur=None), TODAY), [])
        self.assertIn("not above", v.problems(offer(was_eur=1865.0), TODAY)[0])     # equal = no discount
        self.assertIn("not above", v.problems(offer(was_eur=900.0), TODAY)[0])      # old/new swapped
        self.assertIn("above 80%", v.problems(offer(was_eur=1865.0 * 7), TODAY)[0])  # per-stay old vs per-night new
        self.assertEqual(v.problems(offer(was_eur=1865.0 * 4.9), TODAY), [])          # 79.6% off still allowed
        self.assertIn("not a number", v.problems(offer(was_eur="n/a"), TODAY)[0])
        cfg = {"validate": {"max_discount_pct": 90}}
        self.assertEqual(len(v.split([offer(was_eur=1865.0 * 7)], TODAY, cfg)[0]), 1)

    def test_season_checked_when_hotel_known(self):
        summer, winter = {"season": "summer"}, {"season": "winter"}
        self.assertEqual(v.problems(offer(check_in="2027-06-20"), TODAY, hotel=summer), [])
        self.assertIn("season summer", v.problems(offer(check_in="2027-01-15"), TODAY, hotel=summer)[0])
        self.assertIn("season winter", v.problems(offer(check_in="2027-07-01"), TODAY, hotel=winter)[0])
        for ci in ("2026-11-29", "2026-12-20", "2027-03-14", "2027-04-10"):
            self.assertEqual(v.problems(offer(check_in=ci), TODAY, hotel=winter), [], ci)
        self.assertEqual(v.problems(offer(check_in="2027-01-15"), TODAY), [])          # no hotel: no season rule
        good, rej = v.split([offer(check_in="2027-01-15")], TODAY, hotels={"sani-beach": summer})
        self.assertEqual((len(good), v.by_source(rej)["Olympic"]["reasons"]), (0, {"season": 1}))

    def test_duplicates_same_price_same_hotel_or_same_name(self):
        a = offer(room="Family room")
        b = offer(room="Family room sea view")                      # same price, dates, board: a copy
        c = offer(room="Suite", price_eur=2100.0)                   # other price: kept
        good, rej = v.split([a, b, c], TODAY)
        self.assertEqual([o["room"] for o in good], ["Family room", "Suite"])
        self.assertIn("duplicate", rej[0]["reasons"][0])
        # Savana lists one hotel per star category: two ids, same name and area, same price
        hotels = {"sv-melike-3": {"name": "Melike", "area": "Kusadasi, Aegean coast, Turkey", "season": "summer"},
                  "sv-melike-2": {"name": "MELIKE Hotel", "area": "Kusadasi, Turkey", "season": "summer"},
                  "sv-other": {"name": "Other", "area": "Kusadasi, Turkey", "season": "summer"}}
        offers = [offer(hotel="sv-melike-3", source="Savana Travel", price_eur=625.0, board="?"),
                  offer(hotel="sv-melike-2", source="Savana Travel", price_eur=625.0, board="?"),
                  offer(hotel="sv-other", source="Savana Travel", price_eur=625.0, board="?")]
        good, rej = v.split(offers, TODAY, hotels=hotels)
        self.assertEqual([o["hotel"] for o in good], ["sv-melike-3", "sv-other"])
        self.assertEqual(v.by_source(rej)["Savana Travel"]["reasons"], {"duplicate": 1})
        # without hotels only same-id copies are caught
        self.assertEqual(len(v.split(offers, TODAY)[0]), 3)

    def test_placeholder_images(self):
        ph = "https://atlantisonline.mk/ExtraContent/Img/listdefaultthumb.png"
        self.assertTrue(v.bad_image({"image": ph}))
        self.assertTrue(v.bad_image({"image": "https://x.com/img/no-image.jpg"}))
        self.assertTrue(v.bad_image({"image": "https://x.com/placeholder.png"}))
        self.assertFalse(v.bad_image({"image": "https://cdn.atlantis.mk/hotelphotos/bojur-genel-005.jpg"}))
        self.assertFalse(v.bad_image({"image": "https://mcdn.pro/data/objects/images/53306/53306_5841_thumb_800x600.jpeg"}))
        self.assertIn("placeholder", v.problems(offer(image=ph), TODAY)[0])

    def test_add_months_end_of_month(self):
        self.assertEqual(v.add_months(date(2026, 8, 31), 18), date(2028, 2, 29))
        self.assertEqual(v.add_months(date(2026, 11, 25), 18), date(2028, 5, 25))


if __name__ == "__main__":
    unittest.main()
