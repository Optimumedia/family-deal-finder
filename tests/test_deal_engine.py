"""Deal engine on synthetic price histories (no network, no db): baselines, evidence rules,
pre-sale inflation, trend + book-now signal, 2+0 vs 2+2 ranking, explainable parts, digest."""
import random
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from trips import db, digest, run, score

CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)
HOTEL = {"id": "h1", "name": "Test Beach", "stars": 4, "season": "summer", "area": "X", "lat": 40.0, "lng": 23.5,
         "border": True, "family": {"sand_beach": True, "beach_m": 20, "half_board": True, "verified": []}}


def day(n: int) -> str:
    """n days before TODAY, ISO."""
    return (TODAY - timedelta(days=n)).isoformat()


def snap(seen, price, was=None, valid_until=None, checks=None):
    s = {"seen": seen, "price_eur": price, "was_eur": was, "valid_until": valid_until}
    if checks:
        s["checks"] = checks
    return s


def mk(history, occ="2+2", key="k1", hotel="h1", board="HB", check_in="2027-06-20", nights=7, source="test"):
    return {"key": key, "hotel_id": hotel, "source": source, "occupancy": occ, "board": board,
            "check_in": check_in, "nights": nights, "history": history}


def deal(history, **kw):
    o = mk(history, **kw)
    return score.deal_quality(o, [o], CFG, TODAY, True)


class Baselines(unittest.TestCase):
    def test_low_and_median_from_the_30_day_window(self):
        d = deal([snap(day(40), 500), snap(day(20), 1000), snap(day(10), 1100), snap(day(5), 1200),
                  snap(day(0), 900)])
        self.assertEqual(d["baseline_low"], 1000)          # the €500 from 40 days ago is outside the window
        self.assertEqual(d["baseline_median"], 1100)
        self.assertEqual((d["observations"], d["observed_days"]), (4, 4))
        self.assertEqual(d["verdict"], "real")
        self.assertEqual(d["real_pct"], 10.0)
        self.assertEqual(d["vs_median_pct"], 18.2)

    def test_real_needs_three_checks_over_two_days(self):
        two = deal([snap(day(3), 1000), snap(day(0), 900)])
        self.assertEqual(two["verdict"], "unconfirmed")
        self.assertIsNone(two["real_pct"])                  # never shown as "Verified" on the dashboard
        self.assertEqual(two["vs_low_pct"], 10.0)
        three = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 900)])
        self.assertEqual(three["verdict"], "real")
        self.assertGreater(three["score"], two["score"])

    def test_three_checks_on_one_day_are_not_enough(self):
        d = deal([snap(f"{day(0)}T09:00", 1000), snap(f"{day(0)}T13:00", 1000), snap(f"{day(0)}T17:30", 900)])
        self.assertEqual((d["observations"], d["observed_days"]), (3, 1))
        self.assertEqual(d["verdict"], "unconfirmed")

    def test_folded_repeat_checks_count_as_observations(self):
        d = deal([snap(day(1), 1000, checks=2), snap(day(0), 900)])
        self.assertEqual((d["observations"], d["observed_days"]), (3, 2))
        self.assertEqual(d["verdict"], "real")

    def test_drop_under_3_pct_is_not_real(self):
        d = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 980)])
        self.assertEqual(d["verdict"], "flat")
        self.assertEqual(d["score"], deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 1000)])["score"])

    def test_big_claim_small_real_drop_is_fake_with_enough_history(self):
        d = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 980, was=1400)])
        self.assertEqual(d["verdict"], "fake?")
        self.assertTrue(any("not cheaper" in n for n in d["notes"]))

    def test_stated_only_without_history(self):
        d = deal([snap(day(0), 750, was=1000)])
        self.assertEqual((d["verdict"], d["stated_pct"], d["baseline_low"]), ("stated", 25.0, None))

    def test_was_below_price_is_no_claim(self):
        self.assertEqual(deal([snap(day(0), 1000, was=900)])["verdict"], "none")


