"""Olympic parser tests against saved list answers (25.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import olympic as ol

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
PAGE = {"url": "x", "season": "winter", "area": "Bansko, Bulgaria", "lat": 41.83, "lng": 23.48, "nights": 5,
        "check_in": "2027-01-15"}


class Olympic(unittest.TestCase):
    def load(self, name):
        return ol.parse_list((FIX / name).read_text(encoding="utf-8"))

    def test_bansko_cards_with_discount_and_badge(self):
        cards, total = self.load("olympic_list_bansko_p3.json")
        self.assertEqual(total, 42)
        c = next(c for c in cards if c["object_id"] == "115313")
        self.assertEqual((c["name"], c["stars"], c["price"], c["old"]), ("GRAND HOTEL BANSKO", 5, 181.0, 226.0))
        self.assertEqual((c["badge"], c["valid_until"], c["unit"]), ("RANI BUKING", "2026-12-23", "po danu"))

    def test_on_request_cards_skipped_and_board_read(self):
        cards, total = self.load("olympic_list_kopaonik.json")
        self.assertEqual(total, 18)
        self.assertEqual(len(cards), 3)                       # 9 "na upit" cards have no price
        g = next(c for c in cards if c["object_id"] == "1116")
        self.assertEqual((g["board"], g["unit"]), ("BB", "po osobi po danu"))

    def test_units(self):
        cards, _ = self.load("olympic_list_kopaonik.json")
        today = date(2026, 11, 25)
        by = {c["object_id"]: c for c in cards}
        _, pp = ol.to_hotel_and_offer(by["1116"], PAGE, CFG, today)      # per person per day
        self.assertEqual(pp["price_eur"], 47 * 2 * 5)
        _, stay = ol.to_hotel_and_offer(by["1840"], PAGE, CFG, today)    # per stay
        self.assertEqual(stay["price_eur"], 644)
        cards, _ = self.load("olympic_list_bansko_p3.json")
        _, day = ol.to_hotel_and_offer(cards[0], PAGE, CFG, today)       # per day (unit)
        self.assertEqual(day["price_eur"], 181 * 5)
        self.assertEqual(day["discount_label"], "Rani Buking -20%")
        self.assertEqual(day["check_in"], "2027-01-15")

    def test_board_codes(self):
        self.assertEqual(ol.board_code("Polupansion"), "HB")
        self.assertEqual(ol.board_code("All Inclusive"), "AI")
        self.assertEqual(ol.board_code("Noćenje i doručak"), "BB")
        self.assertEqual(ol.board_code(""), "?")

    def test_cross_source_merge_but_not_on_resort_name(self):
        known = [{"id": "tl-1", "name": "Grand Royale Apart Hotel & Spa", "season": "winter"},
                 {"id": "tl-2", "name": "Lion Bansko", "season": "winter"}]
        hs = [{"id": "ol-1", "name": "Grand Royale", "season": "winter"},
              {"id": "ol-2", "name": "Bansko", "season": "winter"}]
        os_ = [{"hotel": "ol-1"}, {"hotel": "ol-2"}]
        add = run.merge_auto(known, hs, os_)
        self.assertEqual(os_[0]["hotel"], "tl-1")
        self.assertEqual([h["id"] for h in add], ["ol-2"])


if __name__ == "__main__":
    unittest.main()
