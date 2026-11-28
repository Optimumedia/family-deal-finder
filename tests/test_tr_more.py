"""Bee Travel (beetravel.bg) hotel-only Turkey parser tests against saved pages (28.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession, fixture
from trips import run, validate
from trips.http import Blocked
from trips.sources import tr_more as t

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 28)
KUS = {"url": "https://beetravel.bg/produkt-kategoriya/turciya/kusadasi/", "season": "summer",
       "area": "Kusadasi, Aegean coast", "region": "Aegean coast, Turkey", "country": "TR",
       "lat": 37.86, "lng": 27.26, "airport": "ADB"}
DIDIM = {"url": "https://beetravel.bg/produkt-kategoriya/turciya/didim/", "season": "summer",
         "area": "Didim, Aegean coast", "region": "Aegean coast, Turkey", "country": "TR",
         "lat": 37.37, "lng": 27.26, "airport": "BJV"}


def cfg(**src):
    c = dict(CFG)
    c["family"] = {**CFG["family"], "kids_birthdate": "2023-10-15"}
    c["sources"] = {**CFG["sources"], "tr_more": {"enabled": True, "nights": 7, "check_ins": ["2027-07-03"],
                                                  "pages": [KUS, DIDIM], **src}}
    return c


ROUTES = [
    (r"/produkt-kategoriya/turciya/kusadasi/$", "tr_more_list_kusadasi.html"),
    (r"/produkt-kategoriya/turciya/didim/$", "tr_more_list_didim.html"),
    (r"/tours/palm-wings-ephesus-beach-resort-kushadasa/$", "tr_more_palm_wings_ephesus.html"),
    (r"/tours/aqua-fantasy-aquapark-kushadasa/$", "tr_more_aqua_fantasy.html"),
    (r"/tours/sunis-efes-royal-palace-resort-spa-jozdere/$", "tr_more_sunis_efes.html"),
    (r"/tours/aquasis-de-luxe-resort-spa-didim/$", "tr_more_aquasis.html"),
]


class TestList(unittest.TestCase):
    def test_kusadasi_products_only(self):
        cards = t.parse_list(fixture("tr_more_list_kusadasi.html"))
        self.assertEqual(len(cards), 7)                       # sidebar's Bulgarian hotels are not in the list
        self.assertFalse(any("primorsko" in c["slug"] for c in cards))
        c = next(x for x in cards if x["slug"] == "palm-wings-ephesus-beach-resort-kushadasa")
        self.assertEqual((c["name"], c["town"], c["from_pp_night"]), ("Palm Wings Ephesus Beach Resort", "Kusadasi", 64.0))
        self.assertTrue(c["image"].startswith("https://beetravel.bg/wp-content/uploads/"))
        sunis = next(x for x in cards if x["slug"].startswith("sunis"))
        self.assertEqual(sunis["town"], "Ozdere")
        self.assertIsNone(next(x for x in cards if x["slug"].startswith("tusan"))["from_pp_night"])

    def test_title_split(self):
        self.assertEqual(t.split_title("Aquasis De Luxe Resort &#038; Spa -Дидим"), ("Aquasis De Luxe Resort & Spa", "Didim"))
        self.assertEqual(t.split_title("Tusan Beach Resort- Кушадасъ"), ("Tusan Beach Resort", "Kusadasi"))
        self.assertEqual(t.split_title("Plain Name"), ("Plain Name", None))


class TestDetail(unittest.TestCase):
    def test_palm_wings_price_table(self):
        d = t.parse_detail(fixture("tr_more_palm_wings_ephesus.html"))
        self.assertEqual((d["name"], d["town"], d["stars"]), ("Palm Wings Ephesus Beach Resort", "Kusadasi", 5))
        self.assertEqual((d["lat"], d["lng"]), (37.92787, 27.28036))
        self.assertEqual(len(d["periods"]), 14)
        self.assertEqual(d["periods"][6], ("2027-07-03", "2027-07-09"))
        self.assertEqual([r["room"].split(" - ")[0] for r in d["rooms"]],
                         ["Стандартна стая", "Разширена стая с двуетажно легло", "Фамилна стая"])
        self.assertEqual(d["rooms"][1]["prices"][6], 249.5)
        self.assertEqual((d["basis"], d["board"]), ("person", "AI"))
        self.assertEqual([(r["slot"], r["max_age"], r["pct"]) for r in d["child_rules"]], [("any", 6.99, 0.0), ("one", 12.99, 0.0)])
        f = d["family"]
        self.assertTrue(f["sand_beach"] and f["aquapark"] and f["kids_club"])
        self.assertEqual((f["kids_free_max_age"], f["first_child_free_max_age"]), (6.99, 12.99))
        self.assertEqual(d["image"], "https://beetravel.bg/wp-content/uploads/2026/10/palm-wings.jpg")

    def test_odd_number_formats(self):
        d = t.parse_detail(fixture("tr_more_aqua_fantasy.html"))     # "106 . 00€", "127,50€", "83.00 €"
        std = d["rooms"][0]
        self.assertEqual(std["prices"][:4], [73.0, 75.0, 106.0, 127.5])
        self.assertEqual(d["board"], "AI")                             # "Тип изхранване: ULTRA ALL INCLUSIVE /UALL/"
        self.assertEqual(d["periods"][0], ("2027-04-23", "2027-05-11"))

    def test_basis_line_board(self):
        d = t.parse_detail(fixture("tr_more_sunis_efes.html"))       # "Hight class All Inclusive" in the basis line
        self.assertEqual(d["board"], "AI")
        self.assertEqual(len(d["rooms"]), 4)
        self.assertEqual(d["town"], "Ozdere")


class TestPrice(unittest.TestCase):
    RULES = [{"slot": "any", "min_age": 0.0, "max_age": 6.99, "pct": 0.0},
             {"slot": "one", "min_age": 0.0, "max_age": 12.99, "pct": 0.0}]

    def test_kids_share(self):
        self.assertEqual(t.kids_share(self.RULES, [3.7, 3.7]), [0.0, 0.0])
        self.assertEqual(t.kids_share(self.RULES, [9, 3]), [0.0, 0.0])
        self.assertIsNone(t.kids_share(self.RULES, [8, 10]))           # only ONE child up to 12.99 is free
        half = [{"slot": 1, "min_age": 0.0, "max_age": 12.99, "pct": 0.0}, {"slot": 2, "min_age": 0.0, "max_age": 12.99, "pct": 50.0}]
        self.assertEqual(t.kids_share(half, [5, 5]), [0.0, 0.5])

    def test_child_rule_with_percent(self):
        html = ('<div id="tab-price_tab"><table><tr><td>ТИП ПОМЕЩЕНИЕ</td><td>01.07.2027<br/>31.07.2027</td></tr>'
                '<tr><td>Фамилна стая</td><td>100.00 €</td></tr>'
                '<tr><td colspan="2">Посочените цени са на човек на нощувка</td></tr>'
                '<tr><td colspan="2">Първо дете до 12.99 г се настанява безплатно.</td></tr>'
                '<tr><td colspan="2">Второ дете до 12.99 г заплаща 50% от цената.</td></tr></table></div>'
                '<div id="tab-location_tab"></div>')
        p = t.parse_prices(html)
        self.assertEqual([(r["slot"], r["pct"]) for r in p["child_rules"]], [(1, 0.0), (2, 50.0)])
        shares = t.kids_share(p["child_rules"], [3, 3])
        self.assertEqual(t.stay_price(p["rooms"][0], p["periods"], "2027-07-01", 7, 2, shares, p["basis"]), 1750.0)

    def test_stay_crosses_periods(self):
        d = t.parse_detail(fixture("tr_more_palm_wings_ephesus.html"))
        bunk = d["rooms"][1]
        self.assertEqual(t.stay_price(bunk, d["periods"], "2027-07-03", 7, 2, [0, 0], "person"), 3493.0)
        self.assertEqual(t.stay_price(bunk, d["periods"], "2027-07-07", 7, 2, [0, 0], "person"),
                         2 * (3 * 249.5 + 4 * 282.5))
        self.assertIsNone(t.stay_price(bunk, d["periods"], "2027-10-28", 7, 2, [0, 0], "person"))   # past 31.10


class TestFetch(unittest.TestCase):
    def test_offers(self):
        s = FakeSession(ROUTES)
        hotels, offers = t.fetch(cfg(), TODAY, session=s)
        by = {o["hotel"]: o for o in offers}
        pw = by["bee-palm-wings-ephesus-beach-resort-kushadasa"]
        self.assertEqual((pw["occupancy"], pw["price_eur"], pw["board"], pw["nights"]), ("2+2", 3493.0, "AI", 7))
        self.assertIn("двуетажно легло", pw["room"])
        self.assertIn("kids free", pw["room"])
        sunis = by["bee-sunis-efes-royal-palace-resort-spa-jozdere"]
        self.assertEqual((sunis["occupancy"], sunis["price_eur"]), ("2+2", 2 * (4 * 285.5 + 3 * 337.0)))
        aq = by["bee-aquasis-de-luxe-resort-spa-didim"]                  # no family room listed
        self.assertEqual((aq["occupancy"], aq["price_eur"]), ("2+0", 2 * 7 * 173.0))
        self.assertIn("no family room", aq["room"])
        self.assertEqual(len(offers), 4)                                 # 4 pages saved; the other 5 hotels answer ""
        hmap = {h["id"]: h for h in hotels}
        h = hmap["bee-sunis-efes-royal-palace-resort-spa-jozdere"]
        self.assertEqual((h["area"], h["stars"], h["direct_flight_skp"], h["border"], h["kind"]),
                         ("Ozdere, Aegean coast, Turkey", 5, True, False, "hotel"))
        self.assertIn("SKP→ADB", h["notes"])
        self.assertIn("SKP→BJV", hmap["bee-aquasis-de-luxe-resort-spa-didim"]["notes"])
        lim = validate.limits(CFG)
        for o in offers:
            self.assertEqual(validate.problems(o, TODAY, lim, hmap[o["hotel"]]), [], o)
        self.assertEqual(s.requests_made, 2 + 9)                         # 2 lists + 1 page per hotel

    def test_hotels_filter_and_out_of_season(self):
        page = {**KUS, "hotels": ["palm-wings-ephesus-beach-resort-kushadasa"]}
        _, offers = t.fetch(cfg(pages=[page], check_ins=["2027-07-03", "2027-11-20", "2026-01-01"]), TODAY,
                            session=FakeSession(ROUTES))
        self.assertEqual([o["check_in"] for o in offers], ["2027-07-03"])

    def test_disabled_and_blocked(self):
        c = cfg(enabled=False)
        self.assertEqual(t.fetch(c, TODAY, session=FakeSession(ROUTES)), ([], []))
        s = FakeSession([(r"beetravel", Blocked("403"))])
        self.assertEqual(t.fetch(cfg(), TODAY, session=s), ([], []))
        self.assertEqual(len(s.urls), 1)                                 # stops at the first block


if __name__ == "__main__":
    unittest.main()
