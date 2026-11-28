"""Italian resorts' price sheets (Radio Radio Viaggi PDFs, saved as extracted text): parser tests. No network."""
import copy
import json
import re
import tomllib
import unittest
from datetime import date
from pathlib import Path

from tests.fakes import FakeSession, no_network
from trips import run
from trips.http import Blocked
from trips.sources import it_hotels as it

ROOT = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(ROOT / "config.toml", local=None)
TODAY = date(2026, 11, 28)


def proposal_block() -> dict:
    md = (ROOT / "proposals" / "it_hotels.md").read_text(encoding="utf-8")
    return tomllib.loads(re.search(r"```toml\n(.*?)```", md, re.S).group(1))["sources"]["it_hotels"]


SRC = proposal_block()
PAGES = {p["key"]: {**{k: v for k, v in SRC.items() if k not in ("pages", "enabled", "discover")}, **p}
         for p in SRC["pages"]}
FILES = {"porto-giardino": "porto_giardino", "baia-domizia": "baia_domizia",
         "le-tonnare": "le_tonnare", "mclub-golfo": "mclub_golfo"}


def text(key):
    return json.loads((FIX / f"it_hotels_{FILES[key]}.json").read_text(encoding="utf-8"))["text"]


def sheet(key):
    return it.parse_sheet(text(key))


def offers(key, cfg=CFG, today=TODAY, **over):
    page = {**PAGES[key], **over}
    return it.hotel_offers(sheet(key), page, cfg, today, page["pdf"])


def cfg_born(bd):
    c = copy.deepcopy(CFG)
    c["family"]["kids_birthdate"] = bd
    return c


TWINS = cfg_born("2023-10-15")


class Sheet(unittest.TestCase):
    def test_per_stay_rows(self):
        s = sheet("le-tonnare")
        self.assertEqual(s["year"], 2026)
        self.assertEqual(len(s["rows"]), 15)
        r = s["rows"][6]                                  # 17/07 – 31/07
        self.assertEqual((r["d1"], r["m1"], r["d2"], r["m2"], r["nights"]), (17, 7, 31, 7, 7))
        self.assertFalse(r["per_night"])
        self.assertEqual(r["cells"], [984.0, 917.0, 1050.0, ("red", 1.0), ("red", 1.0)])

    def test_per_night_rows_with_min_stay(self):
        s = sheet("porto-giardino")
        r = next(r for r in s["rows"] if (r["d1"], r["m1"]) == (9, 8))
        self.assertTrue(r["per_night"])
        self.assertEqual(r["min_nights"], 7)
        self.assertEqual(r["cells"], [199.0, 220.0, ("red", 0.9), ("red", 0.5), ("red", 0.25)])

    def test_package_tables_are_separate_rows(self):
        # MClub's page also carries 10/11-night ferry packages (2 cells); only the 7-night rows match columns
        s = sheet("mclub-golfo")
        sevens = [r for r in s["rows"] if it._named(r, PAGES["mclub-golfo"]["columns"])]
        self.assertEqual(len(sevens), 13)
        self.assertTrue(all(r["nights"] == 7 for r in sevens))
        self.assertTrue(any(r["nights"] == 11 for r in s["rows"]))

    def test_thousands_dot(self):
        self.assertEqual(it._cell("1.050"), 1050.0)
        self.assertEqual(it._cell("90%"), ("red", 0.9))
        self.assertEqual(it._cell("gratis (*)"), ("red", 1.0))
        self.assertIsNone(it._cell("#-"))


