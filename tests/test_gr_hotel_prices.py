"""Greek family hotels' owner price lists (Grčka Info hotel pages): parser tests on saved pages. No network."""
import copy
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession
from trips import run
from trips.http import Blocked
from trips.sources import gr_hotel_prices as g

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
PAGE = {"url": "https://grckainfo.com/en/accommodation/x/2413/", "season": "summer", "area": "Limenaria, Thassos",
        "country": "GR", "lat": 40.62, "lng": 24.57, "nights": 7, "check_in": "2027-06-20"}


def read(name):
    return (FIX / f"gr_hotel_prices_{name}.html").read_text(encoding="utf-8")


def offers(name, cfg=CFG, **page):
    return g.hotel_offers(g.parse_page(read(name)), {**PAGE, **page}, cfg, TODAY)


def cfg_born(bd):
    c = copy.deepcopy(CFG)
    c["family"]["kids_birthdate"] = bd
    return c


class Page(unittest.TestCase):
    def test_units_and_rates(self):
        p = g.parse_page(read("thalassies"))
        self.assertEqual(p["name"], "Thalassies Hotel")
        self.assertAlmostEqual(p["lat"], 40.626067)
        self.assertTrue(p["image"].startswith("https://grckainfo.com/uploads/"))
        self.assertEqual([(u["adults"], u["kids"]) for u in p["units"]], [(3, 1), (2, 2), (3, 0), (2, 1), (2, 0)])
        fam = p["units"][1]
        self.assertEqual(fam["name"], "Room - half board")
        self.assertEqual(fam["rates"][0], {"from": "2027-04-09", "to": "2027-04-13", "night": 167.0})
        self.assertEqual(len(fam["rates"]), 6)
        self.assertIn("Accommodation on the beach", p["amenities"])

    def test_beach_distance(self):
        self.assertEqual(g.parse_page(read("mallas"))["beach_m"], 100)

    def test_period_formats(self):
        self.assertEqual(g._period("25 Jun 2027 – 08 Sep 2027"), (date(2027, 6, 25), date(2027, 9, 8)))
        self.assertEqual(g._period("01.05.2027. – 30.06.2027."), (date(2027, 5, 1), date(2027, 6, 30)))
        self.assertIsNone(g._period("on request"))


class Policy(unittest.TestCase):
    def pol(self, name):
        return g.parse_policy(g.parse_page(read(name))["notes"])

    def test_hb_included(self):
        p = self.pol("thalassies")
        self.assertEqual((p["basis"], p["board"], p["hb"]), ("unit", "HB", None))
        self.assertEqual(p["child_max"], 12)          # "over 11.99 are considered adults"
        self.assertEqual(p["kids_free_max_age"], 2)   # "Children: 0 to 1,99 - free"
        self.assertEqual(p["tax_room_day"], 3)

    def test_hb_supplement_with_child_rate(self):
        p = self.pol("mallas")
        self.assertEqual(p["board"], "BB")
        self.assertEqual(p["hb"]["adult"], 16)
        self.assertEqual(p["hb"]["rules"], [{"lo": 2.0, "hi": 10.0, "price": 15.0}])
        self.assertEqual(p["min_stay"], 3)

    def test_per_two_persons_and_supplement_block(self):
        p = self.pol("royal_paradise")
        self.assertEqual(p["basis"], "pair")
        self.assertEqual(p["hb"]["adult"], 20)
        self.assertIn({"lo": 0.0, "hi": 6.0, "price": 0.0}, p["hb"]["rules"])
        self.assertIn({"lo": 6.0, "hi": 12.0, "price": 15.0}, p["hb"]["rules"])
        self.assertEqual(p["first_child_free_max_age"], 4)
        self.assertIsNone(p["kids_free_max_age"])     # "Children 0-5,99 - free" is the HB rule, not the stay

    def test_everyone_over_one_is_adult(self):
        p = self.pol("alkioni")
        self.assertEqual(p["child_max"], 1)
        self.assertTrue(p["dynamic"])

    def test_meals_priced_separately(self):
        p = self.pol("akrothalassia")
        self.assertIsNone(p["board"])
        self.assertTrue(p["meals_extra"])
        self.assertEqual(p["hb"]["adult"], 18)        # breakfast 8 + dinner 10
        self.assertEqual(p["hb"]["rules"], [{"lo": 6.0, "hi": 12.0, "price": 9.0}])   # 6-11.99: 50 % off
        self.assertEqual(p["kids_free_max_age"], 6)


