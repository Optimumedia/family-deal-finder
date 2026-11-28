"""Montenegro coast hotels' 2027 price lists via Plan A Travel: parser tests on saved pages. No network."""
import copy
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession, no_network
from trips import run
from trips.http import Blocked
from trips.sources import me_coast as m

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 28)
PAGE = {"url": "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/becici.html", "season": "summer",
        "area": "Bečići, Montenegro", "country": "ME", "lat": 42.283, "lng": 18.87, "nights": 7,
        "check_in": "2027-07-04"}
URL = "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/x/{}.html"


def read(name):
    return (FIX / f"me_coast_{name}.html").read_text(encoding="utf-8")


def parsed(name, today=TODAY):
    return m.parse_page(read(name), today)


def offers(name, cfg=CFG, today=TODAY, **page):
    return m.hotel_offers(parsed(name, today), {**PAGE, **page}, cfg, today, URL.format(name))


def cfg_born(bd):
    c = copy.deepcopy(CFG)
    c["family"]["kids_birthdate"] = bd
    return c


TWINS = cfg_born("2023-10-15")


class Listing(unittest.TestCase):
    def test_cards_and_stickers(self):
        cards = m.parse_list(read("list_becici"))
        self.assertEqual(len(cards), 10)
        stickered = sorted(c["url"].rsplit("/", 1)[1] for c in cards if "2027" in c["sticker"])
        self.assertEqual(stickered, ["hotel-becici.html", "hotel-montenegro-beach-resort.html",
                                     "hotel-splendid-conference-spa-resort.html"])
        sp = next(c for c in cards if "splendid" in c["url"])
        self.assertEqual((sp["stars"], sp["beach_m"]), (5, 100))
        self.assertTrue(sp["url"].startswith("https://www.planatravel.rs/letovanje/crna-gora/"))

    def test_area_without_2027_lists(self):
        cards = m.parse_list(read("list_ulcinj"))
        self.assertEqual(len(cards), 3)
        self.assertFalse(any("2027" in c["sticker"] for c in cards))


class Table(unittest.TestCase):
    def test_per_person_per_day_table(self):
        t = parsed("palas")["table"]
        self.assertEqual(t["unit"], "person")
        self.assertEqual(len(t["periods"]), 5)
        self.assertEqual(t["periods"][2], [(date(2027, 7, 1), date(2027, 8, 31))])
        self.assertEqual(t["rooms"][0]["prices"], [52, 72, 90, 72, 52])
        self.assertEqual(t["rooms"][0]["cap"], 3)
        self.assertEqual(t["price_list_date"], "30.10.2026")

    def test_two_ranges_in_one_header_cell(self):
        t = parsed("splendid")["table"]
        self.assertEqual(t["periods"][0], [(date(2027, 1, 5), date(2027, 4, 30)), (date(2027, 11, 1), date(2027, 12, 23))])
        self.assertEqual(t["min_stay"][:3], [3, 3, 5])

    def test_fixed_stay_table(self):
        t = parsed("becici")["table"]
        self.assertEqual(t["stay_nights"][0], 9)
        self.assertEqual(t["periods"][0], [(date(2027, 6, 8), date(2027, 6, 17))])

    def test_page_without_price_list(self):
        p = parsed("sato")
        self.assertIsNone(p["table"])
        self.assertEqual(p["name"], "Hotel Sato")
        h, o = m.hotel_offers(p, PAGE, CFG, TODAY, URL.format("sato"))
        self.assertEqual(o, [])


class Rules(unittest.TestCase):
    def test_one_adult_rules_ignored(self):
        rules = parsed("palas")["table"]["rules"]
        self.assertTrue(rules)
        self.assertFalse(any("30%" in r["text"] and r["count"] == 2 for r in rules))   # the 1-adult "dvoje dece … -30%"
        two = [r for r in rules if r["count"] == 2]
        self.assertEqual([(r["share"], r["hint"]) for r in two], [(0.5, "1/2+1")])

    def test_pays_percent_own_bed(self):
        rules = parsed("becici")["table"]["rules"]
        self.assertIn(0.7, [r["share"] for r in rules if r["lo"] == 2])

    def test_coefficient_and_position_rules(self):
        rules = parsed("vile_oliva")["table"]["rules"]
        coef = [r for r in rules if r["count"] == 2]
        self.assertEqual([(r["coef"], r["hint"]) for r in coef], [(2.8, "superior")])
        self.assertFalse(any("peta" in r["text"].lower() or "četvrta" in r["text"].lower() for r in rules))

    def test_supplement_and_early_booking(self):
        t = parsed("montenegro_beach")["table"]
        self.assertEqual(t["supplement"], {"adult": 14.0, "kid_lo": 2.0, "kid_hi": 12.0, "kid_share": 0.5})
        self.assertEqual((t["early"]["pct"], t["early"]["until"], t["early"]["included"]), (15, "2026-12-31", True))
        self.assertEqual(t["early"]["kids_rule"]["count"], 1)

    def test_early_booking_expires(self):
        t = parsed("splendid", today=date(2027, 1, 5))["table"]
        self.assertIsNone(t["early"])
        self.assertFalse(any(r["count"] == 2 for r in t["rules"]))


