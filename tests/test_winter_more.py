"""Halo Oglasi owner ads (Kopaonik, Stara Planina): parsers on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run, validate
from trips.sources import winter_more as wm

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 28)
KOP = {"url": "https://www.halooglasi.com/odmor/planine/kopaonik", "place": "kopaonik", "season": "winter",
       "area": "Kopaonik, Serbia", "country": "RS", "lat": 43.285, "lng": 20.81, "nights": 5,
       "check_in": "2027-01-16"}
SP = {**KOP, "url": "https://www.halooglasi.com/odmor/planine/stara-planina", "place": "stara planina",
      "area": "Stara Planina, Serbia", "lat": 43.373, "lng": 22.606, "list_pages": 1}


def read(name):
    return (FIX / f"winter_more_{name}.html").read_text(encoding="utf-8")


def card(price=None, aid="1"):
    return {"id": aid, "url": f"https://www.halooglasi.com/odmor/planine/x/{aid}", "title": "t",
            "place": "kopaonik", "price_night": price, "text": ""}


def build(name, page=KOP, price=None):
    return wm.to_hotel_and_offer(card(price), wm.parse_listing(read(name)), page, CFG, TODAY)


class ListPage(unittest.TestCase):
    def test_kopaonik_cards(self):
        cards, total = wm.parse_list(read("list_kopaonik"))
        self.assertEqual(total, 5)
        self.assertEqual(len(cards), 20)
        self.assertEqual(sum(c["price_night"] is not None for c in cards), 11)   # the rest say "Dogovor"
        self.assertTrue(all(c["place"] == "kopaonik" for c in cards))
        bed = next(c for c in cards if c["id"] == "5425643961373")
        self.assertEqual(bed["price_night"], 40.0)
        self.assertEqual(bed["url"], "https://www.halooglasi.com/odmor/planine/kopaonik-apartman-sa-odvojenom-spavacom-sobom/5425643961373")
        self.assertNotIn("?", bed["url"])

    def test_thousands_badge(self):
        cards, _ = wm.parse_list(read("list_kopaonik"))
        self.assertEqual(next(c for c in cards if c["id"] == "5425647448668")["price_night"], 2200.0)

    def test_wanted_skips_on_request_and_other_places(self):
        self.assertFalse(wm._wanted(card(None), KOP))
        self.assertTrue(wm._wanted(card(40.0), KOP))
        self.assertFalse(wm._wanted(card(40.0), SP))

    def test_stara_planina(self):
        cards, total = wm.parse_list(read("list_stara_planina"))
        self.assertEqual((total, len(cards)), (1, 1))
        self.assertEqual(cards[0]["place"], "stara planina")


class Listing(unittest.TestCase):
    def test_structured_fields(self):
        i = wm.parse_listing(read("kop_bedroom"))
        self.assertEqual((i["type"], i["capacity"], i["price_night"]), ("Apartman", 4, 40.0))
        self.assertTrue(i["separate_bedroom"])
        self.assertFalse(i["per_person"])
        self.assertTrue(i["image"].startswith("https://img.halooglasi.com/slike/oglasi/Thumbs/"))
        self.assertIn("/l/", i["image"])               # large photo; robots.txt asks bots to skip /m/ and /s/ thumbs
        self.assertIsNone(i["lat"])                    # no map pin → the page's resort point is used
        self.assertEqual(build("kop_bedroom")[0]["lat"], KOP["lat"])
        pin = wm.parse_listing(read("zl_leonardo_cot"))
        self.assertEqual((pin["lat"], pin["lng"]), (43.730796, 19.698159))

    def test_studio_and_tourist_tax_is_not_per_person(self):
        i = wm.parse_listing(read("kop_studio_ema"))
        self.assertIs(i["separate_bedroom"], False)
        self.assertFalse(i["per_person"])              # "boravišna taksa … 100 din. Po osobi dnevno"

    def test_cot_mentioned(self):
        i = wm.parse_listing(read("zl_leonardo_cot"))
        self.assertTrue(i["cots_mentioned"])           # "Moguć krevetac na zahtev"
        self.assertTrue(i["separate_bedroom"])
        self.assertTrue(i["on_request"])
        self.assertIsNone(i["price_night"])

    def test_per_person_wording(self):
        self.assertTrue(wm._per_person("Cena je 15 € po osobi za noćenje."))
        self.assertFalse(wm._per_person("Boravišna taksa 100 din po osobi dnevno."))

    def test_kind(self):
        self.assertEqual(wm._kind("Kuća za odmor"), "villa")
        self.assertEqual(wm._kind("Hotel"), "hotel")
        self.assertEqual(wm._kind("Apartman"), "apartment")

    def test_no_ad_data(self):
        with self.assertRaises(ValueError):
            wm.parse_listing("<html></html>")


class Offers(unittest.TestCase):
    def test_whole_unit_is_family_price(self):
        h, o = build("kop_bedroom")
        self.assertEqual(o["occupancy"], "2+2")
        self.assertEqual(o["price_eur"], 200.0)        # 40 €/night × 5
        self.assertEqual((o["check_in"], o["nights"], o["board"]), ("2027-01-16", 5, "SC"))
        self.assertEqual(h["id"], "ho-5425643961373")
        self.assertTrue(h["family"]["separate_bedroom"])
        self.assertEqual(h["kind"], "apartment")
        self.assertTrue(h["border"])
        self.assertFalse(h["direct_flight_skp"])
        self.assertEqual(validate.problems(o, TODAY, None, h), [])

    def test_studio_kept_but_no_bedroom(self):
        h, o = build("kop_studio_ema")
        self.assertIs(h["family"]["separate_bedroom"], False)
        self.assertEqual(o["price_eur"], 150.0)

    def test_timeshare_price_ignored(self):
        self.assertIsNone(build("kop_timeshare"))

    def test_no_price_no_offer(self):
        self.assertIsNone(build("zl_leonardo_cot"))

    def test_cot_fact_carried(self):
        h, o = build("zl_leonardo_cot", price=50.0)     # e.g. if the card had a price
        self.assertTrue(h["family"]["cots_mentioned"])
        self.assertIn("Cot mentioned", h["notes"])

    def test_house_stara_planina(self):
        h, o = build("sp_wild", page=SP)
        self.assertEqual(h["kind"], "villa")
        self.assertEqual(h["area"], "Stara Planina, Serbia")
        self.assertEqual(o["price_eur"], 200.0)

    def test_unknown_bedroom_note(self):
        h, _ = build("kop_zoned")
        self.assertIsNone(h["family"]["separate_bedroom"])
        self.assertIn("Ask whether the bedroom is separate", h["notes"])

    def test_capacity_limits(self):
        info = wm.parse_listing(read("kop_bedroom"))
        self.assertIsNone(wm.to_hotel_and_offer(card(), {**info, "capacity": 3}, KOP, CFG, TODAY))
        self.assertIsNone(wm.to_hotel_and_offer(card(), {**info, "capacity": 12}, KOP, CFG, TODAY))

    def test_per_person_is_two_adults(self):
        info = {**wm.parse_listing(read("kop_bedroom")), "per_person": True}
        _, o = wm.to_hotel_and_offer(card(), info, KOP, CFG, TODAY)
        self.assertEqual((o["occupancy"], o["price_eur"]), ("2+0", 400.0))

    def test_last_minute_label(self):
        info = {**wm.parse_listing(read("kop_bedroom")), "last_minute": True}
        _, o = wm.to_hotel_and_offer(card(), info, KOP, CFG, TODAY)
        self.assertEqual(o["discount_label"], "Last minute (owner's ad)")
        self.assertIsNone(o["was_eur"])


class Fetch(unittest.TestCase):
    def test_disabled(self):
        self.assertEqual(wm.fetch({**CFG, "sources": {**CFG["sources"], "winter_more": {}}}, TODAY), ([], []))

    def test_fetch_with_saved_pages(self):
        pages = {KOP["url"]: "list_kopaonik", SP["url"]: "list_stara_planina",
                 "https://www.halooglasi.com/odmor/planine/kopaonik-apartman-sa-odvojenom-spavacom-sobom/5425643961373": "kop_bedroom",
                 "https://www.halooglasi.com/odmor/planine/wild---stara-planina/5425647913171": "sp_wild"}
        asked = []

        class Fake:
            def get(self, url):
                asked.append(url)
                return read(pages[url]) if url in pages else ""

        cfg = {**CFG, "sources": {**CFG["sources"], "winter_more": {
            "enabled": True, "list_pages": 1, "max_listings": 12, "pages": [KOP, SP]}}}
        hotels, offers = wm.fetch(cfg, TODAY, Fake())
        self.assertEqual({o["hotel"] for o in offers}, {"ho-5425643961373", "ho-5425647913171"})
        self.assertEqual(len(hotels), 2)
        self.assertEqual(sum(1 for u in asked if "/odmor/planine/kopaonik" == u[len("https://www.halooglasi.com"):]), 1)
        self.assertEqual(len(asked), 2 + 11 + 1)       # 2 lists, 11 priced Kopaonik ads, 1 Stara Planina ad


if __name__ == "__main__":
    unittest.main()
