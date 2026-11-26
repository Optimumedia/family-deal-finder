"""Clickstay villas/apartments (trips.sources.rentals): parser tests on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import rentals

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
CFG["sources"].setdefault("rentals", {"enabled": True, "gbp_to_eur": 1.17})
TODAY = date(2026, 11, 25)
PAGE = {"url": "https://www.clickstay.com/greece/chalkidiki", "season": "summer", "area": "Halkidiki (villa)",
        "country": "GR", "lat": 40.1, "lng": 23.6, "nights": 7, "check_in": "2027-06-20"}


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="ignore")


class Clickstay(unittest.TestCase):
    def setUp(self):
        self.region = rentals.parse_region(read("rentals_clickstay_chalkidiki.html"))

    def test_region_cards(self):
        self.assertEqual(len(self.region), 16)
        lev = next(v for v in self.region if v["id"] == "439052")
        self.assertEqual(lev["name"], "Villa Levrecchio")
        self.assertEqual((lev["bedrooms"], lev["sleeps"], lev["week_gbp"]), (2, 4, 1522.0))
        self.assertEqual(lev["town"], "Sithonia")
        self.assertEqual(lev["url"], "https://www.clickstay.com/p/439052")
        self.assertTrue(lev["image"].startswith("https://") and "cloudfront.net" in lev["image"])

    def test_beach_distance_from_summary(self):
        v = next(v for v in self.region if v["id"] == "396954")
        self.assertEqual(v["beach_m"], 300)
        apt = rentals.parse_region(read("rentals_clickstay_nikiti.html"))[0]
        self.assertEqual((apt["kind"], apt["bedrooms"], apt["beach_m"]), ("apartment", 2, 50))

    def test_offer_shape(self):
        v = next(v for v in self.region if v["id"] == "439052")
        hotel, offer = rentals.to_hotel_and_offer(v, PAGE, CFG, TODAY)
        self.assertEqual(hotel["id"], "cs-439052")
        self.assertEqual(hotel["kind"], "villa")
        self.assertEqual(hotel["area"], "Sithonia, Halkidiki (villa)")
        self.assertTrue(hotel["family"]["separate_bedroom"])
        self.assertEqual(offer["board"], "SC")
        self.assertEqual(offer["occupancy"], "2+2")
        self.assertEqual(offer["nights"], 7)
        self.assertAlmostEqual(offer["price_eur"], 1522 * 1.17, places=1)
        self.assertEqual(offer["check_in"], "2027-06-20")
        for k in ("hotel", "source", "url", "seen", "room", "was_eur", "discount_label", "valid_until"):
            self.assertIn(k, offer)

    def test_generic_town_keeps_page_area(self):
        v = next(v for v in self.region if v["id"] == "176627")      # alt: "Villa in Greece, Chalkidiki"
        hotel, _ = rentals.to_hotel_and_offer(v, PAGE, CFG, TODAY)
        self.assertEqual(hotel["area"], "Halkidiki (villa)")

    def test_too_small_is_skipped(self):
        v = {**self.region[0], "sleeps": 3}
        self.assertIsNone(rentals.to_hotel_and_offer(v, PAGE, CFG, TODAY))

    def test_disabled_fetch_makes_no_requests(self):
        cfg = {**CFG, "sources": {**CFG["sources"], "rentals": {"enabled": False}}}
        self.assertEqual(rentals.fetch(cfg, TODAY), ([], []))


if __name__ == "__main__":
    unittest.main()
