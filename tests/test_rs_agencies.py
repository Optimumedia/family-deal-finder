"""ArgusTours price-list parser tests against saved pages (argus.rs, 26.11.2026). No network."""
import re
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.http import Blocked
from trips.sources import rs_agencies as ra

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
PAGE = {"url": "https://argus.rs/aranzmani/letovanje/grcka/kasandra-sopstveni-prevoz-2027", "season": "summer",
        "area": "Kassandra, Halkidiki", "country": "GR", "lat": 40.0, "lng": 23.43}


def cfg(**src):
    c = dict(CFG)
    c["sources"] = {**CFG["sources"], "rs_agencies": {"enabled": True, "pages": [PAGE], **src}}
    return c


class FakeSession:
    def __init__(self, pages=None, block=False):
        self.pages, self.block, self.urls = pages or {}, block, []

    def get(self, url):
        self.urls.append(url)
        if self.block:
            raise Blocked("403 bot challenge")
        return next((v for k, v in self.pages.items() if k in url), "")


class Argus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kas = (FIX / "rs_agencies_argus_kassandra.html").read_text(encoding="utf-8")
        cls.thassos = (FIX / "rs_agencies_argus_thassos.html").read_text(encoding="utf-8")
        cls.empty = (FIX / "rs_agencies_argus_empty.html").read_text(encoding="utf-8")

    def test_parse_every_bookable_price(self):
        rows = ra.parse_page(self.kas)
        bookable = re.findall(r'<td[^>]*class="[^"]*capacity-(?:has|little)[^"]*"[^>]*><a ', self.kas)
        self.assertEqual(len(rows), len(bookable))
        self.assertEqual(len(rows), 427)
        self.assertEqual({r["nights"] for r in rows}, {10})
        self.assertEqual({r["per"] for r in rows}, {"unit"})
        self.assertEqual({r["board"] for r in rows}, {"SC"})
        self.assertEqual(len({r["object_url"] for r in rows}), 5)

    def test_known_prices(self):
        rows = ra.parse_page(self.kas)
        a4 = [r for r in rows if r["object_name"].startswith("Grigoriou") and r["unit"] == "A4"]
        by_date = {r["check_in"]: r["price"] for r in a4}
        self.assertEqual(by_date["2027-05-22"], 285)
        self.assertEqual((by_date["2027-06-01"], by_date["2027-06-11"], by_date["2027-06-21"]), (349, 505, 625))
        self.assertEqual(a4[0]["object_url"],
                         "https://argus.rs/aranzmani/letovanje/grcka/kasandra-sopstveni-prevoz-2027/grigoriou-polihrono")

    def test_sold_out_cells_skipped(self):
        # 28 capacity-no cells on the Kassandra page; none of them may become a price
        self.assertEqual(len(re.findall(r'run-active capacity-no"', self.kas)), 28)
        total_cells = len(re.findall(r'class="fw-medium text-center run-active', self.kas))
        self.assertEqual(len(ra.parse_page(self.kas)), total_cells - 28)

    def test_unit_codes(self):
        self.assertEqual([ra.beds(u) for u in ("A4 PR", "S2+2 VP", "Mazoneta (2+1)", "S3 NP", "S2 tip A", "Studio")],
                         [4, 4, 3, 3, 2, None])
        self.assertEqual([ra.unit_kind(u) for u in ("A4 VP", "S4", "S2 Mezoneta", "Mazoneta (2+1)")],
                         ["apartment", "studio", "studio", "maisonette"])
        self.assertEqual(ra.split_name("Hotel Petridis 3* - Pefkohori"), ("Petridis", "Pefkohori", 3))
        self.assertEqual(ra.split_name("Grigoriou - Polihrono"), ("Grigoriou", "Polihrono", None))

    def test_family_offers_only_for_four_bed_units(self):
        hotels, offers = ra.best_offers(ra.parse_page(self.kas), PAGE,
                                        cfg(check_in_from="2027-06-01", check_in_to="2027-09-15"), TODAY)
        self.assertEqual(sorted(h["name"] for h in hotels), ["Grigoriou", "Nikos"])   # others top out at 3 beds
        self.assertEqual(len(offers), 20)
        self.assertTrue(all(o["occupancy"] == "2+2" and o["board"] == "SC" and o["nights"] == 10 for o in offers))
        self.assertTrue(all("2027-06-01" <= o["check_in"] <= "2027-09-15" for o in offers))
        first = next(o for o in offers if o["hotel"] == "ag-grigoriou-polihrono" and o["check_in"] == "2027-06-01")
        self.assertEqual(first["price_eur"], 349.0)
        self.assertIn("sleeps 4", first["room"])
        h = next(h for h in hotels if h["id"] == "ag-grigoriou-polihrono")
        self.assertEqual((h["kind"], h["area"], h["country"], h["direct_flight_skp"]),
                         ("apartment", "Kassandra, Halkidiki", "GR", False))
        self.assertIn("Polihrono", h["notes"])

    def test_one_offer_per_object_and_window(self):
        _, offers = ra.best_offers(ra.parse_page(self.kas), PAGE, cfg(), TODAY)
        keys = [(o["hotel"], o["check_in"]) for o in offers]
        self.assertEqual(len(keys), len(set(keys)))
        # Grigoriou has A4, A4 PR and A4 VP at the same price: one offer, the cheapest
        g = [o for o in offers if o["hotel"] == "ag-grigoriou-polihrono" and o["check_in"] == "2027-07-01"]
        self.assertEqual(len(g), 1)

    def test_past_windows_dropped(self):
        _, offers = ra.best_offers(ra.parse_page(self.kas), PAGE, cfg(), date(2027, 8, 1))
        self.assertTrue(offers)
        self.assertTrue(all(o["check_in"] >= "2027-08-01" for o in offers))

    def test_thassos_s2_plus_2_and_s4(self):
        hotels, offers = ra.best_offers(ra.parse_page(self.thassos), PAGE,
                                        cfg(check_in_from="2027-06-01", check_in_to="2027-09-15"), TODAY)
        self.assertEqual(len(hotels), 5)
        self.assertEqual(len(offers), 48)
        self.assertTrue(any(o["room"].startswith("S4 ") for o in offers))

    def test_per_person_price_is_two_adults(self):
        html = ('<div class="tab-pane fade" id="x_07-2027-pane"><table><thead><tr><th colspan="2"></th>'
                '<th class="fw-medium text-center">01.07.<br>08.07.</th></tr></thead><tbody>'
                '<tr><th colspan="4"><h3><a href="/aranzmani/letovanje/grcka/x/hotel-sun-3">Hotel Sun 3* - Hanioti</a>'
                '</h3></th></tr><tr><th></th><th class="fw-medium" colspan="3">DBL (PP)</th></tr>'
                '<tr><td></td><td></td><td>PO OSOBI</td><td class="fw-medium text-center run-active capacity-has">'
                '<a href="/partner/booking/go?x=1">420</a></td></tr></tbody></table></div>')
        hotels, offers = ra.best_offers(ra.parse_page(html), PAGE, cfg(), TODAY)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual((o["occupancy"], o["board"], o["nights"], o["price_eur"], o["check_in"]),
                         ("2+0", "HB", 7, 840.0, "2027-07-01"))
        self.assertEqual((hotels[0]["name"], hotels[0]["stars"], hotels[0]["kind"]), ("Sun", 3, "hotel"))

    def test_empty_page(self):
        self.assertEqual(ra.parse_page(self.empty), [])

    def test_fetch(self):
        s = FakeSession({"kasandra-sopstveni-prevoz-2027": self.kas})
        hotels, offers = ra.fetch(cfg(check_in_from="2027-06-01", check_in_to="2027-09-15"), TODAY, s)
        self.assertEqual(s.urls, [PAGE["url"]])
        self.assertEqual((len(hotels), len(offers)), (2, 20))
        self.assertEqual({o["source"] for o in offers}, {"ArgusTours"})

    def test_disabled_and_blocked(self):
        c = cfg()
        c["sources"]["rs_agencies"]["enabled"] = False
        self.assertEqual(ra.fetch(c, TODAY, FakeSession()), ([], []))
        two = cfg()
        two["sources"]["rs_agencies"]["pages"] = [PAGE, {**PAGE, "url": PAGE["url"] + "-2"}]
        s = FakeSession(block=True)
        self.assertEqual(ra.fetch(two, TODAY, s), ([], []))
        self.assertEqual(len(s.urls), 1)                       # stops at the first block


if __name__ == "__main__":
    unittest.main()
