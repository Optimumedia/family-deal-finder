"""Family Fit on the facts the detail-page enrichment collects (no network, no db): half board
offered, free-child age limits, beachfront / pebbles, separate bedroom from the room name,
adults-only, and the tier calibration (confirmed → Great, unknown must → capped, stated → ≤79)."""
import unittest
from datetime import date, timedelta
from pathlib import Path

from trips import run, score

BASE = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
CFG = {**BASE, "family": {**BASE["family"], "kids_birthdate": "2023-09-01"}}   # twins 3y 9m on 2027-06-20
TODAY = date(2026, 11, 25)
ALL = ["cots", "sand_beach", "beachfront", "board", "family_room", "kids_club", "kids_pool", "shallow_entry",
       "separate_bedroom", "ski_school", "reach"]


def day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def summer(**fam):
    return {"id": "s1", "name": "Beach", "stars": 4, "season": "summer", "border": True,
            "family": {"sand_beach": True, "beach_m": 20, "verified": [], **fam}}


def winter(**fam):
    return {"id": "w1", "name": "Ski", "stars": 4, "season": "winter", "border": True,
            "family": {"verified": [], **fam}}


def offer(board="HB", occ="2+2", room="Family", history=None, check_in="2027-06-20", key="k1"):
    return {"key": key, "hotel_id": "s1", "source": "test", "occupancy": occ, "board": board, "room": room,
            "check_in": check_in, "nights": 7, "history": history or [{"seen": day(0), "price_eur": 1000}]}


def fit(h, o, drive=200, cfg=CFG):
    return score.family_fit(h, o, cfg, drive)


def state(f, key):
    return next(c for c in f["checklist"] if c["key"] == key)["state"]


class HalfBoard(unittest.TestCase):
    def test_unknown_board_with_half_board_offered_is_available(self):
        f = fit(summer(half_board=True), offer(board="?", occ="2+0"))
        self.assertEqual(state(f, "board"), "available")
        self.assertNotIn("Breakfast + dinner", f["unknown_musts"])
        self.assertFalse(f["failed"])
        self.assertEqual(f["parts"]["food"], 7.5)
        self.assertTrue(any("half board" in q for q in f["questions"]))

    def test_unknown_board_without_facts_stays_an_unknown_must(self):
        f = fit(summer(), offer(board="?", occ="2+0"))
        self.assertEqual(state(f, "board"), "unknown")
        self.assertIn("Breakfast + dinner", f["unknown_musts"])
        self.assertLess(f["parts"]["food"], 7.5)

    def test_priced_bed_and_breakfast_still_fails_even_if_hb_exists(self):
        f = fit(summer(half_board=True), offer(board="BB"))
        self.assertIn("Breakfast + dinner", f["failed"])


class KidsCost(unittest.TestCase):
    def pts(self, **fam):
        return fit(summer(**fam), offer())["parts"]["kids_cost"]

    def test_free_child_limits_vs_twins_age(self):
        both_free = self.pts(kids_free_max_age=6)
        one_free = self.pts(first_child_free_max_age=12)
        both_pay = self.pts(kids_free_max_age=2, first_child_free_max_age=2)
        unknown = self.pts()
        self.assertEqual(both_free, 8.0)
        self.assertGreater(both_free, one_free)
        self.assertGreater(one_free, unknown)
        self.assertGreater(unknown, both_pay)

    def test_age_limit_is_exclusive(self):
        # "0–3 free" and the twins are 3y 9m: they pay (safe side)
        f = fit(summer(kids_free_max_age=3), offer())
        self.assertLess(f["parts"]["kids_cost"], 2)
        self.assertIn("both twins", f["explain"]["kids_cost"])

    def test_same_for_2plus0_and_2plus2(self):
        h = summer(first_child_free_max_age=12)
        self.assertEqual(fit(h, offer(occ="2+0"))["score"], fit(h, offer(occ="2+2"))["score"])


class Beach(unittest.TestCase):
    def test_beachfront_without_metres_counts_as_on_the_beach(self):
        f = fit(summer(beach_m=None, beachfront=True), offer())
        self.assertEqual(state(f, "beachfront"), "yes")
        self.assertFalse(any("Beach" in m for m in f["unknown_musts"]))
        self.assertGreaterEqual(f["parts"]["beach"], fit(summer(), offer())["parts"]["beach"])

    def test_pebbles_exclude_and_lower_the_beach_clearly(self):
        sand = fit(summer(), offer())
        pebble = fit(summer(sand_beach=False), offer())
        self.assertIn("Sandy beach", pebble["failed"])
        self.assertLessEqual(pebble["parts"]["beach"], sand["parts"]["beach"] - 10)
        # even when sand isn't a must, pebbles still cost clearly
        cfg = {**CFG, "summer": {**CFG["summer"], "need_sand": False}}
        loose = fit(summer(sand_beach=False), offer(), cfg=cfg)
        self.assertFalse(loose["failed"])
        self.assertLessEqual(loose["score"], fit(summer(), offer(), cfg=cfg)["score"] - 8)
        self.assertIn("Pebble", loose["explain"]["beach"])

    def test_far_beach_scores_low_and_fails(self):
        f = fit(summer(beach_m=400), offer())
        self.assertIn("Beach ≤150 m", f["failed"])


