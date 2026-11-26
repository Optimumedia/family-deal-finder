"""Family prices: 2+2 offers from hotel price rows, estimated 2+2 totals, cheapest board. No network."""
import copy
import json
import unittest
from datetime import date
from pathlib import Path

from trips import enrich as en
from trips import family_prices as fp
from trips import run

FIX = Path(__file__).parent / "fixtures"
BASE_CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)
GB_URL = "https://www.olympic.rs/zimovanje/bugarska/bansko/hotel-grand-hotel-bansko/115313/"
MED_URL = "https://www.olympic.rs/letovanje/grcka/paralia-katerini/hotel-mediterranean-resort/102986/"
CACHED = json.loads((FIX / "family_prices_cached_pages.json").read_text(encoding="utf-8"))["pages"]


def cfg_with(birthdate):
    c = copy.deepcopy(BASE_CFG)
    c["family"]["kids_birthdate"] = birthdate       # a made-up date, never the real one
    return c


CFG = cfg_with("2023-12-01")                        # ~3 on the dates used below


def offer(url, price, room="cheapest unit, dates on request (po osobi po danu)", board="?", nights=7,
          check_in="2027-06-20", occupancy="2+0", hotel="ol-1"):
    return {"hotel": hotel, "source": "Olympic", "url": url, "seen": TODAY.isoformat(), "check_in": check_in,
            "nights": nights, "board": board, "room": room, "occupancy": occupancy, "price_eur": price,
            "was_eur": None, "discount_label": None, "valid_until": None}


def page(key):
    return CACHED[key]


class AgeRanges(unittest.TestCase):
    def test_integer_upper_bound_includes_that_whole_year(self):
        self.assertTrue(fp.in_range(2.9, 0, 2))
        self.assertFalse(fp.in_range(3.0, 0, 2))
        self.assertTrue(fp.in_range(3.0, 2, 11))
        self.assertFalse(fp.in_range(2.0, 0, 1.99))
        self.assertFalse(fp.in_range(3, None, 5))

    def test_kid_ranges(self):
        self.assertEqual(fp.kid_ranges("0-5 i 0-5"), [(0, 5), (0, 5)])
        self.assertEqual(fp.kid_ranges(None), [])


class FamilyRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = (FIX / "enrich_olympic_grandbansko.html").read_text(encoding="utf-8")
        cls.facts = en._compact(en.extract(html, GB_URL))
        cls.base = [offer(GB_URL, 1000, room="cheapest unit, dates on request (po jedinici po danu)", nights=5,
                          check_in="2027-01-15", hotel="ol-115313")]

    def test_explicit_2plus2_rows_become_2plus2_offers(self):
        out = fp.family_offers(self.facts, self.base, CFG, TODAY)
        self.assertTrue(1 <= len(out) <= fp.MAX_FAMILY_OFFERS)
        first = out[0]
        self.assertEqual(first["occupancy"], "2+2")
        self.assertIn("family price from hotel page", first["room"])
        self.assertEqual((first["hotel"], first["source"], first["url"], first["nights"]),
                         ("ol-115313", "Olympic", GB_URL, 5))
        # 1-bed apartment, 2 adults + 2 kids 0-5, 1-24 Dec: €271.78 per unit per day (was €339.72)
        self.assertEqual(first["check_in"], "2026-12-01")
        self.assertAlmostEqual(first["price_eur"], 271.78 * 5, places=2)
        self.assertAlmostEqual(first["was_eur"], 339.72 * 5, places=2)
        self.assertEqual(first["board"], "?")         # page offers HB and AI; the rows don't say which
        self.assertEqual([o["check_in"] for o in out], sorted(o["check_in"] for o in out))
        for k in ("hotel", "source", "url", "seen", "check_in", "nights", "board", "room", "occupancy",
                  "price_eur", "was_eur", "discount_label", "valid_until"):
            self.assertIn(k, first)

    def test_cheapest_fitting_row_per_period(self):
        out = fp.family_offers(self.facts, self.base, CFG, TODAY)
        for o in out:
            fits = [r for r in self.facts["price_table"] if r["from"] <= o["check_in"] < r["to"]
                    and fp.is_family_row(r, 3.1) and "jedinic" in (r.get("unit") or "")]
            self.assertAlmostEqual(o["price_eur"], min(r["price"] for r in fits) * o["nights"], places=2)

    def test_kids_too_old_for_the_rows_no_offers(self):
        old = cfg_with("2019-01-01")                # ~8: the 0-5 rows don't fit, 6-11 rows are 2+2 too
        for o in fp.family_offers(self.facts, self.base, old, TODAY):
            self.assertIn("6-11", o["family_price_basis"])

    def test_per_person_rows_and_missing_ages_skipped(self):
        rows = [{"from": "2027-01-01", "to": "2027-02-01", "price": 50, "unit": "po osobi po danu",
                 "occupancy": {"persons": 2, "kids": 2, "kid_ages": "0-5 i 0-5"}, "room": "A"},
                {"from": "2027-01-01", "to": "2027-02-01", "price": 50, "unit": "po jedinici po danu",
                 "occupancy": {"persons": 2, "kids": 2, "kid_ages": None}, "room": "B"},
                {"from": "2027-01-01", "to": "2027-01-04", "price": 50, "unit": "po jedinici po danu",
                 "occupancy": {"persons": 2, "kids": 2, "kid_ages": "0-5 i 0-5"}, "room": "too short"}]
        self.assertEqual(fp.family_offers({"price_table": rows}, self.base, CFG, TODAY), [])

    def test_no_base_offers(self):
        self.assertEqual(fp.family_offers(self.facts, [], CFG, TODAY), [])


class Estimates(unittest.TestCase):
    ELINOTEL = "olympic.rs/letovanje/grcka/hanioti/hotel-elinotel-polis/102988/"
    CHROUSSO = "olympic.rs/letovanje/grcka/paliouri/hotel-chrousso-village/102768/"
    CALYPSO = "olympic.rs/letovanje/grcka/hanioti/hotel-calypso/102769/"
    AMMON = "olympic.rs/letovanje/grcka/kasandra/hotel-ammon-zeus-luxury-beach-hotel/114234/"

    def est(self, key, price, **kw):
        p = page(key)
        return fp.estimate(offer("https://www." + key, price, **kw), p["child_policy"], p["rooms"], CFG)

    def test_first_free_second_pays_20_pct(self):
        eur, basis = self.est(self.ELINOTEL, 504.0)
        self.assertEqual(eur, 554.0)                  # 504 + 0.2 × 252
        self.assertIn("first child stays free", basis)
        self.assertIn("second child pays 20 % of an adult", basis)
        self.assertIn("+10 %", basis)
        self.assertIn("Estimate", basis)

    def test_conflicting_rules_use_the_dearest(self):
        eur, basis = self.est(self.CHROUSSO, 938.0)
        # 2nd child 2-11: 50 % discount (234.50) or €29.99 a night (209.93) → 234.50 used
        self.assertEqual(eur, round(938 + 0.5 * 469))
        self.assertIn("dearest", basis)
        eur, basis = self.est(self.CALYPSO, 518.0)    # 1st child 2-5: 70 % or 50 % off → 50 % used
        self.assertEqual(eur, 777.0)

    def test_both_free(self):
        pol = [{"kind": "discount", "child": None, "age_from": 0, "age_to": 5, "pct": 100, "unit": "po osobi po danu",
                "eur_min": None, "eur_max": None, "label": "Popust za dete (0 - 5)"}]
        eur, basis = fp.estimate(offer("https://www.olympic.rs/x/1/", 600.0), pol, [], CFG)
        self.assertEqual(eur, 600.0)
        self.assertIn("Both kids stay free", basis)
        self.assertEqual(basis.count("each child stays free"), 1)

    def test_not_explicit_enough_no_estimate(self):
        self.assertIsNone(self.est(self.AMMON, 826.0))          # only board / extra-bed supplements
        pol = [{"kind": "discount", "child": 1, "age_from": 0, "age_to": 11, "pct": 100, "unit": "po osobi po danu",
                "eur_min": None, "eur_max": None, "label": "Popust za 1 dete (0 - 11)"}]
        self.assertIsNone(fp.estimate(offer("https://www.olympic.rs/x/1/", 600.0), pol, [], CFG))   # 2nd child?
        self.assertIsNone(self.est(self.ELINOTEL, 504.0, room="cheapest unit, dates on request (po danu)"))
        self.assertIsNone(self.est(self.ELINOTEL, 504.0, occupancy="2+2"))
        small = [{"name": "Double", "max_persons": 3}]
        self.assertIsNone(fp.estimate(offer("https://www." + self.ELINOTEL, 504.0),
                                      page(self.ELINOTEL)["child_policy"], small, CFG))

    def test_age_on_check_in_matters(self):
        p = page(self.ELINOTEL)
        baby = cfg_with("2026-03-01")                 # ~1 in June 2027: 2nd child 0-1 is free too
        eur, basis = fp.estimate(offer("https://www." + self.ELINOTEL, 504.0), p["child_policy"], p["rooms"], baby)
        self.assertEqual(eur, 504.0)