class PreSaleInflation(unittest.TestCase):
    D = score.deal_settings(CFG)

    def test_rise_before_claim_detected(self):
        h = [snap(day(20), 1000), snap(day(12), 1000), snap(day(8), 1200), snap(day(5), 1000, was=1200),
             snap(day(0), 1000, was=1200)]
        inf = score._inflation(h, self.D)
        self.assertEqual(inf, {"rise_pct": 20.0, "claim_seen": day(5)})
        d = deal(h)
        self.assertEqual(d["verdict"], "fake?")
        self.assertEqual(d["inflated"]["rise_pct"], 20.0)

    def test_price_in_force_at_window_start_is_the_anchor(self):
        # €1000 seen 18 days before the claim (outside the 14-day window) is still the price when it opened
        h = [snap(day(23), 1000), snap(day(7), 1180), snap(day(5), 1000, was=1180), snap(day(0), 1000, was=1180)]
        self.assertEqual(score._inflation(h, self.D)["rise_pct"], 18.0)

    def test_small_or_old_rises_ignored(self):
        small = [snap(day(10), 1000), snap(day(8), 1100), snap(day(0), 1000, was=1100)]
        self.assertIsNone(score._inflation(small, self.D))
        old = [snap(day(80), 1000), snap(day(70), 1300), snap(day(20), 1300), snap(day(0), 1100, was=1300)]
        self.assertIsNone(score._inflation(old, self.D))     # the rise was long before the claim

    def test_claim_since_first_sighting_cannot_be_checked(self):
        self.assertIsNone(score._inflation([snap(day(3), 900, was=1200), snap(day(0), 900, was=1200)], self.D))

    def test_inflation_flags_thin_history_that_would_look_cheaper(self):
        # rise happened before the 30-day window; in-window history alone says "4.5% below the low"
        h = [snap(day(50), 1000), snap(day(43), 1300), snap(day(40), 1100, was=1300), snap(day(5), 1100, was=1300),
             snap(day(0), 1050, was=1300)]
        d = deal(h)
        self.assertEqual(d["verdict"], "fake?")
        self.assertTrue(any("rose 30%" in n for n in d["notes"]))

    def test_genuine_low_still_real_but_notes_the_inflated_was(self):
        h = [snap(day(20), 1000), snap(day(12), 1000), snap(day(8), 1200), snap(day(0), 900, was=1200)]
        d = deal(h)
        self.assertEqual((d["verdict"], d["real_pct"]), ("real", 10.0))
        self.assertTrue(any("inflated" in n for n in d["notes"]))


class Signal(unittest.TestCase):
    def test_deadline_soon_at_low_books_now(self):
        d = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 1000, valid_until=day(-3))])
        self.assertEqual((d["signal"], d["days_left"]), ("book now", 3))
        self.assertIn("ends in 3 days", d["signal_reason"])

    def test_deadline_soon_but_above_low_is_watch(self):
        d = deal([snap(day(6), 900), snap(day(3), 1000), snap(day(0), 1000, valid_until=day(-2))])
        self.assertEqual(d["signal"], "watch")
        self.assertIn("€100 above", d["signal_reason"])

    def test_deadline_with_no_history_books_now_with_low_confidence(self):
        d = deal([snap(day(0), 1000, valid_until=day(0))])
        self.assertEqual((d["signal"], d["confidence"]), ("book now", "low"))
        self.assertIn("ends today", d["signal_reason"])

    def test_rising_trend_books_now(self):
        d = deal([snap(day(9), 1000), snap(day(6), 1040), snap(day(3), 1080), snap(day(0), 1120)])
        self.assertEqual((d["trend"], d["signal"]), ("rising", "book now"))
        self.assertAlmostEqual(d["trend_pct"], 11.3, places=1)    # fitted +€120 over 9 days / mean €1060

    def test_flat_no_deadline_can_wait(self):
        d = deal([snap(day(9), 1000), snap(day(6), 1005), snap(day(3), 995), snap(day(0), 1000)])
        self.assertEqual((d["trend"], d["signal"]), ("flat", "can wait"))
        self.assertEqual(d["signal_reason"], "Price steady and no deadline")

    def test_falling_can_wait(self):
        d = deal([snap(day(9), 1200), snap(day(6), 1150), snap(day(3), 1100), snap(day(0), 1050)])
        self.assertEqual((d["trend"], d["signal"]), ("falling", "can wait"))

    def test_trend_ignores_old_points(self):
        # a big rise 20+ days ago, flat for the last 14 days
        d = deal([snap(day(25), 700), snap(day(20), 1000), snap(day(12), 1000), snap(day(6), 1000), snap(day(0), 1000)])
        self.assertEqual(d["trend"], "flat")

    def test_too_little_history_is_watch(self):
        d = deal([snap(day(1), 1000), snap(day(0), 1000)])
        self.assertEqual((d["trend"], d["signal"]), ("unknown", "watch"))

    def test_expired_deadline_is_watch(self):
        d = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 1000, valid_until=day(1))])
        self.assertEqual(d["signal"], "watch")
        self.assertIn("passed", d["signal_reason"])

    def test_confidence_levels(self):
        low = deal([snap(day(0), 1000)])
        mid = deal([snap(day(2), 1000), snap(day(1), 1000), snap(day(0), 1000)])
        high = deal([snap(day(n), 1000) for n in (12, 10, 8, 6, 4, 2, 0)])
        self.assertEqual([low["confidence"], mid["confidence"], high["confidence"]], ["low", "medium", "high"])
        self.assertEqual(high["confidence_note"], "7 price checks over 7 days")

    def test_dashboard_fields_present(self):
        d = deal([snap(day(0), 1000)])
        for k in ("baseline_low", "baseline_median", "observations", "trend", "signal", "signal_reason",
                  "confidence", "confidence_note", "parts", "notes"):
            self.assertIn(k, d)