class Offers(unittest.TestCase):
    def test_exact_family_variant_hb(self):
        h, o = offers("thalassies")
        self.assertEqual(len(o), 1)
        x = o[0]
        self.assertEqual((x["occupancy"], x["board"], x["nights"], x["check_in"]), ("2+2", "HB", 7, "2027-06-20"))
        self.assertEqual(x["price_eur"], 5 * 223 + 2 * 283)   # 20-24 Jun at 223, 25-26 Jun at 283
        self.assertEqual(h["id"], "gih-2413")
        self.assertEqual(h["kind"], "hotel")
        self.assertTrue(h["family"]["beachfront"])
        self.assertEqual(h["family"]["kids_free_max_age"], 2)
        self.assertIn("Tourist tax 3", h["notes"])

    def test_bb_plus_hb_supplement_child_rate(self):
        _, o = offers("mallas", cfg=cfg_born("2023-10-15"))
        x = o[0]
        self.assertEqual((x["occupancy"], x["board"]), ("2+2", "HB"))
        room = g.stay_price(next(u for u in g.parse_page(read("mallas"))["units"]
                                 if u["name"].startswith("Superior Junior Suite Phoibe") and u["kids"] == 2)["rates"],
                            date(2027, 6, 20), 7)
        self.assertEqual(x["price_eur"], room + (2 * 16 + 2 * 15) * 7)
        self.assertIn("kids 15 €", x["room"])

    def test_kids_counted_as_adults(self):
        _, o = offers("alkioni")
        self.assertTrue(o)
        self.assertTrue(all(x["occupancy"] == "2+2" and "4 adults" in x["room"] for x in o))

    def test_kids_in_adult_place(self):
        _, o = offers("simeon")
        self.assertTrue(all("[3 adults + 1 children" in x["room"] or "[4 adults" in x["room"] for x in o))
        self.assertLessEqual(len(o), 3)               # max_rooms
        self.assertEqual([x["price_eur"] for x in o], sorted(x["price_eur"] for x in o))

    def test_meals_for_kids_without_child_rate_cost_adult_rate(self):
        _, o = offers("akrothalassia", cfg=cfg_born("2023-10-15"))
        x = o[0]
        self.assertEqual(x["board"], "HB")
        self.assertIn("adult rate", x["room"])
        self.assertIn("[3 adults + 1 children", x["room"])

    def test_per_two_persons_gives_2_plus_0(self):
        h, o = offers("royal_paradise")
        self.assertEqual(len(o), 1)
        self.assertEqual((o[0]["occupancy"], o[0]["board"]), ("2+0", "HB"))
        self.assertIn("per 2 persons", h["notes"])

    def test_stay_outside_published_periods(self):
        h, o = offers("thalassies", check_in="2027-10-18")   # list ends 20 Oct
        self.assertEqual((h, o), (None, []))

    def test_past_check_in_skipped_and_several_check_ins(self):
        _, o = offers("thalassies", check_in=None, check_ins=["2026-07-01", "2027-06-01", "2027-07-01"])
        self.assertEqual([x["check_in"] for x in o], ["2027-06-01", "2027-07-01"])

    def test_stay_price(self):
        rates = [{"from": "2027-06-01", "to": "2027-06-03", "night": 10.0}]
        self.assertEqual(g.stay_price(rates, date(2027, 6, 1), 3), 30.0)
        self.assertIsNone(g.stay_price(rates, date(2027, 6, 2), 3))


class Fetch(unittest.TestCase):
    def cfg(self, pages):
        c = copy.deepcopy(CFG)
        c["sources"]["gr_hotel_prices"] = {"enabled": True, "nights": 7, "check_in": "2027-06-20", "pages": pages}
        return c

    def test_fetch_reads_configured_pages(self):
        s = FakeSession([(r"/thalassies-hotel/2413/", "gr_hotel_prices_thalassies.html"),
                         (r"/hotel-mallas/1145/", "gr_hotel_prices_mallas.html")])
        pages = [{"url": "https://grckainfo.com/en/accommodation/thalassies-hotel/2413/", "area": "Limenaria, Thassos",
                  "lat": 40.62, "lng": 24.57},
                 {"url": "https://grckainfo.com/en/accommodation/hotel-mallas/1145/", "area": "Nea Kallikratia, Halkidiki",
                  "lat": 40.31, "lng": 23.06},
                 {"url": "https://grckainfo.com/en/accommodation/gone/9999/", "area": "X", "lat": 0, "lng": 0}]
        hotels, offs = g.fetch(self.cfg(pages), TODAY, session=s)
        self.assertEqual([h["id"] for h in hotels], ["gih-2413", "gih-1145"])
        self.assertTrue(all(o["source"] == g.SOURCE and o["seen"] == TODAY.isoformat() for o in offs))
        self.assertEqual({h["season"] for h in hotels}, {"summer"})

    def test_disabled_and_blocked(self):
        c = self.cfg([])
        c["sources"]["gr_hotel_prices"]["enabled"] = False
        self.assertEqual(g.fetch(c, TODAY, session=FakeSession()), ([], []))
        s = FakeSession([(r".", Blocked("403"))])
        pages = [{"url": "https://grckainfo.com/en/accommodation/a/1/", "area": "A", "lat": 0, "lng": 0}] * 2
        self.assertEqual(g.fetch(self.cfg(pages), TODAY, session=s), ([], []))
        self.assertEqual(len(s.urls), 1)              # stops after the block


if __name__ == "__main__":
    unittest.main()