class WinterRooms(unittest.TestCase):
    def test_bedroom_from_room_name(self):
        f = fit(winter(), offer(board="SC", room="One-bedroom apartment"))
        self.assertEqual(state(f, "separate_bedroom"), "yes")
        self.assertNotIn("Separate bedroom (cots in the other room)", f["unknown_musts"])
        self.assertIn("sleep", f["explain"])

    def test_two_room_and_serbian_names(self):
        for room in ("Apt 2-Bedroom (Bb)", "Dvosobni apartman", "two rooms apartment", "Maisonette"):
            self.assertEqual(state(fit(winter(), offer(board="SC", room=room)), "separate_bedroom"), "yes", room)
        for room in ("Studio", "2+1 Apt (whole unit, up to 4 guests)", "Dbl Standard (Hb)"):
            self.assertEqual(state(fit(winter(), offer(board="SC", room=room)), "separate_bedroom"), "unknown", room)

    def test_hotel_says_no_beats_room_name(self):
        f = fit(winter(separate_bedroom=False), offer(board="SC", room="1 bedroom apartment"))
        self.assertIn("Separate bedroom (cots in the other room)", f["failed"])

    def test_bedroom_and_room_for_four_score_higher(self):
        studio = fit(winter(), offer(board="SC", room="Studio"))["parts"]["sleep"]
        bed = fit(winter(separate_bedroom=True), offer(board="SC", room="Apartment"))["parts"]["sleep"]
        bed4 = fit(winter(separate_bedroom=True), offer(board="SC", room="Apartment (whole unit, up to 4 guests)"))
        self.assertGreater(bed, studio)
        self.assertGreater(bed4["parts"]["sleep"], bed)

    def test_winter_half_board_available(self):
        f = fit(winter(separate_bedroom=True, half_board=True), offer(board="?", room="Apartment"))
        self.assertEqual(state(f, "board"), "available")


class AdultsOnly(unittest.TestCase):
    def test_adults_only_excluded(self):
        r = score.rate(summer(adults_only=True), offer(), [offer()], CFG, 200, TODAY)
        self.assertTrue(r["excluded"])
        self.assertIn("Children welcome", r["family"]["failed"])


class Tiers(unittest.TestCase):
    """A well-matched, fully-confirmed family offer reaches Great deal; an unknown must-have still
    caps it; a stated-only discount can't push it to the top."""

    def confirmed(self, **extra):
        fam = dict(cots_max=2, cot_age_max=5, family_room=True, separate_bedroom=True, kids_club=True,
                   kids_club_min_age=3, kids_pool=True, playground=True, shallow_entry=True, doctor_near=True,
                   stroller_ok=True, kids_free_max_age=6, verified=ALL)
        fam.update(extra)
        return summer(**fam)

    def flat(self, price=1000):
        return [{"seen": day(n), "price_eur": price} for n in (6, 3, 0)]

    def rate(self, h, o, drive=170):
        return score.rate(h, o, [o], CFG, drive, TODAY)

    def test_confirmed_family_offer_is_a_great_deal_without_any_discount(self):
        r = self.rate(self.confirmed(), offer(history=self.flat()))
        self.assertEqual(r["deal"]["verdict"], "flat")
        self.assertFalse(r["capped"])
        self.assertGreaterEqual(r["overall"], 70)
        self.assertEqual(r["tier"]["key"], "great")
        self.assertGreaterEqual(r["family"]["score"], 90)

    def test_unknown_must_still_caps(self):
        r = self.rate(self.confirmed(cots_max=None, cot_age_max=None), offer(history=self.flat()))
        self.assertTrue(r["capped"] or r["overall"] <= CFG["score"]["unknown_cap"])
        self.assertLessEqual(r["overall"], CFG["score"]["unknown_cap"])
        self.assertNotIn(r["tier"]["key"], ("great", "exceptional", "once"))

    def test_stated_only_discount_cannot_reach_the_top(self):
        hist = [{"seen": day(0), "price_eur": 400, "was_eur": 1000, "valid_until": day(-3)}]
        r = self.rate(self.confirmed(), offer(history=hist))
        self.assertEqual(r["deal"]["verdict"], "stated")
        self.assertLessEqual(r["overall"], score.UNPROVEN_CAP)
        self.assertEqual(r["tier"]["key"], "great")
        self.assertTrue(any("Held at 79" in n for n in r["deal"]["notes"]))

    def test_verified_saving_can_go_higher(self):
        hist = self.flat(1200) + [{"seen": day(0) + "T18:00", "price_eur": 800, "valid_until": day(-3)}]
        r = self.rate(self.confirmed(), offer(history=hist))
        self.assertEqual(r["deal"]["verdict"], "real")
        self.assertGreater(r["overall"], score.UNPROVEN_CAP)

    def test_stated_claim_moves_less_than_a_real_saving(self):
        base = self.rate(self.confirmed(), offer(history=[{"seen": day(0), "price_eur": 800}]))["overall"]
        claim = self.rate(self.confirmed(), offer(history=[{"seen": day(0), "price_eur": 800, "was_eur": 1067}]))
        self.assertLessEqual(claim["overall"] - base, 4)        # a "−25%" claim is worth ≤4 overall points

    def test_parts_add_up_and_are_named(self):
        f = fit(self.confirmed(), offer())
        self.assertAlmostEqual(sum(f["parts"].values()), f["raw"], delta=0.2)
        self.assertEqual(set(f["parts"]), {"sleep", "beach", "travel", "kids", "kids_cost", "food", "health",
                                           "logistics", "reviews"})
        self.assertEqual(sum(score.FAMILY_W.values()), 100)
        self.assertEqual(f["confidence"], 1.0)
        unverified = fit(self.confirmed(verified=[]), offer())
        self.assertEqual(unverified["confidence"], score.UNVERIFIED_CONF)


if __name__ == "__main__":
    unittest.main()
