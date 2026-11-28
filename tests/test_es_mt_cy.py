"""Itaka hotel-only ("Dojazd własny") parser tests against saved search pages (itaka.pl, 28.11.2026).

The fixtures are the live pages trimmed to what the parser reads: the result-card links and the
__NEXT_DATA__ script. No network.
"""
import json
import re
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession, fixture
from trips import run, validate
from trips.http import Blocked
from trips.sources import es_mt_cy as m

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 28)
LIST = "https://www.itaka.pl/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations="
DORADA = {"url": LIST + "costa-dorada", "season": "summer", "area": "Costa Daurada (Salou, Cambrils, La Pineda)",
          "country": "ES", "lat": 41.07, "lng": 1.13, "max_km": 15, "airport": "BCN"}
MARESME = {"url": LIST + "costa-brava", "season": "summer", "area": "Maresme / southern Costa Brava",
           "country": "ES", "lat": 41.635, "lng": 2.72, "max_km": 20, "airport": "BCN"}
CYPRUS = {"url": LIST + "cypr", "season": "summer", "area": "Ayia Napa / Protaras / Larnaca bay",
          "country": "CY", "lat": 34.98, "lng": 33.85, "max_km": 30, "airport": "LCA"}
ROUTES = [(r"destinations=costa-dorada$", "es_mt_cy_costa_dorada.html"),
          (r"destinations=costa-brava$", "es_mt_cy_costa_brava.html"),
          (r"destinations=malta$", "es_mt_cy_malta.html"),
          (r"destinations=cypr$", "es_mt_cy_cypr.html")]


def cfg(pages, **src):
    c = dict(CFG)
    c["family"] = {**CFG["family"], "kids_birthdate": "2023-10-15"}
    c["sources"] = {**CFG["sources"], "es_mt_cy": {"enabled": True, "pln_eur": 0.235, "pages": pages, **src}}
    return c


def with_twins(html: str, code: str) -> str:
    """The same page as if searched for 2 adults + the twins: what a URL with the children's birth
    dates returns (participants typed "child", the server's rateParams echoing the birth dates)."""
    rx = re.compile(r'(<script id="__NEXT_DATA__"[^>]*>)(.*?)(</script>)', re.S)
    head, raw, tail = rx.search(html).groups()
    d = json.loads(raw)
    q = m._rates_query(d)
    q["queryKey"][1]["rateParams"]["participantGroups"][0]["childrenBirthDates"] = ["2023-10-15", "2023-10-15"]
    for r in q["state"]["data"]["main"]["multiRoomRates"]["list"]:
        if r["supplierObjectId"] == code:
            pg = r["participantGroups"][0]
            pg["participants"] += [{"price": 0, "baseCatalogPrice": 41950, "type": "child", "birthDate": "2023-10-15"},
                                   {"price": 41950, "baseCatalogPrice": 41950, "type": "child", "birthDate": "2023-10-15"}]
            pg["price"] += 41950
    return rx.sub(lambda _: head + json.dumps(d) + tail, html, count=1)


class TestListing(unittest.TestCase):
    def test_costa_dorada_rates(self):
        g = m.parse_listing(fixture("es_mt_cy_costa_dorada.html"))
        self.assertEqual(g["party"], {"adults": 2, "children": 0})
        self.assertEqual((g["count"], len(g["rates"])), (20, 15))
        r = next(x for x in g["rates"] if x["code"] == "AESBCD5D3O")
        self.assertEqual((r["name"], r["stars"], r["board"], r["meal_text"]), ("Hotel Best Sol d´Or", 4, "BB", "Śniadania"))
        self.assertEqual((r["check_in"], r["check_out"], r["nights"]), ("2027-05-02", "2027-05-06", 4))
        self.assertEqual((r["price_pln"], r["adults"], r["children"]), (1678.0, 2, 0))
        self.assertAlmostEqual(r["lat"], 41.066, places=3)
        self.assertIn("sandy-beach", r["facilities"])
        self.assertEqual((r["rating"], r["reviews"]), (4.8, 24))
        self.assertTrue(r["own_transport"])
        self.assertTrue(r["image"].startswith("https://s.content4travel.com/"))
        self.assertTrue(r["url"].startswith("https://www.itaka.pl/wczasy/hiszpania/costa-dorada/hotel-best-sol-dor,AESBCD5D3O/?"))
        self.assertIn("id%5B0%5D=", r["url"])

    def test_meal_codes(self):
        boards = {(x["meal"], x["board"]) for k in ("costa_brava", "malta", "costa_dorada")
                  for x in m.parse_listing(fixture(f"es_mt_cy_{k}.html"))["rates"]}
        self.assertTrue({("F", "BB"), ("H", "HB"), ("D", "HB"), ("A", "AI"), ("U", "RO")} <= boards)

    def test_malta_skips_cruise(self):
        g = m.parse_listing(fixture("es_mt_cy_malta.html"))
        self.assertEqual(len(g["rates"]), 14)                       # the 15th card is a Mediterranean cruise
        self.assertNotIn("FCOCR13", [r["code"] for r in g["rates"]])
        seabank = next(r for r in g["rates"] if r["code"] == "AMTSMT22IE")
        self.assertEqual((seabank["name"], seabank["board"]), ("db Seabank Resort + Spa", "HB"))

    def test_own_transport_flag(self):
        rates = {r["code"]: r for r in m.parse_listing(fixture("es_mt_cy_cypr.html"))["rates"]}
        self.assertTrue(rates["AMTSCY1YX8"]["own_transport"])       # Adams Beach, Ayia Napa
        self.assertFalse(rates["HBX911537"]["own_transport"])       # no "OTS" in its rate id
        self.assertIsNone(m.own_transport("%%%"))

    def test_empty_page(self):
        self.assertEqual(m.parse_listing("")["rates"], [])
        self.assertEqual(m.parse_listing("<html>no data</html>")["rates"], [])


