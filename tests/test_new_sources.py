"""Hotel websites, villa rentals (Oliver's Travels), owner rentals (Micazu): parsers on saved pages. No network."""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import db, run, score
from trips.sources import hotel_direct, micazu, oliverstravels, pagetext

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
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
        self.assertEqual(len(v), 9)                      # incl. "2-6 guests" resort villas
        tharo = next(x for x in v if x["name"] == "Villa Tharo")
        self.assertEqual((tharo["guests"], tharo["bedrooms"], tharo["low_gbp"], tharo["pct"]), (8, 4, 3862, 15))
        self.assertTrue(tharo["url"].endswith("/greece/halkidiki/villa-tharo/"))
        self.assertEqual(tharo["image"], "https://pms-images.oliverstravels.com/dwellings/19148/main/6835d509c8c94.jpg?profile=sm")
        # villa-* cards carry a slider photo; the Eagles Resort cards link elsewhere and may have none
        self.assertTrue(all(x["image"] and x["image"].startswith("https://pms-images.oliverstravels.com/")
                            for x in v if x["slug"].startswith("villa-")))
        self.assertTrue(all(x["image"] is None or x["image"].startswith("https://") for x in v))

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
        self.assertIsNone(lst["image"])                               # micazu's image host blocks hotlinks

    def test_offer_uses_period_covering_check_in(self):
        lst = micazu.parse_listing(read("micazu_listing_bansko.html"))
        h, o = micazu.to_hotel_and_offer(lst, "51700", "u", self.PAGE, CFG, TODAY)
        self.assertEqual(o["price_eur"], 75 * 5 + 30)                 # 5 nights + final cleaning
        self.assertNotIn("cots_max", h["family"])                      # 1 cot mentioned ≠ "no": stays unknown
        self.assertIn("ask for a second", h["notes"])
        jan = {**self.PAGE, "check_in": "2027-01-15"}                  # no 2027 rates entered yet → skipped
        self.assertIsNone(micazu.to_hotel_and_offer(lst, "51700", "u", jan, CFG, TODAY))


class HotelDirectLanguagesAndFilters(unittest.TestCase):
    def camps(self, html, **kw):
        return hotel_direct.campaigns(f"<html><body>{html}</body></html>", TODAY, **kw)

    def test_bulgarian_greek_serbian_wording(self):
        bg = self.camps("<p>Ранно записване – 15% отстъпка до 15.12.2026</p>")
        self.assertEqual([(c["pct"], c["valid_until"], c["kind"]) for c in bg], [(15, "2026-12-15", "campaign")])
        gr = self.camps("<p>Έκπτωση 20% για κρατήσεις έως 31/12/2026</p>")
        self.assertEqual([(c["pct"], c["valid_until"]) for c in gr], [(20, "2026-12-31")])
        sr = self.camps("<p>Popust 10% za rani buking</p><p>Попуст 12% за рано резервисање</p>")
        self.assertEqual(sorted(c["pct"] for c in sr), [10, 12])
        self.assertEqual(self.camps("<p>Our rooms are 35% bigger.</p>"), [])          # no offer word

    def test_loyalty_skipped_or_tagged(self):
        portes = "<p>We thank the guests who visit us often, and we offer 5% discount on accommodation.</p>"
        self.assertEqual(self.camps(portes), [])
        self.assertEqual([c["kind"] for c in self.camps(portes, include_loyalty=True)], ["loyalty"])
        secret = ("<p>This Black Friday, enjoy 30% off your stay, plus an additional 5% discount for members "
                  "at Secret Paradise Hotel &amp; Spa.</p>")
        self.assertEqual([(c["pct"], c["kind"]) for c in self.camps(secret)], [(30, "campaign")])
        both = self.camps(secret, include_loyalty=True)
        self.assertEqual(sorted((c["pct"], c["kind"]) for c in both), [(5, "loyalty"), (30, "campaign")])
        self.assertEqual(self.camps("<p>Отстъпка 10% за постоянни клиенти</p>"), [])
        self.assertEqual(self.camps("<p>Save 10%</p>", page_kind="loyalty"), [])     # members-club page

    def test_porto_carras_loyalty_heading(self):
        c = hotel_direct.campaigns(read("direct_portocarras_offers.html"), TODAY)
        self.assertEqual([x["pct"] for x in c], [40])                  # "Direct Booking & Loyalty Benefits" 15%
        c = hotel_direct.campaigns(read("direct_portocarras_offers.html"), TODAY, include_loyalty=True)
        self.assertEqual([(x["pct"], x["kind"]) for x in c], [(40, "campaign"), (15, "loyalty")])

    def test_deposit_tax_and_extras_dropped_but_clause_kept(self):
        royal = ("<p>EB -10% - 10% for accommodation in the period 03.01.2027 - 06.03.2027 , for reservations "
                 "made before 30.11.2026 , 30% payment in advance.</p>")
        self.assertEqual([c["pct"] for c in self.camps(royal)], [10])
        self.assertEqual(self.camps("<p>Early booking offer: 30% deposit required.</p>"), [])
        self.assertEqual(self.camps("<p>Ранни записвания: 20% депозит</p>"), [])
        self.assertEqual(self.camps("<p>• 50% popusta na spa tretmane</p>"), [])
        self.assertEqual(self.camps("<p>Book 60 days in advance and save 15%</p>")[0]["pct"], 15)

    def test_near_identical_campaigns_kept_once(self):
        pirin = ("<p>Winter 2026/27 early booking: −10% until November 30 See offers</p>"
                 "<p>Winter 2026/27 early booking (−10%) ends November 30.</p>")
        self.assertEqual(len(self.camps(pirin)), 1)
        royal = "<h3>EB -10%</h3><p>EB -10% - 10% for accommodation in the period 03.01.2027 - 06.03.2027</p>"
        c = self.camps(royal)
        self.assertEqual(len(c), 1)
        self.assertIn("03.01.2027", c[0]["title"])                     # the fuller text is kept
        two = "<p>Early booking save 10% on rooms.</p><p>Black Friday: 30% off everything.</p>"
        self.assertEqual(sorted(x["pct"] for x in self.camps(two)), [10, 30])

    def test_shared_url_fetched_once(self):
        class S:
            def __init__(self):
                self.urls = []

            def get(self, url):
                self.urls.append(url)
                return "<p>Black Friday – до 50% отстъпка</p>"
        pages = [{"hotel": h, "url": "https://mpmhotels.bg/offers/"} for h in ("a", "b", "c")]
        pages.append({"hotel": "d", "url": "https://x.gr/offers/members-club"})
        cfg = {**CFG, "sources": {**CFG["sources"], "hotel_direct": {"enabled": True, "pages": pages}}}
        s = S()
        found = hotel_direct.fetch(cfg, TODAY, session=s)
        self.assertEqual(s.urls, ["https://mpmhotels.bg/offers/", "https://x.gr/offers/members-club"])
        self.assertEqual(sorted(c["hotel"] for c in found), ["a", "b", "c"])  # members-club page = loyalty
        cfg["sources"]["hotel_direct"]["include_loyalty"] = True
        found = hotel_direct.fetch(cfg, TODAY, session=S())
        self.assertEqual({c["hotel"]: c["kind"] for c in found}["d"], "loyalty")


if __name__ == "__main__":
    unittest.main()
