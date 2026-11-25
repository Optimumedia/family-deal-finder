"""Hotel websites, villa rentals (Oliver's Travels), owner rentals (Micazu): parsers on saved pages. No network."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import db, run, score
from trips.sources import hotel_direct, micazu, oliverstravels, pagetext

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml")
TODAY = date(2026, 11, 25)


def read(name):
    return (FIX / name).read_text(encoding="utf-8", errors="ignore")


class PageText(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(pagetext.find_date("book before December 1st", TODAY), "2026-12-01")
        self.assertEqual(pagetext.find_date("Stay by Dec 23", TODAY), "2026-12-23")
        self.assertEqual(pagetext.find_date("until 31.01.2027", TODAY), "2027-01-31")
        self.assertEqual(pagetext.find_date("from 15 March", TODAY), "2027-03-15")     # next occurrence
        self.assertIsNone(pagetext.find_date("no date here", TODAY))

    def test_money(self):
        self.assertEqual(pagetext.money("2,768"), 2768)
        self.assertEqual(pagetext.money("75.00"), 75)
        self.assertEqual(pagetext.money("1.205"), 1205)


class HotelDirect(unittest.TestCase):
    def test_porto_carras_black_friday(self):
        c = hotel_direct.campaigns(read("direct_portocarras_offers.html"), TODAY)
        bf = next(x for x in c if x["pct"] == 40)
        self.assertIn("Black Friday", bf["title"])

    def test_sani_early_booking_deadline(self):
        c = hotel_direct.campaigns(read("direct_sani_offers.html"), TODAY)
        self.assertTrue(any(x["pct"] == 10 and "Early Booking" in x["title"] for x in c))
        self.assertTrue(any(x["valid_until"] == "2026-12-01" for x in c))

    def test_st_ivan_rilski(self):
        c = hotel_direct.campaigns(read("direct_stivanrilski_offers.html"), TODAY)
        self.assertEqual(sorted(x["pct"] for x in c)[-1], 30)

    def test_campaign_stored_once(self):
        with tempfile.TemporaryDirectory() as d:
            con = db.connect(Path(d) / "t.db")
            c = {"hotel": "h", "source": "Hotel website", "url": "u", "title": "Black Friday | Save 40%", "pct": 40,
                 "seen": "2026-11-25"}
            self.assertTrue(db.add_campaign(con, c))
            self.assertFalse(db.add_campaign(con, {**c, "seen": "2026-11-26"}))
            self.assertEqual(db.campaigns(con, "2026-11-26")["h"][0]["last_seen"], "2026-11-26")
            con.close()


class Villas(unittest.TestCase):
    PAGE = {"url": "u", "season": "summer", "area": "Halkidiki (villa)", "lat": 40.1, "lng": 23.6, "nights": 7,
            "check_in": "2027-06-20"}

    def test_region_cards(self):
        v = oliverstravels.parse_region(read("oliver_halkidiki.html"))
        self.assertEqual(len(v), 5)
        tharo = next(x for x in v if x["name"] == "Villa Tharo")
        self.assertEqual((tharo["guests"], tharo["bedrooms"], tharo["low_gbp"], tharo["pct"]), (8, 4, 3862, 15))
        self.assertTrue(tharo["url"].endswith("/greece/halkidiki/villa-tharo/"))

    def test_villa_offer_is_whole_family_self_catering(self):
        v = next(x for x in oliverstravels.parse_region(read("oliver_halkidiki.html")) if x["name"] == "Villa Brosia")
        h, o = oliverstravels.to_hotel_and_offer(v, self.PAGE, CFG, TODAY)
        self.assertEqual((h["kind"], o["board"], o["occupancy"]), ("villa", "SC", "2+2"))
        self.assertAlmostEqual(o["price_eur"], 2768 * 1.17, places=0)

    def test_self_catering_capped_not_excluded_in_summer(self):
        v = next(x for x in oliverstravels.parse_region(read("oliver_halkidiki.html")) if x["name"] == "Villa Brosia")
        h, o = oliverstravels.to_hotel_and_offer(v, self.PAGE, CFG, TODAY)
        h["family"].update(sand_beach=True, beach_m=50)
        offer = {**o, "key": "k", "history": [{"seen": o["seen"], "price_eur": o["price_eur"]}]}
        r = score.rate(h, offer, [offer], CFG, 200, TODAY)
        self.assertFalse(r["excluded"])
        self.assertIn("Self-catering — no breakfast/dinner", r["family"]["unknown_musts"])


class OwnerRentals(unittest.TestCase):
    PAGE = {"url": "u", "season": "winter", "area": "Bansko, Bulgaria", "lat": 41.83, "lng": 23.48, "nights": 5,
            "check_in": "2026-12-14"}

    def test_list_and_listing(self):
        links = micazu.listing_links(read("micazu_list_bansko.html"))
        self.assertEqual(links[0][1], "51700")
        lst = micazu.parse_listing(read("micazu_listing_bansko.html"))
        self.assertEqual((lst["name"], lst["max_persons"], lst["bedrooms"]), ("Comfortable Ski Retreat", 5, 1))
        self.assertEqual(lst["periods"][0], {"from": "2025-12-30", "to": "2026-12-31", "night": 75.0, "week": 525.0})
        self.assertTrue(lst["cot"] and lst["high_chair"])

    def test_offer_uses_period_covering_check_in(self):
        lst = micazu.parse_listing(read("micazu_listing_bansko.html"))
        h, o = micazu.to_hotel_and_offer(lst, "51700", "u", self.PAGE, CFG, TODAY)
        self.assertEqual(o["price_eur"], 75 * 5 + 30)                 # 5 nights + final cleaning
        self.assertEqual(h["family"]["cots_max"], 1)
        jan = {**self.PAGE, "check_in": "2027-01-15"}                  # no 2027 rates entered yet → skipped
        self.assertIsNone(micazu.to_hotel_and_offer(lst, "51700", "u", jan, CFG, TODAY))


if __name__ == "__main__":
    unittest.main()