class TestFilter(unittest.TestCase):
    def test_months_and_distance(self):
        rates = m.parse_listing(fixture("es_mt_cy_costa_brava.html"))["rates"]
        summer = [r["code"] for r in rates if m.keep(r, MARESME, [6, 7, 8, 9], TODAY)]
        self.assertEqual(summer, ["AESBCBCH86"])                     # Alegria El Mar, Santa Susanna, 24.09.2027
        caleta = next(r for r in rates if r["code"] == "AESBCB5GA0")  # Sant Feliu de Guíxols, ~40 km north
        self.assertFalse(m.keep(caleta, MARESME, [], TODAY))

    def test_paphos_is_too_far_from_larnaca(self):
        rates = m.parse_listing(fixture("es_mt_cy_cypr.html"))["rates"]
        self.assertEqual([r["code"] for r in rates if m.keep(r, CYPRUS, [], TODAY)], ["AMTSCY1YX8"])


class TestFetch(unittest.TestCase):
    def test_summer_offer_two_adults(self):
        s = FakeSession(ROUTES)
        hotels, offers = m.fetch(cfg([DORADA, MARESME, CYPRUS]), TODAY, session=s)
        self.assertEqual(s.misses, [])
        self.assertEqual(len(offers), 1)
        h, o = hotels[0], offers[0]
        self.assertEqual(h["id"], "itk-aesbcbch86")
        self.assertTrue(h["direct_flight_skp"])
        self.assertFalse(h["border"])
        self.assertEqual((h["country"], h["kind"], h["stars"]), ("ES", "hotel", 4))
        self.assertTrue(h["family"]["kids_animation"])
        self.assertIn("SKP→BCN", h["notes"])
        self.assertEqual((o["occupancy"], o["board"], o["nights"], o["check_in"]), ("2+0", "HB", 3, "2027-09-24"))
        self.assertEqual(o["price_eur"], round(1798 * 0.235, 2))
        self.assertIsNone(o["was_eur"])
        self.assertEqual(o["source"], "Itaka (hotel only)")
        self.assertEqual(validate.problems(o, TODAY, validate.limits(CFG), h), [])

    def test_family_price_when_page_has_the_twins(self):
        page = with_twins(fixture("es_mt_cy_costa_dorada.html"), "AESBCD5D3O")
        s = FakeSession([(ROUTES[0][0], page)])
        hotels, offers = m.fetch(cfg([DORADA], months=[]), TODAY, session=s)
        o = next(x for x in offers if x["hotel"] == "itk-aesbcd5d3o")
        self.assertEqual(o["occupancy"], "2+2")
        self.assertEqual(o["price_eur"], round((1678 + 419.5) * 0.235, 2))
        self.assertEqual(o["was_eur"], round((1678 + 839) * 0.235, 2))       # first child free
        self.assertEqual(o["discount_label"], "Itaka -17%")
        h = next(x for x in hotels if x["id"] == "itk-aesbcd5d3o")
        self.assertEqual(h["family"]["ratings"], [{"source": "Itaka", "score": 4.8, "scale": 6.0, "count": 24}])
        self.assertTrue(h["family"]["sand_beach"])
        others = [x for x in offers if x["hotel"] != "itk-aesbcd5d3o"]
        self.assertTrue(others and all(x["occupancy"] == "2+0" for x in others))

    def test_disabled_and_blocked(self):
        c = cfg([DORADA])
        c["sources"]["es_mt_cy"]["enabled"] = False
        self.assertEqual(m.fetch(c, TODAY, session=FakeSession(ROUTES)), ([], []))
        s = FakeSession([(r"costa-dorada", Blocked("403"))] + ROUTES)
        self.assertEqual(m.fetch(cfg([DORADA, MARESME]), TODAY, session=s), ([], []))  # stops at the block


if __name__ == "__main__":
    unittest.main()