class Offers(unittest.TestCase):
    def test_palas_two_kids_share_extra_bed(self):
        h, (o,) = offers("palas", TWINS)
        self.assertEqual((o["occupancy"], o["board"], o["nights"]), ("2+2", "HB", 7))
        self.assertEqual(o["price_eur"], 90 * 7 * 3)                  # 2 adults + 2 × 50 %
        self.assertTrue(h["family"]["beachfront"])
        self.assertEqual(h["id"], "pa-palas")

    def test_castellastva_apartment_row_only(self):
        _, (o,) = offers("castellastva", TWINS)
        self.assertTrue(o["room"].startswith("02 App"))
        self.assertEqual(o["price_eur"], 94 * 7 * 3)

    def test_castellastva_far_sandy_beach_not_taken_as_hotel_beach(self):
        h, _ = offers("castellastva")
        self.assertNotIn("sand_beach", h["family"])
        self.assertEqual(h["family"]["beach_m"], 150)

    def test_splendid_early_booking_kids_free_plus_half_board(self):
        h, (o,) = offers("splendid", TWINS)
        self.assertEqual((o["occupancy"], o["board"]), ("2+2", "HB"))
        self.assertEqual(o["price_eur"], 133 * 7 * 2 + 35 * 7 * 3)     # kids free on B&B, half the HB supplement
        self.assertAlmostEqual(o["was_eur"], 133 * 7 * 2 / 0.85 + 35 * 7 * 3, places=1)
        self.assertEqual((o["discount_label"], o["valid_until"]), ("Early booking -15%", "2026-12-31"))
        self.assertTrue(h["family"]["sand_beach"])
        self.assertEqual(h["stars"], 5)

    def test_splendid_after_early_booking_is_two_adults(self):
        _, (o,) = offers("splendid", TWINS, today=date(2027, 1, 5))
        self.assertEqual(o["occupancy"], "2+0")                       # rooms sleep 2+1: no stated 2+2 rule left
        self.assertEqual(o["price_eur"], 133 * 7 * 2 + 35 * 7 * 2)

    def test_montenegro_beach_three_bed_rooms_give_2_0(self):
        _, (o,) = offers("montenegro_beach", TWINS)
        self.assertEqual((o["occupancy"], o["board"]), ("2+0", "HB"))
        self.assertEqual(o["price_eur"], 97 * 7 * 2 + 14 * 7 * 2)

    def test_becici_fixed_nine_night_stay(self):
        h, (o,) = offers("becici", TWINS, sand_beach=True)
        self.assertEqual((o["check_in"], o["nights"], o["occupancy"]), ("2027-06-26", 9, "2+2"))
        self.assertEqual(o["price_eur"], round(470 * 3.4, 2))          # own beds: kids pay 70 %
        self.assertTrue(h["family"]["sand_beach"])                    # from the page setting

    def test_vile_oliva_coefficient(self):
        _, (o,) = offers("vile_oliva", TWINS)
        self.assertEqual((o["board"], o["occupancy"]), ("AI", "2+2"))
        self.assertAlmostEqual(o["price_eur"], 93 * 7 * 2.8, places=2)
        self.assertEqual(o["valid_until"], "2027-02-28")

    def test_several_check_ins(self):
        _, offs = offers("palas", TWINS, check_ins=["2027-06-20", "2027-08-22"])
        self.assertEqual([o["price_eur"] for o in offs], [72 * 7 * 3, 90 * 7 * 3])

    def test_price_crossing_two_periods(self):
        _, (o,) = offers("palas", TWINS, check_in="2027-06-27")
        self.assertEqual(o["price_eur"], (72 * 4 + 90 * 3) * 3)

    def test_pebble_beach_marked(self):
        p = parsed("korali")
        self.assertIs(p["sand_beach"], False)


class Fetch(unittest.TestCase):
    def cfg(self, **src):
        c = copy.deepcopy(TWINS)
        c["sources"]["me_coast"] = {"enabled": True, "pages": [
            {**PAGE, "sand_beach": True},
            {**PAGE, "url": "https://www.planatravel.rs/letovanje/crna-gora/budvanska-rivijera/petrovac.html",
             "area": "Petrovac, Montenegro"}], **src}
        return c

    ROUTES = [(r"rivijera/becici\.html$", "me_coast_list_becici.html"),
              (r"rivijera/petrovac\.html$", "me_coast_list_petrovac.html"),
              (r"hotel-becici\.html", "me_coast_becici.html"),
              (r"montenegro-beach-resort", "me_coast_montenegro_beach.html"),
              (r"splendid", "me_coast_splendid.html"), (r"palas", "me_coast_palas.html"),
              (r"castellastva", "me_coast_castellastva.html"), (r"vile-oliva", "me_coast_vile_oliva.html")]

    def test_reads_only_stickered_hotels(self):
        s = FakeSession(self.ROUTES)
        with no_network():
            hotels, offs = m.fetch(self.cfg(), TODAY, s)
        self.assertEqual(len(s.urls), 2 + 3 + 3)
        self.assertEqual(s.misses, [])
        self.assertEqual(len(hotels), 6)
        self.assertEqual(sum(o["occupancy"] == "2+2" for o in offs), 5)
        self.assertTrue(all(o["source"] == m.SOURCE and o["seen"] == "2026-11-28" for o in offs))
        self.assertTrue(all(h["country"] == "ME" and h["image"].startswith("https://") for h in hotels))

    def test_disabled(self):
        c = self.cfg(enabled=False)
        self.assertEqual(m.fetch(c, TODAY, FakeSession()), ([], []))

    def test_block_stops(self):
        s = FakeSession([(r".", Blocked("403"))])
        self.assertEqual(m.fetch(self.cfg(), TODAY, s), ([], []))
        self.assertEqual(len(s.urls), 1)


if __name__ == "__main__":
    unittest.main()
