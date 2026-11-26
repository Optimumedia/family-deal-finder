"""Olympic parser tests against saved list answers (25.11.2026). No network."""
import json
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
        self.assertEqual(c["image"], "https://mcdn.pro/data/objects/images/64317/64317_214_thumb_800x600.jpeg")
        h, _ = ol.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))
        self.assertEqual(h["image"], c["image"])

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


class FakeSession:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return next((v for k, v in self.pages.items() if k in url), '{"html": "", "total": 0}')


OHRID = {"url": "x", "destination": "144:158:263:9157", "season": "summer", "area": "Ohrid, North Macedonia",
         "lat": 41.117, "lng": 20.802, "nights": 7, "check_in": "2027-06-20", "border": False}


class OlympicPagingAndBoards(unittest.TestCase):
    """Ohrid list pages 2 and 3, saved 2026-11-26 (total 26: 12 + 12 + 2)."""

    def setUp(self):
        self.p2 = (FIX / "olympic_list_ohrid_p2.json").read_text(encoding="utf-8")
        self.p3 = (FIX / "olympic_list_ohrid_p3.json").read_text(encoding="utf-8")

    def cfg(self):
        return {**CFG, "sources": {**CFG["sources"], "olympic": {"enabled": True, "max_list_pages": 8,
                                                              "pages": [OHRID]}}}

    def test_board_in_small_uppercase_div_and_missing_board(self):
        cards, total = ol.parse_list(self.p2)
        by = {c["object_id"]: c for c in cards}
        self.assertEqual((total, len(ol.listed_ids(self.p2)), len(cards)), (26, 12, 5))
        self.assertEqual(by["1292"]["board"], "BB")           # <div class="text-uppercase small">
        self.assertEqual(by["1112"]["board"], "?")            # Aqualina: the card has no board line

    def test_board_other_markup(self):
        card = ('<div class="col-md-6"><a href="/letovanje/x/hotel-y/77/" class="card-package">'
                '<h4 class="h5 mb-0">Hotel Y</h4><h5 class="h6 small mb-0">Najbolja cena</h5>'
                '<span class="badge text-uppercase">Polupansion</span>'
                '<div class="h2 lh-1 text-primary mb-0">€ 50</div><div class="small text-end">po danu</div></a>')
        c = ol.parse_list(json.dumps({"html": card, "total": 1}))[0][0]
        self.assertEqual(c["board"], "HB")
        loose = card.replace('<span class="badge text-uppercase">Polupansion</span>',
                             '<p class="info">Usluga: All Inclusive</p>')
        self.assertEqual(ol.parse_list(json.dumps({"html": loose, "total": 1}))[0][0]["board"], "AI")

    def test_reads_every_page_then_stops_at_total(self):
        s = FakeSession({"_page=1&": self.p2, "_page=2&": self.p3})   # 12 + 2 of 26 listed, then empty
        _, offers = ol.fetch(self.cfg(), date(2026, 11, 26), session=s)
        self.assertEqual(len(offers), 7)
        self.assertEqual([u.split("_page=")[1].split("&")[0] for u in s.urls], ["1", "2", "3"])

    def test_stops_when_page_only_repeats(self):
        s = FakeSession({"_page=": self.p2})                  # a site ignoring _page: same 12 every time
        _, offers = ol.fetch(self.cfg(), date(2026, 11, 26), session=s)
        self.assertEqual((len(offers), len(s.urls)), (5, 2))
        self.assertEqual(len({o["hotel"] for o in offers}), 5)


if __name__ == "__main__":
    unittest.main()