class CheapestBoard(unittest.TestCase):
    def test_mediterranean_bb_is_cheapest(self):
        html = (FIX / "enrich_olympic_mediterranean.html").read_text(encoding="utf-8")
        s = en.page_summary(en._compact(en.extract(html, MED_URL)))
        board, basis = fp.cheapest_board(s["board_prices"], s["board_options"])
        self.assertEqual(board, "BB")
        self.assertIn("HB from", basis)

    def test_needs_two_priced_boards_and_a_strict_winner(self):
        self.assertIsNone(fp.cheapest_board({"HB": 40.0}, ["HB", "FB"]))
        self.assertIsNone(fp.cheapest_board({"HB": 40.0, "FB": 40.0}, ["HB", "FB"]))
        self.assertIsNone(fp.cheapest_board({}, []))


class Annotate(unittest.TestCase):
    def test_fields_and_never_touches_price_or_occupancy(self):
        key = Estimates.ELINOTEL
        o = offer("https://www." + key, 504.0)
        extra = fp.annotate(o, page(key), CFG)
        self.assertEqual(set(extra), {"family_price_est", "family_price_basis"})
        self.assertEqual((o["price_eur"], o["occupancy"]), (504.0, "2+0"))

    def test_other_site_not_annotated(self):
        key = Estimates.ELINOTEL
        self.assertEqual(fp.annotate(offer("https://www.fibula.com.mk/x", 504.0), page(key), CFG), {})
        self.assertEqual(fp.annotate(offer("https://www." + key, 504.0), None, CFG), {})

    def test_cached_pages_count(self):
        """The 19 data.json offers whose pages are cached on 25.11.2026: how many gain an estimate."""
        offers = [
            (Estimates.ELINOTEL, 504.0), (Estimates.ELINOTEL, 504.0), (Estimates.CHROUSSO, 938.0),
            (Estimates.CHROUSSO, 938.0), (Estimates.CALYPSO, 518.0), (Estimates.CALYPSO, 518.0),
            ("olympic.rs/letovanje/grcka/kalithea/hotel-aegean-melathron/102886/", 714.0),
            (Estimates.AMMON, 826.0),
            ("olympic.rs/letovanje/grcka/pefkohori/hotel-agnes-deluxe-hotel/113841/", 616.0),
        ]
        got = sum(bool(fp.annotate(offer("https://www." + k, p), page(k), CFG).get("family_price_est"))
                  for k, p in offers)
        self.assertEqual(got, 7)


if __name__ == "__main__":
    unittest.main()
