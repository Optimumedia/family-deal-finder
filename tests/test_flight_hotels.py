"""Relaxo.bg hotel-only parser tests against saved pages (relaxo.bg, 26.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession, fixture
from trips import run, validate
from trips.http import Blocked
from trips.sources import flight_hotels as fh

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
KUS = {"url": "https://relaxo.bg/oferti-za/kushadasa", "season": "summer", "area": "Kusadasi, Aegean coast",
       "country": "TR", "lat": 37.86, "lng": 27.26, "airport": "ADB", "hotels": ["palm-wings-ephesus-beach-resort-5-kusadasi"]}


def cfg(**src):
    c = dict(CFG)
    c["family"] = {**CFG["family"], "kids_birthdate": "2023-10-15"}
    c["sources"] = {**CFG["sources"], "flight_hotels": {"enabled": True, "nights": 7, "check_ins": ["2027-07-03"],
                                                        "pages": [KUS], **src}}
    return c


ROUTES = [
    (r"/oferti-za/kushadasa$", "flight_hotels_list_kusadasi.html"),
    (r"/oferta/palm-wings-ephesus-beach-resort-5-kusadasi/rezultati\?", "flight_hotels_results_palmwings.html"),
    (r"/oferta/palm-wings-ephesus-beach-resort-5-kusadasi$", "flight_hotels_detail_palmwings.html"),
]


class TestList(unittest.TestCase):
    def test_kusadasi_cards(self):
        cards = fh.parse_list(fixture("flight_hotels_list_kusadasi.html"))
        self.assertEqual(len(cards), 22)
        c = next(x for x in cards if x["slug"] == "palm-wings-ephesus-beach-resort-5-kusadasi")
        self.assertEqual((c["name"], c["stars"], c["from_pp_night"], c["board"]),
                         ("Palm Wings Ephesus Beach Resort", 5, 53.0, "AI"))
        self.assertTrue(c["own_transport"])
        self.assertEqual(c["basis"], "на човек за нощувка")
        self.assertTrue(c["image"].startswith("https://relaxo.bg/media/"))
        derici = next(x for x in cards if x["name"] == "Derici Hotel")
        self.assertEqual(derici["board"], "HB")                       # "Полупансион"

    def test_cards_without_price_and_bb(self):
        cards = fh.parse_list(fixture("flight_hotels_list_cesme.html"))
        self.assertEqual([c["from_pp_night"] for c in cards], [55.0, None, None])
        self.assertEqual(cards[1]["board"], "BB")                     # "Закуска"

    def test_pick_cheapest_priced_or_listed(self):
        cards = fh.parse_list(fixture("flight_hotels_list_kusadasi.html"))
        got = fh.pick(cards, {"max_hotels": 3}, 5)
        self.assertEqual([c["from_pp_night"] for c in got], [24.0, 33.0, 34.0])
        got = fh.pick(cards, {"hotels": ["arora-hotel-4-kusadasi", "nope"]}, 5)
        self.assertEqual([c["slug"] for c in got], ["arora-hotel-4-kusadasi"])

    def test_board_codes(self):
        for text, code in [("Ultra All Inclusive", "AI"), ("HCAI", "AI"), ("Premier Ultra All Inclusive", "AI"),
                           ("Полупансион", "HB"), ("Закуска и вечеря", "HB"), ("Закуска", "BB"),
                           ("Пълен пансион", "FB"), ("Само нощувка", "RO"), ("", "?")]:
            self.assertEqual(fh.board_code(text), code, text)


class TestDetail(unittest.TestCase):
    def test_palm_wings(self):
        d = fh.parse_detail(fixture("flight_hotels_detail_palmwings.html"), TODAY)
        self.assertAlmostEqual(d["lat"], 37.9278, places=3)
        self.assertAlmostEqual(d["lng"], 27.2789, places=3)
        f = d["family"]
        self.assertTrue(f["sand_beach"] and f["beachfront"] and f["kids_club"] and f["kids_pool"])
        self.assertEqual(f["ratings"], [{"source": "Relaxo.bg", "score": 4.4, "scale": 5.0, "count": 5567}])
        self.assertEqual(d["season"], ("2027-05-15", "2027-09-30"))
        self.assertEqual(d["min_nights"], 7)
        self.assertEqual((d["promo"], d["promo_until"]), ("Black Friday", "2026-11-28"))
        self.assertTrue(d["image"].startswith("https://relaxo.bg/storage/uploads/"))

    def test_mixed_beach(self):
        d = fh.parse_detail(fixture("flight_hotels_detail_orangecounty.html"), TODAY)
        self.assertEqual(d["family"].get("beach_type"), "mixed")       # "Пясъчно-чакълест плаж"
        self.assertNotIn("sand_beach", d["family"])


class TestResults(unittest.TestCase):
    def test_black_friday_rows(self):
        r = fh.parse_results(fixture("flight_hotels_results_palmwings.html"))
        self.assertEqual((r["adults"], r["children"]), (2, 2))
        self.assertEqual(r["child_rules"], [{"child": 1, "max_age": 11, "free": True, "text": "БЕЗПЛАТНО"}])
        self.assertEqual([(x["room"], x["price"], x["was"]) for x in r["rows"]],
                         [("LARGE BUNKBED ROOM", 2335.76, 3461.54), ("FAMILY ROOM", 3027.83, 4487.18)])
        self.assertEqual(r["rows"][0]["badge"], "Black Friday -32%")
        self.assertEqual(r["rows"][0]["low30"], 2423.07)

    def test_early_booking_rows(self):
        r = fh.parse_results(fixture("flight_hotels_results_orangecounty.html"))
        self.assertEqual(len(r["rows"]), 4)
        first = r["rows"][0]
        self.assertEqual((first["price"], first["was"], first["early_booking_pct"], first["badge"]),
                         (2484.39, 4771.22, 48, None))

    def test_unavailable_and_empty(self):
        html = ('<div class="rx-section-header"><span>2 възрастни + 2 деца (3 г., 3 г.)</span></div>'
                '<div class="rx-row" data-price="1999.00" data-room-name="X" data-board="All Inclusive" data-available="0">')
        r = fh.parse_results(html)
        self.assertFalse(r["rows"][0]["available"])
        self.assertIsNone(fh.to_offer({"id": "rx-x", "family": {}}, {"url": "u"}, r, None, "2027-07-03", 7, "s",
                                      CFG, TODAY))
        self.assertEqual(fh.parse_results("")["rows"], [])

    def test_results_url(self):
        u = fh.results_url("https://relaxo.bg/oferta/x", "2027-07-03", 7, 2, [3, 3])
        self.assertEqual(u, "https://relaxo.bg/oferta/x/rezultati?date_from=2027-07-03&date_to=2027-07-10&rooms_count=1"
                            "&rooms%5B0%5D%5Badults%5D=2&rooms%5B0%5D%5Bchildren%5D=2&rooms%5B0%5D%5Bchild_ages%5D=3%2C3")


class TestFetch(unittest.TestCase):
    def test_end_to_end_family_price(self):
        s = FakeSession(ROUTES)
        hotels, offers = fh.fetch(cfg(), TODAY, session=s)
        self.assertEqual(s.misses, [])
        self.assertEqual(len(hotels), 1)
        h, o = hotels[0], offers[0]
        self.assertEqual(h["id"], "rx-palm-wings-ephesus-beach-resort-5-kusadasi")
        self.assertTrue(h["direct_flight_skp"])
        self.assertFalse(h["border"])
        self.assertEqual(h["kind"], "hotel")
        self.assertEqual(h["area"], "Kusadasi, Aegean coast")
        self.assertAlmostEqual(h["lat"], 37.928, places=2)
        self.assertEqual(h["family"]["first_child_free_max_age"], 11.0)
        self.assertIn("SKP→ADB", h["notes"])
        self.assertEqual(o["occupancy"], "2+2")
        self.assertEqual((o["price_eur"], o["was_eur"], o["board"], o["nights"]), (2335.76, 3461.54, "AI", 7))
        self.assertEqual(o["discount_label"], "Black Friday -32%")
        self.assertEqual(o["valid_until"], "2026-11-28")
        self.assertIn("child_ages%5D=3%2C3", o["url"])                  # twins are 3 on 03.07.2027
        self.assertEqual(validate.problems(o, TODAY, validate.limits(CFG), h), [])

    def test_party_not_echoed_is_two_adults(self):
        res = fixture("flight_hotels_results_palmwings.html").replace("2 възрастни + 2 деца", "2 възрастни")
        s = FakeSession([(ROUTES[1][0], res)] + ROUTES[:1] + ROUTES[2:])
        _, offers = fh.fetch(cfg(), TODAY, session=s)
        self.assertEqual(offers[0]["occupancy"], "2+0")
        self.assertEqual(offers[0]["url"], "https://relaxo.bg/oferta/palm-wings-ephesus-beach-resort-5-kusadasi")

    def test_check_in_outside_window_is_skipped(self):
        s = FakeSession(ROUTES)
        hotels, offers = fh.fetch(cfg(check_ins=["2027-10-15"]), TODAY, session=s)
        self.assertEqual((hotels, offers), ([], []))
        self.assertFalse(any("rezultati" in u for u in s.urls))

    def test_disabled_and_blocked(self):
        c = cfg()
        c["sources"]["flight_hotels"]["enabled"] = False
        self.assertEqual(fh.fetch(c, TODAY, session=FakeSession(ROUTES)), ([], []))
        s = FakeSession([(r"relaxo", Blocked("403"))])
        self.assertEqual(fh.fetch(cfg(), TODAY, session=s), ([], []))
        self.assertEqual(len(s.urls), 1)


if __name__ == "__main__":
    unittest.main()
