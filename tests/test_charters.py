"""Savana Travel (charters) parser tests against listing pages saved 25.11.2026. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import charters as ch

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)
PAGE = {"url": "x", "season": "summer", "area": "Antalya region, Turkey", "region": "Antalya region, Turkey",
        "country": "TR", "lat": 36.88, "lng": 30.70, "nights": 7, "check_in": "2027-06-20"}


def html(name):
    return (FIX / name).read_text(encoding="utf-8")


class Charters(unittest.TestCase):
    def test_antalya_cards(self):
        cards = ch.parse_list(html("charters_antalya.html"))
        self.assertEqual(len(cards), 20)
        c = cards[0]
        self.assertEqual((c["slug"], c["name"], c["stars"], c["town"]),
                         ("gold-stone-3-stars-kemer-turkey", "HOTEL GOLD STONE", 3, "Kemer"))
        self.assertEqual((c["price"], c["old"], c["nights"], c["adults"]), (812.0, 1014.59, 6, 2))
        self.assertEqual(c["stays"], [(6, 812.0), (7, 857.0)])
        self.assertEqual(c["image"], "https://etrip.savana.com.mk/file.php?file=20473")
        self.assertTrue(c["url"].startswith("https://www.online.savana.travel/vacations/gold-stone-"))

    def test_page_two_fragment_and_paging(self):
        first = html("charters_antalya.html")
        self.assertEqual(ch.next_pages(first),
                         ["https://www.online.savana.travel/vacations/turkey/antalya/from-skopje/vacations/with-plane/2/"])
        p2 = ch.parse_list(html("charters_antalya_p2.html"))
        self.assertEqual([c["slug"] for c in p2], ["mesut-4-stars-alanya-turkey", "ada-beach-kleopatra-4-stars-alanya-turkey"])
        self.assertIn("mesut-4-stars-alanya-turkey", ch.pins(first))     # page 1's map covers page 2's hotels

    def test_pins_and_departures(self):
        page = html("charters_antalya.html")
        self.assertEqual(ch.pins(page)["gold-stone-3-stars-kemer-turkey"], (36.7328585, 30.55902456))
        deps = ch.departures(page)
        self.assertEqual((deps[0], deps[-1]), ("2027-06-02", "2027-09-07"))

    def test_hotel_and_offer(self):
        page = html("charters_antalya.html")
        c = ch.parse_list(page)[0]
        h, o = ch.to_hotel_and_offer(c, PAGE, CFG, TODAY, ch.pins(page)[c["slug"]], ch.departures(page)[0])
        self.assertEqual((h["id"], h["name"], h["area"]), ("sv-gold-stone-3-stars-kemer-turkey", "Gold Stone",
                                                          "Kemer, Antalya region, Turkey"))
        self.assertEqual((h["direct_flight_skp"], h["border"], h["lat"]), (True, False, 36.7328585))
        self.assertEqual((o["price_eur"], o["was_eur"], o["nights"], o["occupancy"], o["board"]),
                         (812.0, 1014.59, 6, "2+0", "?"))
        self.assertEqual((o["check_in"], o["discount_label"]), ("2027-06-20", "Savana -20%"))

    def test_first_departure_wins_when_later(self):
        c = ch.parse_list(html("charters_antalya.html"))[0]
        _, o = ch.to_hotel_and_offer(c, dict(PAGE, check_in="2027-05-01"), CFG, TODAY, None, "2027-06-02")
        self.assertEqual(o["check_in"], "2027-06-02")

    def test_kusadasi_no_discount_and_ip_photo_dropped(self):
        cards = ch.parse_list(html("charters_kusadasi.html"))
        t = cards[0]
        self.assertEqual((t["name"], t["price"], t["old"], t["nights"]), ("TECIMEN HOTEL", 620.0, None, 7))
        self.assertIsNone(t["image"])                                     # bare IP:port file server
        _, o = ch.to_hotel_and_offer(t, PAGE, CFG, TODAY)
        self.assertIsNone(o["discount_label"])
        self.assertEqual(ch.departures(html("charters_kusadasi.html"))[0], "2027-04-02")

    def test_clean_name(self):
        self.assertEqual(ch._clean_name("RAMIRA BEACH HOTEL( EX.SUN MARITIM HOTEL)"), "Ramira Beach")
        self.assertEqual(ch._clean_name("Leda Beach Hotel"), "Leda Beach")

    def test_fetch_dedupes_and_follows_pages(self):
        pages = {"A": html("charters_antalya.html"),
                 "https://www.online.savana.travel/vacations/turkey/antalya/from-skopje/vacations/with-plane/2/":
                     html("charters_antalya_p2.html")}

        class Fake:
            def get(self, url):
                return pages[url]

        cfg = dict(CFG, sources=dict(CFG["sources"], charters={"enabled": True, "max_list_pages": 3,
                                                               "pages": [dict(PAGE, url="A")]}))
        hotels, offers = ch.fetch(cfg, TODAY, Fake())
        self.assertEqual(len(hotels), 22)
        self.assertEqual(len({h["id"] for h in hotels}), 22)
        mesut = next(h for h in hotels if h["id"] == "sv-mesut-4-stars-alanya-turkey")
        self.assertNotEqual((mesut["lat"], mesut["lng"]), (PAGE["lat"], PAGE["lng"]))


if __name__ == "__main__":
    unittest.main()
