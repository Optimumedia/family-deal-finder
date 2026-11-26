"""AtlantiS (atlantis.mk) parser tests against saved result pages (Bansko, Borovets, 25.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from trips.sources import mk_agencies as mk

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 25)
BANSKO_URL = "https://www.atlantis.mk/hotels/bansko?PartialGuid=1f54d4c1-4682-415e-a6b3-854b99efbc22"
BOROVETS_URL = "https://atlantisonline.mk/hotels/borovets?PartialGuid=cf76af02-5ce1-415f-a46a-3fb269306d0b"
PAGE = {"url": BANSKO_URL, "season": "winter", "area": "Bansko, Bulgaria", "country": "BG", "lat": 41.83,
        "lng": 23.48, "nights": 4, "check_in": "2027-01-15"}


def read(name):
    return (FIX / f"mk_agencies_{name}.html").read_text(encoding="utf-8")


class FakeSession:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return self.pages.get(url, "")


class Atlantis(unittest.TestCase):
    def setUp(self):
        self.bansko = mk.parse_results(read("atlantis_bansko"), BANSKO_URL)
        self.by_code = {c["code"]: c for c in self.bansko}

    def test_parse_cards(self):
        self.assertEqual(len(self.bansko), 9)
        c = self.by_code["CASKARMVO3"]
        self.assertEqual((c["name"], c["town"], c["nights"], c["adults"], c["children"]),
                         ("CASA KARINA", "Bansko", 4, 2, 0))
        self.assertEqual((c["head"]["room"], c["head"]["board"], c["head"]["price"]), ("Dbl Standard", "HB", 550.0))
        self.assertEqual({r["room"]: r["price"] for r in c["rooms"]},
                         {"Stu Studio Lux": 638.0, "Apt 1 Bedroom Lux Appart": 770.0, "Dbl Standard": 550.0,
                          "Apt 1 Bedroom Appart": 594.0})
        self.assertEqual(c["hotel_url"], "https://www.atlantis.mk/hotel/casa-karina")
        self.assertEqual(c["image"], "https://cdn.atlantis.mk/hotelphotos/casa-karina-genel-002.jpg")

    def test_early_booking_and_thousands(self):
        c = self.by_code["GRAHOTP5WQ"]
        self.assertEqual((c["stars"], c["pct"], c["early_booking"]), (5, 15, True))
        self.assertEqual((c["head"]["price"], c["head"]["old"]), (741.2, 872.0))   # data-price is unrounded
        exe = next(r for r in c["rooms"] if r["room"] == "Executive Room")
        self.assertEqual((exe["price"], exe["old"], exe["board"]), (925.0, 1088.0, "HB"))

    def test_board_codes(self):
        self.assertEqual([mk.board_code(x) for x in ("Hb", "Half Board plus", "Bb", "Bed and Breakfast", "Fb",
                                                      "All Inclusive", "Ultra All Inclusive", "THERME PRIVILEGE", "")],
                         ["HB", "HB", "BB", "BB", "FB", "AI", "AI", "?", "?"])

    def test_winter_picks_cheapest_room_with_a_bedroom(self):
        h, o = mk.to_hotel_and_offer(self.by_code["CASKARMVO3"], PAGE, TODAY)
        self.assertEqual((o["price_eur"], o["board"], o["nights"], o["occupancy"]), (594.0, "HB", 4, "2+0"))
        self.assertTrue(o["room"].startswith("Apt 1 Bedroom Appart"))
        self.assertEqual((h["kind"], h["family"]), ("apartment", {"verified": [], "separate_bedroom": True}))
        self.assertEqual((h["id"], h["name"], o["url"], o["check_in"]),
                         ("atl-caskarmvo3", "Casa Karina", BANSKO_URL, "2027-01-15"))

    def test_no_bedroom_room_keeps_fact_unknown(self):
        h, o = mk.to_hotel_and_offer(self.by_code["BOJUR9XNG"], PAGE, TODAY)
        self.assertEqual((o["room"].split(" (")[0], o["price_eur"], h["kind"]), ("Dbl Standard", 361.0, "hotel"))
        self.assertNotIn("separate_bedroom", h["family"])

    def test_discount_label_and_was_price(self):
        h, o = mk.to_hotel_and_offer(self.by_code["GRAHOTP5WQ"], PAGE, TODAY)
        self.assertEqual((o["room"].split(" (")[0], o["price_eur"], o["was_eur"]), ("One Bedroom Apartment", 1115.0, 1312.0))
        self.assertEqual(o["discount_label"], "Early booking -15%")
        h, o = mk.to_hotel_and_offer(self.by_code["CASKARMVO3"], PAGE, TODAY)
        self.assertIsNone(o["was_eur"])
        self.assertIsNone(o["discount_label"])

    def test_summer_prefers_dinner_board(self):
        h, o = mk.to_hotel_and_offer(self.by_code["CASKARMVO3"], {**PAGE, "season": "summer"}, TODAY)
        self.assertEqual((o["board"], o["price_eur"]), ("HB", 550.0))

    def test_checkin_never_in_past(self):
        _, o = mk.to_hotel_and_offer(self.by_code["CASKARMVO3"], {**PAGE, "check_in": "2026-01-01"}, TODAY)
        self.assertEqual(o["check_in"], "2026-11-25")

    def test_menu_links(self):
        links = mk.menu_links(read("atlantis_home_menu"))
        self.assertEqual(links["bansko"], BANSKO_URL)
        self.assertEqual(links["borovets"], BOROVETS_URL)
        self.assertIn("pamporovo", links)

    def _cfg(self, pages):
        return {"sources": {"delay_seconds": 0, "jitter_seconds": 0, "timeout_seconds": 1,
                            "mk_agencies": {"enabled": True, "pages": pages}}}

    def test_fetch_two_pages(self):
        bor = {**PAGE, "url": BOROVETS_URL, "area": "Borovets, Bulgaria"}
        s = FakeSession({BANSKO_URL: read("atlantis_bansko"), BOROVETS_URL: read("atlantis_borovets")})
        hotels, offers = mk.fetch(self._cfg([PAGE, bor]), TODAY, session=s)
        self.assertEqual((len(hotels), len(offers)), (15, 15))
        self.assertEqual(s.urls, [BANSKO_URL, BOROVETS_URL])
        self.assertTrue(all(o["source"] == mk.SOURCE and o["price_eur"] > 0 for o in offers))

    def test_fetch_follows_refreshed_menu_link_and_dedupes(self):
        stale = "https://www.atlantis.mk/hotels/bansko?PartialGuid=old"
        s = FakeSession({stale: "<html>no results</html>", mk.HOME: read("atlantis_home_menu"),
                         BANSKO_URL: read("atlantis_bansko")})
        hotels, offers = mk.fetch(self._cfg([{**PAGE, "url": stale}, PAGE]), TODAY, session=s)
        self.assertEqual(s.urls[:3], [stale, mk.HOME, BANSKO_URL])
        self.assertEqual(len(offers), 9)                       # second page lists the same hotels: skipped
        self.assertTrue(all(o["url"] == BANSKO_URL for o in offers))

    def test_disabled(self):
        self.assertEqual(mk.fetch({"sources": {}}, TODAY, session=FakeSession({})), ([], []))


if __name__ == "__main__":
    unittest.main()
