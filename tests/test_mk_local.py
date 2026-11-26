"""Kajak.mk (Macedonian accommodation portal) for Mavrovo, Popova Šapka, Kruševo, Pelister, Ohrid,
Struga, Dojran: parsers on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run, score
from trips.sources import mk_local

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
WINTER = {"url": "https://kajak.mk/smestuvanja/b588801e-mavrovski-region", "location": "Mavrovo",
          "season": "winter", "area": "Mavrovo, North Macedonia", "country": "MK", "lat": 41.66, "lng": 20.74,
          "nights": 5, "check_in": "2027-01-16"}
SUMMER = {**WINTER, "season": "summer", "area": "Ohrid, North Macedonia", "location": "Ohrid", "nights": 7,
          "check_in": "2027-07-03"}


def read(name):
    return (FIX / f"mk_local_{name}.html").read_text(encoding="utf-8")


def listing(name):
    return mk_local.parse_listing(read(name))


def card(url="https://kajak.mk/smestuvanje/test-unit", price=None):
    return {"url": url, "title": "test", "location": "Mavrovo", "price_mkd": price, "closed": False, "image": None}


def build(name, page=WINTER, today=TODAY):
    return mk_local.to_hotel_and_offer(card(), listing(name), page, CFG, today)


class Money(unittest.TestCase):
    def test_mkd(self):
        self.assertEqual(mk_local.mkd("3,075.00"), 3075)
        self.assertEqual(mk_local.mkd("2.200.00"), 2200)
        self.assertEqual(mk_local.mkd("6.159"), 6159)
        self.assertEqual(mk_local.mkd("800.00"), 800)


class RegionList(unittest.TestCase):
    def test_cards_and_pages(self):
        cards, pages = mk_local.parse_list(read("list_mavrovo"))
        self.assertEqual(pages, 7)
        self.assertEqual(len(cards), 21)
        self.assertEqual(cards[0]["location"], "Gevgelija")            # promoted card from another region
        c = next(c for c in cards if "Комплекс Резиденс" in c["title"])
        self.assertEqual((c["location"], c["price_mkd"]), ("Mavrovo", 3075))
        self.assertTrue(c["url"].startswith("https://kajak.mk/smestuvanje/"))
        self.assertTrue(c["image"].startswith("https://cdn.kajak.mk/"))

    def test_location_filter_drops_promoted_cards(self):
        cards, _ = mk_local.parse_list(read("list_mavrovo"))
        kept = [c for c in cards if mk_local._wanted(c, WINTER)]
        self.assertEqual(len(kept), 20)
        self.assertTrue(all(c["location"] == "Mavrovo" for c in kept))

    def test_title_match_picks_pelister_in_bitola_region(self):
        cards, pages = mk_local.parse_list(read("list_bitola"))
        page = {**WINTER, "location": "Bitola", "title_match": "Пелистер|Нижеполе|Трново|Магарево"}
        kept = [c["title"] for c in cards if mk_local._wanted(c, page)]
        self.assertEqual(pages, 4)
        self.assertEqual(len(kept), 11)
        self.assertFalse(any("строгиот центар на Битола" in t for t in kept))

    def test_closed_badge_skipped(self):
        c = {**card(), "closed": True}
        self.assertFalse(mk_local._wanted(c, WINTER))


class Listing(unittest.TestCase):
    def test_whole_unit_two_bedrooms(self):
        i = listing("mavrovo_mia")
        self.assertEqual((i["entire"], i["capacity"], i["price_mkd"]), (True, 4, 6150))
        self.assertIs(i["separate_bedroom"], True)                     # "две спални соби"
        self.assertEqual(i["range_mkd"], (6159, 12318))
        self.assertEqual(i["board"], "SC")                             # food not included

    def test_price_for_four_people(self):
        i = listing("dojran_4")
        self.assertEqual(i["per_n"], {2: 1800, 3: 2460, 4: 2200})

    def test_per_person(self):
        i = listing("mavrovo_residence")
        self.assertTrue(i["per_person"])
        self.assertEqual(i["capacity"], 7)

    def test_english_page_and_min_stay(self):
        i = listing("ohrid_family_en")
        self.assertEqual((i["entire"], i["capacity"], i["min_nights"]), (True, 4, 3))
        self.assertIs(i["separate_bedroom"], True)                     # "separate bedroom"

    def test_studio_and_hotel(self):
        self.assertIs(listing("ohrid_studios")["separate_bedroom"], False)
        bora = listing("popova_bora")
        self.assertEqual((bora["kind"], bora["board"]), ("hotel", "BB"))
        self.assertEqual(bora["per_n"], {2: 4500, 3: 6200})

    def test_unknown_bedroom_stays_unknown(self):
        self.assertIsNone(listing("mavrovo_lakeview4")["separate_bedroom"])


class Offers(unittest.TestCase):
    def test_price_for_four_is_2p2(self):
        h, o = build("dojran_4", SUMMER)
        self.assertEqual((o["occupancy"], o["nights"], o["check_in"], o["board"]), ("2+2", 7, "2027-07-03", "SC"))
        self.assertEqual(o["price_eur"], round(2200 * 7 / 61.5, 2))
        self.assertEqual((h["country"], h["border"], h["direct_flight_skp"]), ("MK", False, False))
        self.assertTrue(h["id"].startswith("kj-"))

    def test_whole_unit_is_2p2(self):
        h, o = build("mavrovo_mia")
        self.assertEqual((o["occupancy"], o["nights"]), ("2+2", 5))
        self.assertEqual(o["price_eur"], round(6150 * 5 / 61.5, 2))
        self.assertEqual((h["kind"], h["season"]), ("apartment", "winter"))
        self.assertIs(h["family"]["separate_bedroom"], True)
        self.assertIn("6,159–12,318", h["notes"])

    def test_per_person_is_two_adults_2p0(self):
        _, o = build("mavrovo_residence")
        self.assertEqual(o["occupancy"], "2+0")
        self.assertEqual(o["price_eur"], round(3075 * 2 * 5 / 61.5, 2))

    def test_for_two_is_2p0(self):
        _, o = build("pelister_green")
        self.assertEqual((o["occupancy"], o["price_eur"]), ("2+0", round(3000 * 5 / 61.5, 2)))
        _, o = build("popova_bora")
        self.assertEqual((o["occupancy"], o["board"]), ("2+0", "BB"))

    def test_min_stay_lengthens_short_stay(self):
        _, o = build("ohrid_family_en", {**WINTER, "nights": 2})
        self.assertEqual(o["nights"], 3)

    def test_too_small_is_skipped(self):
        self.assertIsNone(build("struga_family", SUMMER))              # max 2 guests

    def test_party_villa_skipped(self):
        i = {**listing("mavrovo_mia"), "capacity": 12, "kind": "villa"}
        self.assertIsNone(mk_local.to_hotel_and_offer(card(), i, WINTER, CFG, TODAY))

    def test_check_in_never_in_the_past(self):
        _, o = build("dojran_4", SUMMER, today=date(2027, 7, 10))
        self.assertEqual(o["check_in"], "2027-07-10")

    def test_scores_separate_bedroom(self):
        h, o = build("ohrid_studios", WINTER)
        fit = score.family_fit(h, o, CFG, 180)
        self.assertEqual(next(c for c in fit["checklist"] if c["key"] == "separate_bedroom")["state"], "no")


class Fetch(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(mk_local.fetch({**CFG, "sources": {**CFG["sources"], "mk_local": {}}}, TODAY), ([], []))

    def test_fetch_with_fake_session(self):
        pages = {WINTER["url"]: read("list_mavrovo")}
        mia = "https://kajak.mk/smestuvanje/6c9243b4-nov-i-moderen-apartman-vo-mavrovo-so-dve-spali-sobi-mia"
        pages[mia] = read("mavrovo_mia")

        class Fake:
            calls = []

            def get(self, url):
                self.calls.append(url)
                return pages.get(url, "")

        cfg = {**CFG, "sources": {**CFG["sources"], "mk_local": {
            "enabled": True, "max_list_pages": 1, "max_listings": 20, "pages": [WINTER]}}}
        s = Fake()
        hotels, offers = mk_local.fetch(cfg, TODAY, session=s)
        self.assertEqual(len(s.calls), 21)                              # 1 list + 20 listings
        self.assertEqual([o["url"] for o in offers], [mia])            # other listings came back empty
        self.assertEqual(hotels[0]["id"], "kj-" + mia.rsplit("/", 1)[-1][:60])


class English(unittest.TestCase):
    """The English edition (sent when the session asks for "en"): 'mkd' prices, EUR per-guest lines."""

    def test_english_list(self):
        cards, pages = mk_local.parse_list(read("list_dojran_en"))
        self.assertEqual(len(cards), 19)
        self.assertEqual(sum(c["location"] == "Dojran" for c in cards), 18)
        self.assertEqual(cards[1]["price_mkd"], 2400)

    def test_eur_per_guests_is_2p2(self):
        i = listing("dojran_4_en")
        self.assertEqual(i["per_n_eur"], {2: 29, 3: 40, 4: 36})
        self.assertEqual((i["entire"], i["capacity"], i["price_mkd"]), (True, 4, 1800))
        _, o = mk_local.to_hotel_and_offer(card(), i, SUMMER, CFG, TODAY)
        self.assertEqual((o["occupancy"], o["price_eur"]), ("2+2", 36 * 7))


if __name__ == "__main__":
    unittest.main()
