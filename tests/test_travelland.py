"""Travelland parser tests against a saved list answer (Bansko, 25.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import travelland as tl

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml")
PAGE = {"url": "x", "season": "winter", "area": "Bansko, Bulgaria", "country": "BG", "lat": 41.83, "lng": 23.48,
        "nights": 5}


class FakeSession:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        for k, v in self.pages.items():
            if k in url:
                return v
        return '{"html": "", "total": 0}'


class Travelland(unittest.TestCase):
    def setUp(self):
        self.payload = (FIX / "travelland_list_bansko.json").read_text(encoding="utf-8")

    def test_parse_cards(self):
        cards, total = tl.parse_list(self.payload)
        self.assertEqual(total, 30)
        self.assertEqual(len(cards), 12)
        c = next(c for c in cards if c["object_id"] == "111005")
        self.assertEqual(c["name"], "FOUR POINTS BY SHERATON BANSKO (EX. STRAZITE)")
        self.assertEqual((c["price_pp"], c["old_pp"], c["pct"], c["stars"]), (61.0, 77.0, 20, 4))
        self.assertEqual((c["date_from"], c["valid_until"]), ("2026-12-01", "2026-12-23"))

    def test_number_formats(self):
        self.assertEqual(tl._num("1.205"), 1205.0)
        self.assertEqual(tl._num("35,50"), 35.5)

    def test_offer_is_2_adults_times_nights_board_unknown(self):
        cards, _ = tl.parse_list(self.payload)
        c = next(c for c in cards if c["object_id"] == "111005")
        h, o = tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))
        self.assertEqual(o["price_eur"], 61 * 2 * 5)
        self.assertEqual(o["was_eur"], 77 * 2 * 5)
        self.assertEqual((o["occupancy"], o["board"]), ("2+0", "?"))
        self.assertEqual(h["name"], "Four Points By Sheraton Bansko (ex. Strazite)")

    def test_past_window_skipped_and_checkin_not_in_past(self):
        cards, _ = tl.parse_list(self.payload)
        c = next(c for c in cards if c["object_id"] == "111088")       # window 2026-04-14 .. 2026-12-01
        self.assertEqual(tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))[1]["check_in"], "2026-11-25")
        self.assertIsNone(tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 12, 5)))

    def test_fetch_pages_until_total(self):
        cfg = {**CFG, "sources": {**CFG["sources"], "travelland": {"enabled": True, "max_list_pages": 5,
                                                                 "pages": [PAGE]}}}
        s = FakeSession({"x": '<div data-destination="22:294:477:9466">', "paginate=1": self.payload})
        hotels, offers = tl.fetch(cfg, date(2026, 11, 25), session=s)
        self.assertEqual(len(offers), 12)
        self.assertTrue(any("paginate=2" in u for u in s.urls))       # 12 of 30 seen → asks for page 2
        self.assertFalse(any("paginate=3" in u for u in s.urls))      # page 2 empty → stop

    def test_merge_keeps_curated_hotel(self):
        cards, _ = tl.parse_list(self.payload)
        c = next(c for c in cards if c["object_id"] == "111088")       # CASA KARINA
        h, o = tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))
        curated = [{"id": "casa-karina-bansko", "name": "Casa Karina Apartments", "season": "winter"}]
        add = run.merge_auto(curated, [h], [o])
        self.assertEqual(add, [])
        self.assertEqual(o["hotel"], "casa-karina-bansko")


if __name__ == "__main__":
    unittest.main()