def rand_history(rng: random.Random) -> list[dict]:
    n = rng.randint(1, 8)
    days = sorted(rng.sample(range(0, 40), n), reverse=True)
    if days[-1] != 0:
        days[-1] = 0
    out = []
    for i, dd in enumerate(days):
        p = rng.uniform(600, 2400)
        was = p * rng.uniform(1.0, 1.6) if rng.random() < 0.5 else None
        vu = day(-rng.randint(-3, 40)) if i == len(days) - 1 and rng.random() < 0.5 else None
        out.append(snap(day(dd), round(p), was and round(was), vu))
    return out


class AdultsOnlyNeverOutranksFamilyOnPrice(unittest.TestCase):
    def test_deal_score_bound_over_random_histories(self):
        rng = random.Random(7)
        for _ in range(400):
            fam_hist, adult_hist = rand_history(rng), rand_history(rng)
            # same deadline + reach: only the prices differ
            adult_hist[-1]["valid_until"] = fam_hist[-1]["valid_until"]
            f = deal(fam_hist, occ="2+2")
            a = deal(adult_hist, occ="2+0", key="k2")
            self.assertLessEqual(a["score"], f["score"], (fam_hist, adult_hist))

    def test_rate_bound_same_hotel_including_fake_cap(self):
        rng = random.Random(11)
        for _ in range(200):
            fam = mk(rand_history(rng), occ="2+2", key="fam")
            adult = mk(rand_history(rng), occ="2+0", key="adult")
            peers = [fam, adult]
            rf = score.rate(HOTEL, fam, peers, CFG, 200, TODAY)
            ra = score.rate(HOTEL, adult, peers, CFG, 200, TODAY)
            self.assertLessEqual(ra["overall"], rf["overall"])

    def test_cheap_adults_only_held_at_family_score_with_reason(self):
        # well-verified hotel; its 2+2 price is a fake "discount" (capped at 54), the 2+0 price really fell
        h = dict(HOTEL, direct_flight_skp=True, family=dict(
            HOTEL["family"], cots_max=2, cot_age_max=5, family_room=True, kids_club=True, kids_pool=True,
            shallow_entry=True, doctor_near=True, stroller_ok=True,
            verified=["cots", "sand_beach", "beachfront", "family_room", "kids_club", "kids_pool", "shallow_entry"]))
        fam = mk([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 1100, was=1500)], occ="2+2", key="fam")
        adult = mk([snap(day(9), 1500), snap(day(5), 1500), snap(day(0), 900, was=1500)], occ="2+0", key="adult")
        alone = score.rate(h, adult, [adult], CFG, 200, TODAY)
        held = score.rate(h, adult, [fam, adult], CFG, 200, TODAY)
        rf = score.rate(h, fam, [fam, adult], CFG, 200, TODAY)
        self.assertEqual(rf["deal"]["verdict"], "fake?")
        self.assertGreater(alone["overall"], rf["overall"])   # without the rule it would outrank the 2+2
        self.assertEqual(held["overall"], rf["overall"])
        self.assertTrue(any("2+2 price for the same stay" in n for n in held["deal"]["notes"]))
        self.assertTrue(any("2 adults only" in n for n in held["deal"]["notes"]))

    def test_other_stays_are_not_comparable(self):
        adult = mk([snap(day(0), 900)], occ="2+0", key="adult")
        others = [mk([snap(day(0), 1)], key="b", board="BB"), mk([snap(day(0), 1)], key="n", nights=5),
                  mk([snap(day(0), 1)], key="d", check_in="2027-07-20"), mk([snap(day(0), 1)], key="h", hotel="h2")]
        self.assertEqual(score.comparable_family_offers(adult, others + [adult]), [])
        near = mk([snap(day(0), 1)], key="near", check_in="2027-06-25")
        self.assertEqual(score.comparable_family_offers(adult, [near, adult]), [near])

    def test_family_fit_ignores_occupancy_and_is_explained(self):
        a = score.family_fit(HOTEL, mk([snap(day(0), 1)], occ="2+0"), CFG, 200)
        f = score.family_fit(HOTEL, mk([snap(day(0), 1)], occ="2+2"), CFG, 200)
        self.assertEqual(a["score"], f["score"])
        self.assertEqual((a["price_covers_kids"], f["price_covers_kids"]), (False, True))
        self.assertAlmostEqual(sum(f["parts"].values()), f["raw"], delta=0.2)
        self.assertIn("beach", f["parts"])

    def test_deal_parts_add_up(self):
        d = deal([snap(day(6), 1000), snap(day(3), 1000), snap(day(0), 900, valid_until=day(-5))])
        self.assertAlmostEqual(sum(d["parts"].values()), d["score"], delta=0.2)


