"""Pochivka.bg (bg_more) apartment price tables: parser tests on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import bg_more

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
PAGE = {"url": "https://pochivka.bg/apartamenti-bansko-t6", "season": "winter", "area": "Bansko, Bulgaria",
        "country": "BG", "lat": 41.83, "lng": 23.48, "nights": 5, "check_in": "2027-01-15"}


def read(name):
    return (FIX / f"bg_more_{name}.html").read_text(encoding="utf-8")


def listing(name):
    return bg_more.parse_listing(read(name))


def offer(name, oid="1", page=PAGE):
    return bg_more.to_hotel_and_offer(listing(name), oid, f"https://pochivka.bg/x-o{oid}", page, CFG, TODAY)


class ListPage(unittest.TestCase):
    def test_cards_and_places(self):
        cards = bg_more.parse_list(read("list_bansko"))
        self.assertEqual(len(cards), 10)
        by = {c["oid"]: c for c in cards}
        self.assertEqual(by["48410"]["url"], "https://pochivka.bg/apartament-glazne-bansko-o48410")
        self.assertEqual(by["48410"]["places"], 4)
        self.assertEqual(by["62800"]["places"], 5)
        self.assertEqual(by["57272"]["places"], 3)          # too small: fetch() skips it unopened
        self.assertIsNone(by["59046"]["places"])            # several unit types: must be opened

    def test_empty_page(self):
        self.assertEqual(bg_more.parse_list("<html></html>"), [])


class ListingPage(unittest.TestCase):
    def test_price_table(self):
        x = listing("do_gondola")
        self.assertEqual(x["name"], "Апартамент до Гондола")
        self.assertTrue(x["per_unit_night"])
        self.assertEqual(x["rows"], [{"type": "апартамент", "places": 4, "rates": {
            "high_summer": 46.02, "low_summer": 46.02, "high_winter": 56.24, "low_winter": 51.13, "other": None}}])
        self.assertAlmostEqual(x["lat"], 41.8340454)
        self.assertTrue(x["image"].startswith("https://static.pochivka.bg/bgstay.com/images/photos/49/49279/"))

    def test_bedroom_words(self):
        self.assertEqual(listing("do_gondola")["bedrooms"], 1)     # "В спалнята …"
        self.assertEqual(listing("glazne")["bedrooms"], 1)         # "обзаведена спалня с … двойно легло"
        self.assertEqual(listing("paskalina")["bedrooms"], 2)      # "с две спални", "от 2 спални"
        self.assertIsNone(listing("florimont")["bedrooms"])        # text never names a bedroom

    def test_double_bed_is_not_a_bedroom(self):
        html = read("do_gondola").replace("В спалнята има", "В хола има двойна спалня и")
        self.assertIsNone(bg_more.parse_listing(html)["bedrooms"])

    def test_two_room_flat_has_one_bedroom(self):
        html = read("florimont").replace("Апартаментите са 15 на брой", "Двустаен апартамент, 15 на брой")
        self.assertEqual(bg_more.parse_listing(html)["bedrooms"], 1)

    def test_lev_price_converted(self):
        self.assertEqual(bg_more._rate('<span class="value">130<span class="currency">лв</span></span>'), 66.47)
        self.assertIsNone(bg_more._rate("не се дава"))

    def test_gallery_photo_on_big_gallery(self):
        self.assertIn("/48/48410/orig_48410_1.jpg", listing("glazne")["image"])


class Offers(unittest.TestCase):
    def test_family_offer_from_high_winter_rate(self):
        hotel, off = offer("do_gondola", "49279")
        self.assertEqual(off["price_eur"], round(56.24 * 5, 2))
        self.assertEqual((off["occupancy"], off["board"], off["nights"], off["check_in"]), ("2+2", "SC", 5, "2027-01-15"))
        self.assertEqual(hotel["id"], "pv-49279")
        self.assertEqual(hotel["kind"], "apartment")
        self.assertTrue(hotel["family"]["separate_bedroom"])
        self.assertEqual(hotel["family"]["verified"], [])
        self.assertIn("Cots not mentioned", hotel["notes"])

    def test_only_rows_for_four(self):
        _, off = offer("marand")                             # studio for 2 ignored
        self.assertEqual((off["room"], off["price_eur"]), ("whole апартамент (sleeps 4)", 750))

    def test_apartment_preferred_over_cheaper_studio(self):
        x = listing("marand")
        x["rows"][0]["places"] = 4                           # studio for 4 at 80/night, apartment 150
        _, off = bg_more.to_hotel_and_offer(x, "1", "u", PAGE, CFG, TODAY)
        self.assertEqual(off["room"], "whole апартамент (sleeps 4)")

    def test_low_winter_fallback_and_missing_winter(self):
        x = listing("glazne")
        x["rows"][0]["rates"].update(high_winter=None, low_winter=50.0)
        _, off = bg_more.to_hotel_and_offer(x, "1", "u", PAGE, CFG, TODAY)
        self.assertEqual(off["price_eur"], 250)
        x["rows"][0]["rates"].update(low_winter=None)
        self.assertIsNone(bg_more.to_hotel_and_offer(x, "1", "u", PAGE, CFG, TODAY))

    def test_too_small_or_rooms_only(self):
        self.assertIsNone(offer("royal_park"))               # rooms for 2, apartment for 3

    def test_no_bedroom_stated_leaves_it_unknown(self):
        hotel, off = offer("florimont")
        self.assertNotIn("separate_bedroom", hotel["family"])
        self.assertEqual(off["price_eur"], round(148.27 * 5, 2))

    def test_per_person_table_is_skipped(self):
        x = listing("do_gondola")
        x["per_unit_night"] = False
        self.assertIsNone(bg_more.to_hotel_and_offer(x, "1", "u", PAGE, CFG, TODAY))

    def test_check_in_never_in_the_past(self):
        _, off = offer("do_gondola", page={**PAGE, "check_in": "2026-01-10"})
        self.assertEqual(off["check_in"], TODAY.isoformat())


class Fetch(unittest.TestCase):
    def test_fetch_with_saved_pages(self):
        pages = {
            "https://pochivka.bg/apartamenti-bansko-t6": read("list_bansko"),
            "https://pochivka.bg/apartament-glazne-bansko-o48410": read("glazne"),
            "https://pochivka.bg/marand-butik-apartamenti-o59046": read("marand"),
            "https://pochivka.bg/apartament-paskalina-blizo-do-lifta-o62800": read("paskalina"),
            "https://pochivka.bg/florimont-hayts-apartkompleks-o63098": read("florimont"),
        }

        class Fake:
            requested = []

            def get(self, url):
                self.requested.append(url)
                return pages.get(url, "")

        cfg = {**CFG, "sources": {**CFG["sources"], "bg_more": {
            "enabled": True, "list_pages": 2, "max_listings": 20, "pages": [PAGE]}}}
        s = Fake()
        hotels, offers = bg_more.fetch(cfg, TODAY, session=s)
        self.assertNotIn("https://pochivka.bg/apartament-v-kompleks-griyn-layf-o57272", s.requested)  # 3 places
        self.assertEqual({h["id"] for h in hotels}, {"pv-48410", "pv-59046", "pv-62800", "pv-63098"})
        self.assertTrue(all(o["occupancy"] == "2+2" and o["source"] == bg_more.SOURCE for o in offers))

    def test_disabled(self):
        self.assertEqual(bg_more.fetch({**CFG, "sources": {**CFG["sources"], "bg_more": {}}}, TODAY), ([], []))


if __name__ == "__main__":
    unittest.main()
