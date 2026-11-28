"""gr_family: proposed extra Grčka Info hotel pages for gr_hotel_prices (config-only change).

Checks, on pages saved 2026-11-28, that the existing gr_hotel_prices parser turns the proposed hotels
into real 2 adults + 2 kids stay totals, and that the site's own hotel filter on a region list finds
them. No network.
"""
import copy
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession
from trips import run
from trips.sources import gr_apartments as ga
from trips.sources import gr_hotel_prices as g

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 28)
BASE = "https://grckainfo.com/en/accommodation/"


def read(name):
    return (FIX / f"gr_family_{name}.html").read_text(encoding="utf-8")


def page(slug_id, **kw):
    return {"url": BASE + slug_id + "/", "season": "summer", "area": "X", "country": "GR", "lat": 0, "lng": 0,
            "nights": 7, "check_in": "2027-06-20", **kw}


def offers(name, slug_id, cfg=CFG):
    return g.hotel_offers(g.parse_page(read(name)), page(slug_id), cfg, TODAY)


class RegionList(unittest.TestCase):
    def test_hotel_filter_finds_new_hotels(self):
        cards = ga.parse_list(read("list_sithonia_hotels"))["cards"]
        ids = {c["id"] for c in cards}
        for pid in ("3751", "3651", "4802", "4155", "4140", "4244", "3252", "1932"):
            self.assertIn(pid, ids)
        self.assertIn("1395", ids)                    # Toroni Blue Sea: already configured
        golden = next(c for c in cards if c["id"] == "3751")
        self.assertEqual(golden["town"], "Metamorfosi")
        self.assertTrue(golden["url"].startswith("https://grckainfo.com/sr/smestaj/golden-beach-hotel/3751"))


class HalfBoardFamilyPrices(unittest.TestCase):
    def check(self, name, slug_id, price, board="HB"):
        hotel, offs = offers(name, slug_id)
        self.assertIsNotNone(hotel)
        best = offs[0]
        self.assertEqual(best["occupancy"], "2+2")
        self.assertEqual(best["board"], board)
        self.assertEqual(best["price_eur"], price)
        self.assertEqual(best["check_in"], "2027-06-20")
        self.assertEqual(best["nights"], 7)
        return hotel, offs

    def test_golden_beach_metamorfosi(self):
        hotel, offs = self.check("golden_beach", "golden-beach-hotel/3751", 1155.0)
        self.assertIn("2 adults + 2 children", offs[0]["room"])
        self.assertTrue(hotel["family"]["half_board"])
        self.assertTrue(hotel["family"]["playground"])
        self.assertTrue(hotel["family"]["cots_mentioned"])
        self.assertEqual(hotel["id"], "gih-3751")
        self.assertAlmostEqual(hotel["lat"], 40.228, places=2)

    def test_siokas_nei_pori(self):
        hotel, offs = self.check("siokas", "hotel-siokas/1501", 1008.0)
        self.assertIn("2 + 2 children", offs[0]["room"])
        self.assertTrue(hotel["family"]["half_board"])

    def test_esperia_thassos(self):
        hotel, _ = self.check("esperia", "hotel-esperia/1663", 1330.0)
        self.assertTrue(hotel["image"].startswith("https://"))

    def test_porto_matina_metamorfosi(self):
        hotel, _ = self.check("porto_matina", "porto-matina-hotel/3651", 917.0)
        self.assertTrue(hotel["family"].get("beachfront"))

    def test_saint_george_bb_only(self):
        self.check("saint_george", "saint-george-hotel/3457", 1050.0, board="BB")


class ParserGaps(unittest.TestCase):
    """What gr_hotel_prices does not read yet on the proposed pages (see proposals/gr_family.md)."""

    def test_akti_belvedere_notes(self):
        self.assertIn("Half board - 35€/per day, children 0-12 years - 25 €/per day",
                      " ".join(g.parse_page(read("akti_belvedere"))["notes"].split()))

    def test_akti_belvedere_hb_supplement(self):
        # 'Half board - 35€/per day, children 0-12 years - 25 €/per day' -> 1120 + (2×35 + 2×25) × 7
        _, offs = offers("akti_belvedere", "akti-belvedere-color-and-essence/2920")
        self.assertEqual((offs[0]["board"], offs[0]["price_eur"]), ("HB", 1960.0))


class ProposedConfig(unittest.TestCase):
    def test_fetch_with_proposed_pages(self):
        s = FakeSession([(r"/golden-beach-hotel/3751/", "gr_family_golden_beach.html"),
                         (r"/hotel-siokas/1501/", "gr_family_siokas.html"),
                         (r"/hotel-esperia/1663/", "gr_family_esperia.html"),
                         (r"/porto-matina-hotel/3651/", "gr_family_porto_matina.html")])
        c = copy.deepcopy(CFG)
        c["sources"]["gr_hotel_prices"] = {
            "enabled": True, "season": "summer", "country": "GR", "nights": 7, "check_in": "2027-06-20",
            "max_rooms": 3, "pages": [
                {"url": BASE + "golden-beach-hotel/3751/", "area": "Metamorfosi, Sithonia, Halkidiki",
                 "lat": 40.228, "lng": 23.605},
                {"url": BASE + "hotel-siokas/1501/", "area": "Nei Pori, Olympic Riviera", "lat": 39.978, "lng": 22.651},
                {"url": BASE + "hotel-esperia/1663/", "area": "Pefkari, Thassos", "lat": 40.618, "lng": 24.597},
                {"url": BASE + "porto-matina-hotel/3651/", "area": "Metamorfosi, Sithonia, Halkidiki",
                 "lat": 40.228, "lng": 23.606}]}
        hotels, offs = g.fetch(c, TODAY, session=s)
        self.assertEqual([h["id"] for h in hotels], ["gih-3751", "gih-1501", "gih-1663", "gih-3651"])
        self.assertTrue(all(o["occupancy"] == "2+2" for o in offs))
        self.assertTrue(all(o["board"] == "HB" for o in offs))
        self.assertEqual(s.misses, [])


if __name__ == "__main__":
    unittest.main()