class Offers(unittest.TestCase):
    def test_le_tonnare_total_with_tessera(self):
        h, offs = offers("le-tonnare", cfg=TWINS)
        o = next(o for o in offs if o["check_in"] == "2027-07-17")
        # 2 × 917 + 3rd bed free + 4th bed 50% + tessera €7 × 4 persons × 7 nights
        self.assertAlmostEqual(o["price_eur"], 2 * 917 + 0.5 * 917 + 196)
        self.assertAlmostEqual(o["was_eur"], 2 * 1050 + 0.5 * 1050 + 196)
        self.assertEqual((o["occupancy"], o["board"], o["nights"]), ("2+2", "FB", 7))
        self.assertIn("2026 price list", o["room"])
        self.assertIn("2026", h["notes"])
        self.assertEqual(h["id"], "rr-le-tonnare")
        self.assertTrue(h["direct_flight_skp"])
        self.assertEqual(h["family"]["beach_type"], "mixed")

    def test_months_filter(self):
        _, offs = offers("le-tonnare", cfg=TWINS)
        self.assertTrue(offs)
        self.assertTrue(all(o["check_in"][5:7] in ("07", "08", "09") for o in offs))

    def test_tessera_window(self):
        # 11/09 – 18/09: tessera only on the night of 11.09 (window ends 09-11)
        _, offs = offers("le-tonnare", cfg=TWINS)
        o = next(o for o in offs if o["check_in"] == "2027-09-11")
        self.assertAlmostEqual(o["price_eur"], 2.5 * 503 + 7 * 4 * 1)

    def test_porto_giardino_per_night_across_periods(self):
        _, offs = offers("porto-giardino", cfg=TWINS)
        o = next(o for o in offs if o["check_in"] == "2027-08-23")
        # 23/08 – 30/08 is 7 nights at 181 → 181 × 7 × (2 + 0.1 + 0.5)
        self.assertAlmostEqual(o["price_eur"], round(181 * 7 * 2.6, 2))
        o = next(o for o in offs if o["check_in"] == "2027-08-02")
        self.assertAlmostEqual(o["price_eur"], round(181 * 7 * 2.6, 2))   # 02/08–09/08 exactly one week
        o = next(o for o in offs if o["check_in"] == "2027-06-21")
        self.assertAlmostEqual(o["price_eur"], round(131 * 7 * 2.6, 2))
        self.assertEqual(o["board"], "AI")

    def test_crossing_two_periods(self):
        # Baia Domizia 23/08 – 25/08 (124) then 25/08 – 01/09 (102): 2 + 5 nights
        _, offs = offers("baia-domizia", cfg=TWINS)
        o = next(o for o in offs if o["check_in"] == "2027-08-23")
        self.assertAlmostEqual(o["price_eur"], round((2 * 124 + 5 * 102) * 3.0, 2))
        self.assertAlmostEqual(o["was_eur"], round((2 * 140 + 5 * 115) * 3.0, 2))
        self.assertEqual(o["board"], "HB")

    def test_min_stay_respected(self):
        _, offs = offers("porto-giardino", cfg=TWINS, nights=5)
        self.assertNotIn("2027-08-09", [o["check_in"] for o in offs])   # min 7 nights 09/08 – 23/08
        self.assertIn("2027-07-19", [o["check_in"] for o in offs])

    def test_mclub_kid_forfait_in_august(self):
        _, offs = offers("mclub-golfo", cfg=TWINS)
        aug = next(o for o in offs if o["check_in"] == "2027-08-07")
        self.assertAlmostEqual(aug["price_eur"], 2.5 * 1127 + 50 * 7)
        jul = next(o for o in offs if o["check_in"] == "2027-07-17")
        self.assertAlmostEqual(jul["price_eur"], 2.5 * 939)
        self.assertGreater(jul["was_eur"], jul["price_eur"])

    def test_rules_changed_skips_hotel(self):
        page = copy.deepcopy(PAGES["le-tonnare"])
        page["extras"][0]["check"] = "€ 9 a persona al giorno"
        h, offs = it.hotel_offers(sheet("le-tonnare"), page, TWINS, TODAY, page["pdf"])
        self.assertIsNone(h)
        self.assertEqual(offs, [])

    def test_twins_under_three_get_no_offer(self):
        _, offs = offers("le-tonnare", cfg=cfg_born("2024-12-01"))   # still 2 until Dec 2027
        self.assertEqual(offs, [])

    def test_current_year_sheet_not_labelled(self):
        txt = text("le-tonnare").replace("Estate 2026", "Estate 2027")
        h, offs = it.hotel_offers(it.parse_sheet(txt), PAGES["le-tonnare"], TWINS, TODAY, "https://x.test/a.pdf")
        self.assertTrue(offs)
        self.assertNotIn("price list", offs[0]["room"].split("(")[0])
        self.assertIn("2027", offs[0]["discount_label"])

    def test_all_pages_validate(self):
        from trips import validate
        for key in PAGES:
            h, offs = offers(key, cfg=TWINS)
            self.assertTrue(offs, key)
            for o in offs:
                self.assertEqual(validate.problems(o, TODAY, validate.limits(CFG), h), [], (key, o))


