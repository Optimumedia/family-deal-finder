"""Grčka Info (grckainfo.com) per-unit price lists: parsers on saved pages. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run, validate
from trips.sources import gr_apartments as g

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
PAGE = {"url": "https://grckainfo.com/sr/smestaji/halkidiki-sitonija/210/?udaljenost%5B0%5D=1", "season": "summer",
        "area": "Sithonia, Halkidiki", "country": "GR", "lat": 40.10, "lng": 23.80, "nights": 7,
        "check_in": "2027-06-20", "beach_filter_m": 200}


def read(name):
    return (FIX / f"gr_apartments_{name}.html").read_text(encoding="utf-8")


def card(pid, town, url="https://grckainfo.com/sr/smestaj/x/1/"):
    return {"id": pid, "url": url, "town": town, "name": "", "capacity": 4, "discount": False}


class ListPage(unittest.TestCase):
    def test_cards(self):
        lst = g.parse_list(read("list_sithonia"))
        self.assertEqual(len(lst["cards"]), 12)
        self.assertEqual(lst["last_page"], 37)
        first = lst["cards"][0]
        self.assertEqual((first["id"], first["name"], first["town"], first["region"], first["capacity"]),
                         ("1917", "Likno Apartments", "Neos Marmaras", "Sitonija", 5))
        self.assertEqual(first["url"], "https://grckainfo.com/sr/smestaj/likno-apartments/1917/")
        self.assertIn("Villa Maria Apartments & Studios", [c["name"] for c in lst["cards"]])
        self.assertIsNone(next(c for c in lst["cards"] if c["id"] == "1605")["capacity"])   # no capacity chip
        par = g.parse_list(read("list_paralia"))
        self.assertTrue(par["cards"])
        self.assertEqual({c["town"] for c in par["cards"]}, {"Paralija"})
        self.assertEqual(par["last_page"], 1)

    def test_page_url(self):
        self.assertEqual(g.page_url(PAGE["url"], 1), PAGE["url"])
        self.assertEqual(g.page_url(PAGE["url"], 3),
                         "https://grckainfo.com/sr/smestaji/halkidiki-sitonija/210/3/?udaljenost%5B0%5D=1")
        self.assertEqual(g.page_url("https://grckainfo.com/sr/smestaji/paralia/333/", 2),
                         "https://grckainfo.com/sr/smestaji/paralia/333/2/")


class PropertyPage(unittest.TestCase):
    def test_rate_table(self):
        p = g.parse_property(read("mare_doro"))
        self.assertEqual(p["name"], "Mare D’Oro Studios")
        self.assertEqual((p["lat"], p["lng"]), (40.089231, 23.977609))
        self.assertTrue(p["image"].startswith("https://grckainfo.com/uploads/"))
        self.assertEqual(p["basis"], "unit")                          # "po smeštajnoj jedinici/dnevno"
        self.assertEqual([(u["name"], u["adults"], u["kids"]) for u in p["units"]],
                         [("Studio", 2, 2), ("Studio", 3, 0), ("Studio", 2, 0)])
        r = p["units"][0]["rates"]
        self.assertEqual(len(r), 6)
        self.assertEqual(r[0], {"from": "2027-05-01", "to": "2027-06-20", "night": 90.0, "was": None})
        self.assertEqual(r[3]["night"], 140.0)
        self.assertIn("Kuhinja", p["amenities"])

    def test_beach_facts(self):
        likno = g.parse_property(read("likno"))
        self.assertEqual(likno["beach"]["beach_m"], 30)               # "na plaži Paradisos na udaljenosti od samo 30m"
        self.assertTrue(likno["beach"]["beachfront"])
        rodia = g.parse_property(read("rodia"))
        self.assertEqual(rodia["beach"]["beach_m"], 290)              # "290 metara od plaže"
        self.assertNotIn("beachfront", rodia["beach"])
        self.assertTrue(rodia["special_offer"])
        mare = g.parse_property(read("mare_doro"))
        self.assertNotIn("beach_m", mare["beach"])                    # "dva minuta od plaže": no number
        self.assertEqual(mare["town_beach"].get("beach_type"), "sand")

    def test_variant_choice(self):
        units = g.parse_property(read("likno"))["units"]
        chosen = g.pick_family_variants(units, 2, 2)
        self.assertEqual(len(chosen), 1)                              # one unit type, four occupancy variants
        self.assertEqual((chosen[0]["adults"], chosen[0]["kids"]), (4, 0))   # the 4-bed price, not the 5-bed one
        self.assertEqual(g.unit_type(chosen[0]["name"]), "Apartman 40m² - 2 sobe")
        mare = g.pick_family_variants(g.parse_property(read("mare_doro"))["units"], 2, 2)
        self.assertEqual([(u["adults"], u["kids"]) for u in mare], [(2, 2)])

    def test_stay_price_crosses_periods(self):
        rates = g.parse_property(read("mare_doro"))["units"][0]["rates"]
        # 2 nights at 90 (to 20.06) + 5 nights at 100
        self.assertEqual(g.stay_price(rates, date(2027, 6, 19), 7), (680.0, None))
        self.assertIsNone(g.stay_price(rates, date(2027, 9, 28), 7))  # runs past the last published night


class Offers(unittest.TestCase):
    def test_family_offer(self):
        h, offers = g.property_offers(card("2505", "Sarti"), g.parse_property(read("mare_doro")), PAGE, CFG, TODAY)
        self.assertEqual(h["id"], "gi-2505")
        self.assertEqual(h["area"], "Sarti, Sithonia, Halkidiki")
        self.assertEqual((h["kind"], h["country"], h["direct_flight_skp"], h["border"]), ("apartment", "GR", False, True))
        self.assertIs(h["family"]["separate_bedroom"], False)          # studio
        self.assertTrue(h["family"]["family_room"])
        self.assertIs(h["family"]["sand_beach"], True)                 # from the town paragraph, noted
        self.assertIn("not this house", h["notes"])
        self.assertEqual(h["family"]["beach_max_m"], 200)
        self.assertEqual(len(offers), 1)
        o = offers[0]
        self.assertEqual((o["check_in"], o["nights"], o["board"], o["occupancy"]), ("2027-06-20", 7, "SC", "2+2"))
        self.assertEqual(o["price_eur"], 690.0)                        # 90 + 6 × 100
        self.assertEqual(validate.problems(o, TODAY, validate.limits(CFG), h), [])

    def test_two_room_apartment(self):
        h, offers = g.property_offers(card("1917", "Neos Marmaras"), g.parse_property(read("likno")), PAGE, CFG, TODAY)
        self.assertIs(h["family"]["separate_bedroom"], True)           # "2 sobe"
        self.assertEqual(h["family"]["beach_m"], 30)
        self.assertNotIn("beach_max_m", h["family"])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price_eur"], 525.0)                # 60 + 6 × 75
        self.assertEqual(offers[0]["room"], "Apartman 40m² - 2 sobe (whole unit, priced for 4 adults; sleeps 4)")

    def test_check_in_list_and_past(self):
        page = {**PAGE, "check_ins": ["2026-07-01", "2027-07-05", "2027-08-10"]}
        _, offers = g.property_offers(card("5677", "Nikiti"), g.parse_property(read("rodia")), page, CFG, TODAY)
        self.assertEqual([(o["check_in"], o["price_eur"]) for o in offers],
                         [("2027-07-05", 665.0), ("2027-08-10", 665.0)])

    def test_half_board_hotel(self):
        page = {**PAGE, "url": "https://grckainfo.com/sr/smestaji/nei-pori/337/", "area": "Nei Pori, Olympic Riviera"}
        h, offers = g.property_offers(card("1501", "Nei Pori"), g.parse_property(read("siokas")), page, CFG, TODAY)
        self.assertEqual(h["kind"], "hotel")
        self.assertEqual(h["area"], "Nei Pori, Olympic Riviera")
        self.assertTrue(offers)
        self.assertEqual({o["board"] for o in offers}, {"HB"})        # "Soba - 2 + 2 deteta HB"
        kids_room = next(o for o in offers if "2 + 2" in o["room"])
        self.assertIn("priced for 2 adults + 2 kids", kids_room["room"])

    def test_unit_board_and_area_spelling(self):
        self.assertEqual(g.unit_board("Standard soba 28m² - BB"), "BB")
        self.assertEqual(g.unit_board("Soba - 4 osobe HB"), "HB")
        self.assertIsNone(g.unit_board("HBO apartman"))
        page = {**PAGE, "area": "Paralia, Olympic Riviera"}
        h, _ = g.property_offers(card("2505", "Paralija"), g.parse_property(read("mare_doro")), page, CFG, TODAY)
        self.assertEqual(h["area"], "Paralia, Olympic Riviera")       # Serbian spelling not repeated

    def test_two_family_unit_left_out(self):
        _, offers = g.property_offers(card("1616", "Asprovalta"), g.parse_property(read("petalo")), PAGE, CFG, TODAY)
        self.assertTrue(offers)
        self.assertFalse([o for o in offers if "2 porodice" in o["room"]])   # 9-guest unit, over max_unit_guests

    def test_per_person_page_skipped(self):
        prop = g.parse_property(read("mare_doro"))
        prop["basis"] = "person"
        self.assertEqual(g.property_offers(card("2505", "Sarti"), prop, PAGE, CFG, TODAY), (None, []))

    def test_disabled(self):
        cfg = {**CFG, "sources": {**CFG["sources"], "gr_apartments": {"enabled": False}}}
        self.assertEqual(g.fetch(cfg, TODAY, session=object()), ([], []))


class FakeSession:
    def __init__(self, pages):
        self.pages, self.asked = pages, []

    def get(self, url):
        self.asked.append(url)
        return self.pages.get(url, "")


class Fetch(unittest.TestCase):
    def test_fetch_filters_cards(self):
        lst = read("list_sithonia")
        s = FakeSession({PAGE["url"]: lst,
                         "https://grckainfo.com/sr/smestaj/likno-apartments/1917/": read("likno")})
        cfg = {**CFG, "sources": {**CFG["sources"], "gr_apartments": {
            "enabled": True, "max_list_pages": 1, "pages": [{**PAGE, "towns": ["Neos Marmaras"], "max_properties": 1}]}}}
        hotels, offers = g.fetch(cfg, TODAY, session=s)
        self.assertEqual(s.asked, [PAGE["url"], "https://grckainfo.com/sr/smestaj/likno-apartments/1917/"])
        self.assertEqual([h["id"] for h in hotels], ["gi-1917"])
        self.assertEqual(hotels[0]["area"], "Neos Marmaras, Sithonia, Halkidiki")
        self.assertEqual(len(offers), 1)


if __name__ == "__main__":
    unittest.main()