class BuildExportsSignal(unittest.TestCase):
    def test_items_carry_signal_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = db.connect(Path(tmp) / "t.db")
            db.upsert_hotel(con, HOTEL)
            for n, p in ((6, 1000), (3, 1000), (0, 900)):
                db.add_sighting(con, {"hotel": "h1", "source": "test", "url": "https://example.test/offer", "seen": day(n),
                                      "check_in": "2027-06-20", "nights": 7, "board": "HB", "room": "Family",
                                      "occupancy": "2+2", "price_eur": p, "was_eur": None, "valid_until": None})
            items, _ = run.build(con, CFG, TODAY, offline=True)
            con.close()
        d = items[0]["deal"]
        self.assertEqual((d["verdict"], d["baseline_low"], d["observations"], d["trend"]), ("real", 1000, 3, "falling"))
        self.assertEqual(d["signal"], "can wait")


class Digest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(digest.render([]), "")

    def test_grouped_by_type_with_signal(self):
        alerts = [
            {"icon": "👍", "url": "u1", "text": "New: A"},
            {"icon": "🏨", "url": "u2", "text": "New on B's own website: -20%"},
            {"icon": "⏰", "url": "u3", "text": "Offer ends in 2 days: C", "signal": "book now",
             "signal_reason": "Offer ends in 2 days and the price is at its 30-day low"},
            {"icon": "📉", "url": "u4", "text": "Price drop −9%: D", "signal": "can wait",
             "signal_reason": "Price falling"},
            {"icon": "⭐", "url": "u5", "text": "New: E", "signal": "watch", "signal_reason": "x"},
        ]
        out = digest.render(alerts)
        self.assertTrue(out.startswith("Family Deal Finder — 5 alerts, 1 to book now"))
        order = [out.index(t) for t in ("Ending soon (1)", "Price drops (1)", "New good deals (2)",
                                        "On hotels' own websites (1)")]
        self.assertEqual(order, sorted(order))
        self.assertIn("C → BOOK NOW: Offer ends in 2 days", out)
        self.assertIn("D → can wait: Price falling", out)
        self.assertNotIn("watch", out)                       # "watch" adds nothing to an email
        self.assertIn("   u3", out)

    def test_explicit_type_wins_and_long_groups_are_cut(self):
        alerts = [{"icon": "👍", "type": "drop", "text": f"Drop {i}", "url": None} for i in range(9)]
        out = digest.render(alerts, max_per_group=3)
        self.assertIn("Price drops (9)", out)
        self.assertEqual(out.count("Drop "), 3)
        self.assertIn("… and 6 more on the dashboard", out)

    def test_book_now_first_within_group(self):
        alerts = [{"icon": "👍", "text": "New: plain"}, {"icon": "👍", "text": "New: urgent", "signal": "book now"}]
        out = digest.render(alerts)
        self.assertLess(out.index("urgent"), out.index("plain"))


if __name__ == "__main__":
    unittest.main()