class Discovery(unittest.TestCase):
    def test_newest_main_sheet(self):
        payload = json.dumps([
            {"source_url": "https://viaggi.radioradio.it/wp-content/uploads/2027/02/2027-puglia-porto-giardino-rep1-IN4.pdf"},
            {"source_url": "https://viaggi.radioradio.it/wp-content/uploads/2027/01/2027-puglia-porto-giardino-IN4.pdf"},
            {"source_url": "https://viaggi.radioradio.it/wp-content/uploads/2024/02/2024-puglia-porto-giardino-IN4.pdf"},
        ])
        self.assertEqual(it.newest_pdf(payload, "puglia-porto-giardino"),
                         (2027, "https://viaggi.radioradio.it/wp-content/uploads/2027/01/2027-puglia-porto-giardino-IN4.pdf"))

    def test_saved_media_answer(self):
        payload = (FIX / "it_hotels_media_giardino.json").read_text(encoding="utf-8")
        self.assertEqual(it.newest_pdf(payload, "puglia-porto-giardino")[0], 2024)
        self.assertIsNone(it.newest_pdf("not json", "x"))


class Fetch(unittest.TestCase):
    def cfg(self, **src):
        c = copy.deepcopy(TWINS)
        c["sources"]["it_hotels"] = {**SRC, **src}
        return c

    def routes(self, media=lambda u: "[]"):
        r = [(r"/wp-json/wp/v2/media", media)]
        for key, f in FILES.items():
            r.append((re.escape(PAGES[key]["pdf"]), lambda u, k=key: text(k)))
        return r

    def test_fetch_uses_fallback_pdfs(self):
        s = FakeSession(self.routes())
        with no_network():
            hotels, offs = it.fetch(self.cfg(), TODAY, session=s)
        self.assertEqual(len(hotels), 4)
        self.assertEqual({o["source"] for o in offs}, {it.SOURCE})
        self.assertEqual(sum(1 for u in s.urls if "wp-json" in u), 4)
        self.assertTrue(all("2026 price list" in o["room"] for o in offs))

    def test_fetch_prefers_newer_sheet(self):
        new = "https://viaggi.radioradio.it/wp-content/uploads/2027/01/2027-sardegna-le-tonnare-IN4.pdf"
        media = lambda u: json.dumps([{"source_url": new}]) if "tonnare" in u else "[]"   # noqa: E731
        r = [(re.escape(new), lambda u: text("le-tonnare").replace("Estate 2026", "Estate 2027"))] + self.routes(media)
        s = FakeSession(r)
        with no_network():
            _, offs = it.fetch(self.cfg(), TODAY, session=s)
        ton = [o for o in offs if o["hotel"] == "rr-le-tonnare"]
        self.assertTrue(ton and all(o["url"] == new for o in ton))
        self.assertTrue(all("price list" not in o["room"] for o in ton))

    def test_disabled_and_blocked(self):
        self.assertEqual(it.fetch(self.cfg(enabled=False), TODAY, session=FakeSession()), ([], []))
        s = FakeSession([(r".", Blocked("wall"))])
        with no_network():
            self.assertEqual(it.fetch(self.cfg(), TODAY, session=s), ([], []))
        self.assertEqual(len(s.urls), 1)                     # stops at the first block

    def test_missing_pdf_skips_hotel(self):
        r = [(re.escape(PAGES["porto-giardino"]["pdf"]), "")] + self.routes()
        with no_network():
            hotels, _ = it.fetch(self.cfg(), TODAY, session=FakeSession(r))
        self.assertEqual(len(hotels), 3)


if __name__ == "__main__":
    unittest.main()
