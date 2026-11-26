"""Travelland parser tests against a saved list answer (Bansko, 25.11.2026). No network."""
import unittest
from datetime import date
from pathlib import Path

from trips import run
from trips.sources import travelland as tl

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
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

    def test_card_photo_hotlinked(self):
        cards, _ = tl.parse_list(self.payload)
        self.assertTrue(all(c["image"] and c["image"].startswith("https://mcdn.pro/") for c in cards))
        self.assertEqual(cards[0]["image"], "https://mcdn.pro/data/objects/images/53424/53424_5581_thumb_800x600.jpeg")
        c = next(c for c in cards if c["object_id"] == "111005")
        h, _ = tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))
        self.assertEqual(h["image"], c["image"])

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

    def test_merge_carries_photo_to_curated_hotel(self):
        cards, _ = tl.parse_list(self.payload)
        c = next(c for c in cards if c["object_id"] == "111088")
        h, o = tl.to_hotel_and_offer(c, PAGE, CFG, date(2026, 11, 25))
        photos = {}
        run.merge_auto([{"id": "casa-karina-bansko", "name": "Casa Karina Apartments", "season": "winter"}],
                       [h], [o], photos)
        self.assertEqual(photos, {"casa-karina-bansko": c["image"]})
        photos = {}                                                   # a curated photo is never replaced
        run.merge_auto([{"id": "casa-karina-bansko", "name": "Casa Karina Apartments", "season": "winter",
                         "image": "https://example.org/own.jpg"}], [h], [o], photos)
        self.assertEqual(photos, {})

    def test_image_url_made_absolute_https(self):
        from trips.sources.pagetext import image_url
        self.assertEqual(image_url("//cdn.x/a.jpg", tl.BASE), "https://cdn.x/a.jpg")
        self.assertEqual(image_url("/img/a.jpg", tl.BASE), "https://www.travelland.rs/img/a.jpg")
        self.assertEqual(image_url("http://cdn.x/a.jpg?a=1&amp;b=2", tl.BASE), "https://cdn.x/a.jpg?a=1&b=2")
        self.assertIsNone(image_url("data:image/gif;base64,AAA", tl.BASE))
        self.assertIsNone(image_url(None, tl.BASE))


SUMMER = {"url": "https://www.travelland.rs/destinacije/grcka/letovanje/hoteli/tasos/", "tag_category": 564,
          "season": "summer", "area": "Thassos, Greece", "country": "GR", "lat": 40.68, "lng": 24.65, "nights": 7,
          "check_in": "2027-06-20"}


class TravellandTagPagesAndPaging(unittest.TestCase):
    """Saved 2026-11-26: Thassos tag 564 list answer, and a "Ponuda stiže uskoro" answer (Kassandra)."""

    def setUp(self):
        self.thassos = (FIX / "travelland_list_thassos_tag564.json").read_text(encoding="utf-8")
        self.bansko = (FIX / "travelland_list_bansko.json").read_text(encoding="utf-8")

    def cfg(self, *pages):
        return {**CFG, "sources": {**CFG["sources"], "travelland": {"enabled": True, "max_list_pages": 5,
                                                                 "pages": list(pages)}}}

    def test_list_query_from_config_or_page(self):
        self.assertEqual(tl.list_query({"destination": "1:2"}), {"destination": "1:2"})
        self.assertEqual(tl.list_query({"tag_category": 564}), {"destination": "", "tagCategoryId": "564"})
        self.assertIsNone(tl.list_query({"url": "x"}))                       # -> fetch the page
        form_then_list = ('<form data-destination="89:60" data-tagCategoryId="">'
                          '<div class="list-featured" data-destination="89:60:2364"></div>')
        self.assertEqual(tl.list_query({}, form_then_list), {"destination": "89:60:2364"})
        tag_page = '<form data-destination="" data-tagCategoryId="564"><div class="list-featured" data-destination="">'
        self.assertEqual(tl.list_query({}, tag_page), {"destination": "", "tagCategoryId": "564"})
        self.assertIsNone(tl.list_query({}, '<div data-destination="">'))

    def test_thassos_summer_cards_without_date_window(self):
        cards, total = tl.parse_list(self.thassos)
        self.assertEqual((total, len(cards), len(tl.listed_ids(self.thassos))), (31, 7, 12))
        by = {c["object_id"]: c for c in cards}
        a = by["102901"]                                       # Atrium of Thassos, "po danu od", VAŽE DO
        self.assertEqual((a["price_pp"], a["old_pp"], a["pct"], a["valid_until"], a["date_from"]),
                         (69.0, 94.0, 27, "2026-11-30", None))
        h, o = tl.to_hotel_and_offer(a, SUMMER, CFG, date(2026, 11, 26))
        self.assertEqual((o["check_in"], o["nights"], o["price_eur"]), ("2027-06-20", 7, 69 * 7))   # per unit
        _, pp = tl.to_hotel_and_offer(by["102892"], SUMMER, CFG, date(2026, 11, 26))                # per person
        self.assertEqual(pp["price_eur"], 43 * 2 * 7)
        self.assertEqual(pp["discount_label"], "Travelland -20%")

    def test_tag_page_fetch_uses_tag_and_stops_on_repeated_cards(self):
        s = FakeSession({"tagCategoryId=564": self.thassos})  # the site answers every page with the same 12
        hotels, offers = tl.fetch(self.cfg(SUMMER), date(2026, 11, 26), session=s)
        self.assertEqual(len(offers), 7)
        self.assertEqual(len({o["hotel"] for o in offers}), 7)
        self.assertFalse(any("/destinacije/" in u for u in s.urls))          # tag in config: no page request
        self.assertEqual(len(s.urls), 2)                                     # page 2 repeats page 1 -> stop
        self.assertIn("destination=&tagCategoryId=564", s.urls[0])
        self.assertIn("_page=2", s.urls[1])

    def test_repeating_pages_not_double_counted(self):
        s = FakeSession({"destination=e2e": self.bansko})     # 30 listed, but every page = the same 12
        _, offers = tl.fetch(self.cfg({**PAGE, "destination": "e2e"}), date(2026, 11, 25), session=s)
        self.assertEqual(len(offers), 12)                     # was 36 (3 pages x the same 12) on 25.11
        self.assertEqual(len(s.urls), 2)

    def test_coming_soon_answer_is_empty(self):
        payload = (FIX / "travelland_list_coming_soon.json").read_text(encoding="utf-8")
        self.assertEqual(tl.parse_list(payload), ([], 0))
        s = FakeSession({"destination=89": payload})
        _, offers = tl.fetch(self.cfg({**PAGE, "destination": "89:60:2364"}), date(2026, 11, 26), session=s)
        self.assertEqual((offers, len(s.urls)), ([], 1))


if __name__ == "__main__":
    unittest.main()
