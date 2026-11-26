"""Area conditions (sea / snow climatology + OSM family places). Saved and hand-made API answers, no network."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import conditions as c

FIX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 26)


def _hourly(start_month: int, days: int, value_fn, key: str, year: int = 2025) -> dict:
    times, vals = [], []
    for d in range(days):
        for h in range(24):
            times.append(f"{year}-{start_month:02d}-{d + 1:02d}T{h:02d}:00")
            vals.append(value_fn(d, h))
    return {"hourly": {"time": times, key: vals}}


ITEMS = [
    {"season": "summer", "area": "Kassandra, Halkidiki", "lat": 40.02, "lng": 23.43, "check_in": "2027-06-20"},
    {"season": "summer", "area": "Kassandra, Halkidiki (villa)", "lat": 40.04, "lng": 23.45, "check_in": "2027-07-01"},
    {"season": "summer", "area": "Ohrid, North Macedonia", "lat": 41.117, "lng": 20.802, "check_in": "2027-06-20"},
    {"season": "winter", "area": "Bansko, Bulgaria", "lat": 41.83, "lng": 23.48, "check_in": "2027-01-10"},
    {"season": "winter", "area": "Bansko, Bulgaria", "lat": None, "lng": None, "check_in": "2027-01-10"},
]


class FakeFetch:
    """Answers like Open-Meteo / Overpass, from fixtures; counts calls."""

    def __init__(self):
        self.calls = []
        self.overpass = json.loads((FIX / "conditions_overpass_borovets.json").read_text(encoding="utf-8"))

    def __call__(self, url, params, body):
        self.calls.append((url, params, body))
        if body is not None:
            return self.overpass
        lats = params["latitude"].split(",")
        lngs = params["longitude"].split(",")
        m = int(params["start_date"][5:7])
        out = []
        for la, lo in zip(lats, lngs):
            la, lo = float(la), float(lo)
            if "marine" in url:
                if abs(la - 41.117) < 0.01:          # Ohrid: nearest sea cell is the Adriatic, far away
                    out.append({"latitude": 41.0, "longitude": 19.4, "hourly": {"time": [], "sea_surface_temperature": []}})
                else:
                    r = _hourly(7, 3, lambda d, h: 25.0 + d, "sea_surface_temperature")   # July: 25, 26, 27
                    r["hourly"]["time"] = ["2025-06-01T00:00"] * 24 + r["hourly"]["time"]
                    r["hourly"]["sea_surface_temperature"] = [21.0] * 24 + r["hourly"]["sea_surface_temperature"]
                    out.append({"latitude": la + 0.02, "longitude": lo - 0.03, **r})
            elif m == 6:
                out.append({"latitude": la, "longitude": lo, "daily": {
                    "time": ["2025-06-01", "2025-06-02", "2025-07-01"], "temperature_2m_max": [28, 30, 33],
                    "temperature_2m_mean": [23, 25, 27], "sunshine_duration": [36000, 43200, 46800],
                    "precipitation_sum": [0, 3.2, 0]}})
            else:
                r = _hourly(1, 2, lambda d, h: 0.5 if d == 0 else 0.1, "snow_depth", 2025)
                r["daily"] = {"time": ["2025-01-01", "2025-01-02"], "temperature_2m_mean": [-3, -1],
                              "temperature_2m_min": [-8, -6], "temperature_2m_max": [1, 3], "snowfall_sum": [10, 0]}
                out.append({"latitude": la, "longitude": lo, **r})
        return out if len(out) > 1 else out[0]


class AreaTest(unittest.TestCase):
    def test_area_key_drops_villa_tag(self):
        self.assertEqual(c.area_key("summer", "Kassandra, Halkidiki (villa)"), c.area_key("summer", "Kassandra,  Halkidiki"))
        self.assertNotEqual(c.area_key("summer", "Bansko"), c.area_key("winter", "Bansko"))

    def test_areas_from_items_median_and_skip_missing_coords(self):
        a = c.areas_from_items(ITEMS)
        self.assertEqual(len(a), 3)
        k = a["summer|kassandra, halkidiki"]
        self.assertAlmostEqual(k["lat"], 40.03)
        self.assertEqual(a["winter|bansko, bulgaria"]["hotels"], 1)

    def test_season_ranges_last_complete(self):
        self.assertEqual(c.season_ranges("summer", TODAY), [("2024-06-01", "2024-09-30"), ("2025-06-01", "2025-09-30"),
                                                             ("2026-06-01", "2026-09-30")])
        self.assertEqual(c.season_ranges("winter", TODAY)[-1], ("2025-11-01", "2026-03-31"))
        self.assertEqual(c.season_ranges("summer", date(2026, 7, 1))[-1], ("2025-06-01", "2025-09-30"))


class SummaryTest(unittest.TestCase):
    def test_summer(self):
        f = FakeFetch()
        arch = f(c.ARCHIVE_URL, {"latitude": "40", "longitude": "23", "start_date": "2025-06-01"}, None)
        mar = f(c.MARINE_URL, {"latitude": "40", "longitude": "23", "start_date": "2025-06-01"}, None)
        s = c.summarize_summer([arch], [mar])
        self.assertEqual(s["06"]["sea_c"], 21.0)
        self.assertFalse(s["06"]["sea_ok"])
        self.assertEqual(s["07"]["sea_c"], 26.0)
        self.assertTrue(s["07"]["sea_ok"])
        self.assertEqual(s["06"]["air_max_c"], 29.0)
        self.assertEqual(s["06"]["sun_h"], 11.0)
        self.assertEqual(s["06"]["rain_days"], 15)
        self.assertNotIn("08", s)

    def test_summer_without_sea(self):
        s = c.summarize_summer([{"daily": {"time": ["2025-06-01"], "temperature_2m_max": [30]}}], [None])
        self.assertIsNone(s["06"]["sea_c"])
        self.assertIsNone(s["06"]["sea_ok"])

    def test_winter_snow_depth_from_daily_max(self):
        f = FakeFetch()
        w = c.summarize_winter([f(c.ARCHIVE_URL, {"latitude": "41", "longitude": "23", "start_date": "2024-11-01"}, None)])
        j = w["01"]
        self.assertEqual(j["snow_depth_cm"], 30)          # (50 + 10) / 2
        self.assertEqual(j["snow_sure_pct"], 50)
        self.assertEqual(j["snowfall_cm"], 150)           # 5 cm/day x 30
        self.assertEqual(j["air_min_c"], -7.0)

    def test_places_from_saved_overpass(self):
        """Real answers of 26.11.2026 for Borovets (winter) and Kassandra (summer)."""
        resp = json.loads((FIX / "conditions_overpass_borovets.json").read_text(encoding="utf-8"))
        p = c.summarize_places(resp, 42.266, 23.606, "winter")
        self.assertEqual(set(c.PLACE_KEYS["winter"]) | {"hospital_km", "hospital_name"}, set(p))
        self.assertEqual((p["novice_pistes"], p["magic_carpets"], p["pharmacies"]), (24, 1, 2))
        self.assertEqual(p["hospital_km"], 8.9)
        resp = json.loads((FIX / "conditions_overpass_kassandra.json").read_text(encoding="utf-8"))
        k = c.summarize_places(resp, 40.02, 23.43, "summer")
        self.assertNotIn("novice_pistes", k)
        self.assertEqual(k["pharmacies"], 5)
        self.assertNotIn("AED", k["hospital_name"] or "")

    def test_defibrillator_tagged_hospital_is_skipped(self):
        resp = {"elements": [{"type": "node", "lat": 40.0, "lon": 23.0, "tags": {"amenity": "hospital", "name": "AED POINT"}},
                             {"type": "way", "center": {"lat": 40.1, "lon": 23.0}, "tags": {"amenity": "hospital", "name": "Health centre"}}]}
        p = c.summarize_places(resp, 40.0, 23.0, "summer")
        self.assertEqual(p["hospital_name"], "Health centre")
        self.assertAlmostEqual(p["hospital_km"], 11.1, places=1)

    def test_real_open_meteo_answers(self):
        """One location cut from the real archive (winter 2024/25, Bansko) and marine (summer 2025, Kassandra) answers."""
        w = c.summarize_winter([json.loads((FIX / "conditions_archive_bansko_2024_25.json").read_text(encoding="utf-8"))])
        self.assertEqual(sorted(w), ["01", "02", "03", "11", "12"])
        self.assertLess(w["01"]["air_mean_c"], 5)
        self.assertGreaterEqual(w["01"]["snow_depth_cm"], 0)
        s = c.summarize_summer([], [json.loads((FIX / "conditions_marine_kassandra_2025.json").read_text(encoding="utf-8"))])
        self.assertLess(s["06"]["sea_c"], s["08"]["sea_c"])
        self.assertTrue(s["08"]["sea_ok"])

    def test_overpass_query_shape(self):
        q = c.overpass_query(41.83, 23.48, "winter")
        self.assertTrue(q.startswith("[out:json][timeout:60]"))
        self.assertEqual(q.count("out count;"), len(c.PLACE_KEYS["winter"]))
        self.assertIn('"piste:difficulty"="novice"', q)
        self.assertEqual(c.overpass_query(40, 23, "summer").count("out count;"), len(c.PLACE_KEYS["summer"]))


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "conditions_cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_batches_requests_caches_and_attaches(self):
        f = FakeFetch()
        info = c.update(ITEMS, {}, TODAY, fetch=f, path=self.path)
        # summer: 3 years x (archive + marine); winter: 3 years x archive; Overpass: 3 areas
        self.assertEqual(len(f.calls), 6 + 3 + 3)
        self.assertEqual(set(info), {"summer|kassandra, halkidiki", "summer|ohrid, north macedonia", "winter|bansko, bulgaria"})
        self.assertIsNone(info["summer|ohrid, north macedonia"]["climate"]["06"]["sea_c"])   # lake, no sea
        items = [dict(i) for i in ITEMS]
        self.assertEqual(c.attach(items, info), 5)        # the hotel without coords still gets its area's info
        july = items[1]["area_info"]
        self.assertEqual(july["month"], "07")
        self.assertTrue(july["sea_ok"])
        self.assertTrue(any("warm for toddlers" in x for x in july["toddler_flags"]))
        self.assertEqual(items[3]["area_info"]["month"], "01")
        # second run within a month: nothing live
        f2 = FakeFetch()
        again = c.update(ITEMS, {}, date(2026, 12, 10), fetch=f2, path=self.path)
        self.assertEqual(f2.calls, [])
        self.assertEqual(again, info)
        # a month later: refreshed
        f3 = FakeFetch()
        c.update(ITEMS, {}, date(2027, 1, 5), fetch=f3, path=self.path)
        self.assertEqual(len(f3.calls), 12)

    def test_offline_uses_cache_only(self):
        c.update(ITEMS, {}, TODAY, fetch=FakeFetch(), path=self.path)
        f = FakeFetch()
        info = c.update(ITEMS, {}, TODAY, offline=True, fetch=f, path=self.path)
        self.assertEqual(f.calls, [])
        self.assertEqual(len(info), 3)

    def test_budget_stops_and_keeps_what_it_has(self):
        class Capped(FakeFetch):
            made = 0

            def __call__(self, url, params, body):
                if len(self.calls) >= 7:
                    raise c.Budget("cap")
                return super().__call__(url, params, body)
        info = c.update(ITEMS, {}, TODAY, fetch=Capped(), path=self.path)
        self.assertIn("climate", info["summer|kassandra, halkidiki"])
        self.assertNotIn("winter|bansko, bulgaria", info)          # its climate call hit the cap
        self.assertTrue(self.path.exists())

    def test_nearby_areas_share_one_overpass_query(self):
        items = ITEMS[:1] + [{"season": "summer", "area": "Hanioti", "lat": 40.025, "lng": 23.435, "check_in": "2027-06-20"}]
        f = FakeFetch()
        c.update(items, {}, TODAY, fetch=f, path=self.path)
        self.assertEqual(sum(1 for u, p, b in f.calls if b is not None), 1)

    def test_api_failure_does_not_raise(self):
        import requests

        def boom(url, params, body):
            raise requests.RequestException("down")
        self.assertEqual(c.update(ITEMS, {}, TODAY, fetch=boom, path=self.path), {})


class FlagsTest(unittest.TestCase):
    def test_winter_and_hospital_flags(self):
        f = c.flags("winter", {"snow_sure_pct": 20, "air_max_c": -1.0}, {"magic_carpets": 2, "hospital_km": 31.0})
        self.assertEqual(f, ["below freezing all day (-1°C max)", "magic carpet (kids' ski lift) nearby", "hospital 31 km away"])
        self.assertEqual(c.flags("summer", {"sea_ok": False, "sea_c": 22.4, "air_max_c": 34}, {}),
                         ["sea 22°C: cool for toddlers", "hot (34°C afternoons)"])
        self.assertIsNone(c.info_for(None, "2027-06-01"))


if __name__ == "__main__":
    unittest.main()
