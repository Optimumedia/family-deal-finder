"""Vlero.com (Albanian coast) parser tests against pages saved 26.11.2026. No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import al_me_coast as v
from trips.http import Blocked

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 26)
GOLEM = {"url": "x", "season": "summer", "area": "Durrës / Golem, Albania", "country": "AL", "lat": 41.245,
         "lng": 19.523, "nights": 7, "check_in": "2027-06-20", "zones": ["Golem", "Shkembi Kavajes"]}


def load(name):
    return v.parse_list((FIX / f"al_me_coast_{name}.html").read_text(encoding="utf-8"))


class Parse(unittest.TestCase):
    def test_golem_card_fields(self):
        cards = load("golem")
        self.assertEqual(len(cards), 40)
        c = next(c for c in cards if c["room_id"] == "2479")
        self.assertEqual((c["property_id"], c["type"], c["city"], c["zone"], c["stars"]),
                         ("906", "hotel", "Durres", "Golem", 3))
        self.assertEqual((c["room"], c["price"], c["currency"], c["unit"]), ("Dhome Premium", 165.0, "EUR", "1 Nate"))
        self.assertEqual((c["adults"], c["kids"], c["beach_m"], c["size_m2"]), (2, 0, 140, 34))
        self.assertIn("Mengjesi", c["included"])
        self.assertTrue(c["image"].startswith("https://www.vlero.com/upload/member/"))
        self.assertEqual(c["url"], "https://www.vlero.com/hotelet-shqiptare/l-al-c-26-h-906-r-2479.html")

    def test_kids_capacity_read(self):
        caps = {(c["adults"], c["kids"]) for c in load("golem")}
        self.assertIn((2, 2), caps)
        self.assertIn((4, 2), caps)

    def test_zone_filter_drops_featured_rooms_elsewhere(self):
        cards = load("golem")
        kept = v.pick(cards, GOLEM)
        self.assertEqual(len(kept), 30)
        self.assertTrue(all(c["zone"] in ("Golem", "Shkembi Kavajes") for c in kept))
        self.assertEqual(len(v.pick(load("shengjin"), {"zones": ["Shengjin"]})), 34)
        self.assertEqual(len(v.pick(load("velipoje"), {"zones": ["Velipoje"]})), 27)
        self.assertEqual(len(v.pick(load("lalzi"), {"zones": ["Gjiri i Lalzit"]})), 10)

    def test_lek_prices_skipped_unless_rate_given(self):
        lek = next(c for c in load("shengjin") if c["price"] == 14300)   # "14,300 Leke" (meta says EUR)
        self.assertEqual(lek["currency"], "ALL")
        lek = dict(lek, adults=2, kids=2)
        self.assertIsNone(v.to_hotel_and_offer(lek, GOLEM, CFG, TODAY))
        _, o = v.to_hotel_and_offer(lek, GOLEM, CFG, TODAY, {"all_per_eur": 100})
        self.assertAlmostEqual(o["price_eur"], round(lek["price"] / 100 * 7, 2))


class Convert(unittest.TestCase):
    def test_family_apartment_offer(self):
        c = next(c for c in load("golem") if c["room_id"] == "2479")
        self.assertIsNone(v.to_hotel_and_offer(c, GOLEM, CFG, TODAY))     # sleeps 2+0 only: dropped
        fam = next(c for c in load("golem") if c["zone"] == "Golem" and (c["adults"], c["kids"]) == (2, 2)
                   and c["currency"] == "EUR")
        h, o = v.to_hotel_and_offer(fam, GOLEM, CFG, TODAY)
        self.assertEqual(h["id"], f"vl-{fam['property_id']}")
        self.assertEqual((h["country"], h["season"], h["border"], h["direct_flight_skp"]), ("AL", "summer", True, False))
        self.assertTrue(h["family"]["family_room"])
        self.assertEqual(h["family"]["beach_m"], fam["beach_m"])
        self.assertEqual((o["occupancy"], o["nights"], o["check_in"]), ("2+2", 7, "2027-06-20"))
        self.assertEqual(o["price_eur"], round(fam["price"] * 7, 2))
        self.assertIn("dates on request", o["room"])
        self.assertIsNone(o["was_eur"])

    def test_board_codes(self):
        self.assertEqual(v.board_code(["Internet Wi-Fi", "Mengjesi"]), "BB")
        self.assertEqual(v.board_code(["Kuzhine Private/Mundesi Gatimi"]), "SC")
        self.assertEqual(v.board_code(["Mengjesi dhe darke"]), "HB")
        self.assertEqual(v.board_code([]), "RO")

    def test_separate_bedroom(self):
        self.assertTrue(v.separate_bedroom("2 dhoma + sallon Standard"))
        self.assertTrue(v.separate_bedroom("Dhome + sallon Ekonomike"))
        self.assertFalse(v.separate_bedroom("Dhome Standard"))

    def test_past_check_in_moves_to_today(self):
        fam = next(c for c in load("velipoje") if v.fits_family(c, CFG) and c["currency"] == "EUR")
        _, o = v.to_hotel_and_offer(fam, dict(GOLEM, check_in="2026-06-01"), CFG, TODAY)
        self.assertEqual(o["check_in"], TODAY.isoformat())


class FakeSession:
    def __init__(self, pages, block_after=None):
        self.pages, self.calls, self.block_after = pages, [], block_after

    def get(self, url):
        self.calls.append(url)
        if self.block_after is not None and len(self.calls) > self.block_after:
            raise Blocked("wall")
        return self.pages[url]


class Fetch(unittest.TestCase):
    def cfg(self, pages):
        c = dict(CFG)
        c["sources"] = dict(CFG["sources"], al_me_coast={"enabled": True, "pages": pages})
        return c

    def test_fetch_all_areas_and_dedupe(self):
        pages = [dict(GOLEM, url="g"), {**GOLEM, "url": "s", "area": "Shëngjin, Albania", "zones": ["Shengjin"]},
                 {**GOLEM, "url": "g", "area": "again"}]        # same page twice: rooms not counted twice
        sess = FakeSession({"g": (FIX / "al_me_coast_golem.html").read_text(encoding="utf-8"),
                            "s": (FIX / "al_me_coast_shengjin.html").read_text(encoding="utf-8")})
        hotels, offers = v.fetch(self.cfg(pages), TODAY, sess)
        self.assertEqual(len(offers), 26)                    # 15 Golem + 11 Shëngjin (Lek prices skipped)
        self.assertEqual(len({o["url"] for o in offers}), len(offers))
        self.assertEqual({o["hotel"] for o in offers}, {h["id"] for h in hotels})
        self.assertTrue(all(o["occupancy"] == "2+2" and o["price_eur"] > 0 for o in offers))

    def test_disabled_and_block(self):
        off = {**CFG, "sources": {**CFG["sources"], "al_me_coast": {**CFG["sources"].get("al_me_coast", {}), "enabled": False}}}
        self.assertEqual(v.fetch(off, TODAY, FakeSession({})), ([], []))
        sess = FakeSession({"g": ""}, block_after=0)
        self.assertEqual(v.fetch(self.cfg([dict(GOLEM, url="g"), dict(GOLEM, url="h")]), TODAY, sess), ([], []))
        self.assertEqual(len(sess.calls), 1)                    # stops after the wall


if __name__ == "__main__":
    unittest.main()
