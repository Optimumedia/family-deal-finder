"""Hotel-level geocoding tests. Provider answers are hand-made in the shape of real Nominatim /
Photon / Overpass responses (26.11.2026). No network: a fake session records every request."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import geocode as gc

TODAY = date(2026, 11, 26)
BANSKO = (41.83, 23.48)
CFG = {"sources": {"olympic": {"pages": [{"area": "Bansko, Bulgaria", "lat": 41.83, "lng": 23.48}]}}}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class FakeSession:
    """Answers by host: nominatim → list, photon → FeatureCollection, overpass → elements."""

    def __init__(self, nominatim=None, photon=None, overpass=None, status=None):
        self.answers = {"nominatim": nominatim, "photon": photon, "overpass": overpass}
        self.status = status or {}
        self.calls = []

    def _answer(self, url, kw):
        host = next(h for h in self.answers if h in url)
        self.calls.append((host, kw))
        return Resp(self.answers[host] if self.answers[host] is not None else [], self.status.get(host, 200))

    def get(self, url, **kw):
        return self._answer(url, kw)

    def post(self, url, **kw):
        return self._answer(url, kw)


def nom(name, lat, lng, cls="tourism", typ="hotel", **names):
    return {"lat": str(lat), "lon": str(lng), "category": cls, "type": typ, "name": name, "osm_type": "node",
            "osm_id": 1, "display_name": f"{name}, Bansko, Bulgaria", "namedetails": {"name": name, **names}}


def photon(name, lat, lng, key="tourism", value="hotel"):
    return {"features": [{"geometry": {"coordinates": [lng, lat]},
                          "properties": {"name": name, "osm_key": key, "osm_value": value, "osm_type": "W",
                                         "osm_id": 9, "city": "Bansko", "country": "Bulgaria"}}]}


def hotel(name="Hotel Dumanov", hid="tl-1", kind="hotel", season="winter", **kw):
    return {"id": hid, "name": name, "area": "Bansko, Bulgaria", "country": "BG", "lat": BANSKO[0],
            "lng": BANSKO[1], "kind": kind, "season": season, "family": {"verified": []}, **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = str(Path(self.tmp.name) / "geocode_cache.json")
        self.cfg = {**CFG, "geocode": {"cache": self.cache, "delay_seconds": 0}}

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, hotels, session, today=TODAY, offline=False, **gcfg):
        cfg = {**self.cfg, "geocode": {**self.cfg["geocode"], **gcfg}}
        return gc.apply(hotels, cfg, today=today, offline=offline, session=session)


class Names(unittest.TestCase):
    def test_clean_name_drops_unit_stars_brackets(self):
        self.assertEqual(gc.clean_name("Apartmani Marija Lux – 2+1 Apartman"), "Apartmani Marija Lux")
        self.assertEqual(gc.clean_name("Grand Hotel Bansko 4*"), "Grand Hotel Bansko")
        self.assertEqual(gc.clean_name("Iceberg (ex Mura)"), "Iceberg")

    def test_town_of(self):
        self.assertEqual(gc.town_of("Nea Skioni, Kassandra, Halkidiki"), "Nea Skioni")
        self.assertEqual(gc.town_of("Olympic Riviera (Paralia, Leptokaria)"), "Olympic Riviera")
        self.assertEqual(gc.town_of("Ulcinj / Velika Plaža, Montenegro"), "Ulcinj")

    def test_transliteration(self):
        self.assertEqual(gc.latin("Хотел Думанов"), "hotel dumanov")
        self.assertEqual(gc.latin("ЈАТ апартмани"), "jat apartmani")
        self.assertIn("karras", gc.latin("Πόρτο Καρράς"))

    def test_name_matching(self):
        place = {"bansko", "bulgaria"}
        self.assertTrue(gc.name_matches("Hotel Dumanov", ["Хотел Думанов"], place))
        self.assertTrue(gc.name_matches("Sport Hotel Mpm", ["MPM Sport Hotel"], place))
        self.assertTrue(gc.name_matches("Green Life Bansko", ["Green Life Ski & Spa Resort"], place))
        self.assertTrue(gc.name_matches("Hotel Bansko", ["Хотел Банско"], place))     # only place words left
        self.assertFalse(gc.name_matches("Green Life Bansko", ["Bansko Royal Towers"], place))
        self.assertFalse(gc.name_matches("Grand Hotel Bansko", ["Grand Royale Apartment Complex & Spa"], place))
        self.assertFalse(gc.name_matches("Hotel", ["Hotel Lion"], place))


class Geometry(unittest.TestCase):
    def test_box_contains_radius(self):
        b = gc.box(*BANSKO, 15)
        self.assertLess(b[0], BANSKO[1])
        self.assertGreater(b[2], BANSKO[1])
        self.assertAlmostEqual(gc.km((b[1], BANSKO[1]), BANSKO), 15, delta=0.2)

    def test_beach_distance_from_outline(self):
        # beach outline ~110 m north of the hotel
        data = {"elements": [{"type": "way", "tags": {"natural": "beach", "surface": "sand"},
                              "geometry": [{"lat": 40.001, "lon": 23.499}, {"lat": 40.001, "lon": 23.501}]}]}
        m, surface = gc.beach_distance((40.0, 23.5), data)
        self.assertEqual((m, surface), (110, "sand"))
        self.assertEqual(gc.beach_distance((40.0, 23.5), {"elements": []}), (None, None))


class Pick(unittest.TestCase):
    def test_rejects_wrong_type_far_and_other_name(self):
        h = hotel()
        cands = [
            {"lat": 41.83, "lng": 23.48, "cls": "amenity", "type": "restaurant", "names": ["Dumanov"], "osm": "n/1", "label": ""},
            {"lat": 42.70, "lng": 23.32, "cls": "tourism", "type": "hotel", "names": ["Dumanov"], "osm": "n/2", "label": ""},
            {"lat": 41.82, "lng": 23.48, "cls": "tourism", "type": "hotel", "names": ["Kempinski"], "osm": "n/3", "label": ""},
            {"lat": 41.824, "lng": 23.486, "cls": "building", "type": "hotel", "names": ["Хотел Думанов"], "osm": "w/4", "label": ""},
        ]
        got = gc.pick(cands, h, BANSKO, 15)
        self.assertEqual(got["osm"], "w/4")
        self.assertLess(got["dist_km"], 1)


class Apply(Base):
    def test_hit_moves_hotel_and_is_cached(self):
        s = FakeSession(nominatim=[nom("Хотел Думанов", 41.8241, 23.4862, **{"name:en": "Hotel Dumanov"})])
        hs = {"tl-1": hotel()}
        st = self.run_apply(hs, s)
        self.assertEqual((hs["tl-1"]["lat"], hs["tl-1"]["lng"]), (41.8241, 23.4862))
        self.assertEqual(hs["tl-1"]["geo"]["via"], "nominatim")
        self.assertEqual(hs["tl-1"]["geo"]["resort"], [41.83, 23.48])
        self.assertEqual((st["hit"], st["moved"], st["requests"]), (1, 1, 1))
        host, kw = s.calls[0]
        p = kw["params"]
        self.assertEqual((p["bounded"], p["countrycodes"], p["q"]), (1, "bg", "Hotel Dumanov"))
        self.assertIn("family-deal-finder", kw["headers"]["User-Agent"])
        # next run: from the cache, no request
        s2 = FakeSession()
        hs2 = {"tl-1": hotel()}
        st2 = self.run_apply(hs2, s2)
        self.assertEqual((s2.calls, st2["cached_hit"], hs2["tl-1"]["lat"]), ([], 1, 41.8241))

    def test_offline_uses_cache_only_and_never_writes(self):
        s = FakeSession(nominatim=[nom("Dumanov", 41.8241, 23.4862)])
        hs = {"tl-1": hotel()}
        self.run_apply(hs, s, offline=True)
        self.assertEqual((s.calls, hs["tl-1"]["lat"]), ([], BANSKO[0]))
        self.assertFalse(Path(self.cache).exists())

    def test_photon_fallback(self):
        s = FakeSession(nominatim=[], photon=photon("Hotel Iceberg", 41.83, 23.49))
        hs = {"tl-1": hotel("Iceberg")}
        self.run_apply(hs, s)
        self.assertEqual(hs["tl-1"]["geo"]["via"], "photon")
        self.assertEqual([c[0] for c in s.calls], ["nominatim", "photon"])
        self.assertIn("Iceberg", s.calls[1][1]["params"]["q"])
        self.assertIn("Bansko", s.calls[1][1]["params"]["q"])

    def test_far_result_is_a_miss_retried_after_30_days(self):
        far = [nom("Dumanov", 41.70, 23.70)]                 # ~23 km away
        s = FakeSession(nominatim=far, photon={"features": []})
        hs = {"tl-1": hotel()}
        st = self.run_apply(hs, s)
        self.assertEqual((st["miss"], hs["tl-1"]["lat"]), (1, BANSKO[0]))
        entry = json.loads(Path(self.cache).read_text(encoding="utf-8"))["entries"]["tl-1@41.8300,23.4800"]
        self.assertEqual(entry["status"], "miss")
        self.assertAlmostEqual(entry["rejected"][0]["km"], 23.3, delta=0.5)
        s2 = FakeSession(nominatim=far)
        self.run_apply({"tl-1": hotel()}, s2, today=date(2026, 12, 20))
        self.assertEqual(s2.calls, [])                          # fresh miss: not asked again
        s3 = FakeSession(nominatim=[nom("Dumanov", 41.8241, 23.4862)])
        hs3 = {"tl-1": hotel()}
        self.run_apply(hs3, s3, today=date(2026, 12, 27))      # 31 days later: retried, now found
        self.assertEqual(hs3["tl-1"]["lat"], 41.8241)

    def test_wider_area_radius(self):
        s = FakeSession(nominatim=[nom("Dumanov", 41.70, 23.70)])
        hs = {"tl-1": hotel()}
        self.run_apply(hs, s, area_km={"Bansko": 30})
        self.assertEqual(hs["tl-1"]["lat"], 41.70)

    def test_budget_and_scope(self):
        s = FakeSession(nominatim=[], photon={"features": []})
        hs = {f"h{i}": hotel(f"Hotel Number{i}", hid=f"h{i}") for i in range(5)}
        hs["villa"] = hotel("Villa Rosa", hid="villa", kind="villa")
        hs["curated"] = hotel("Hotel Curated", hid="curated")
        hs["pinned"] = {**hotel("Pinned", hid="pinned"), "lat": 41.8201, "lng": 23.4777}   # own pin already
        st = gc.apply(hs, {**self.cfg, "geocode": {**self.cfg["geocode"], "budget": 4}}, today=TODAY,
                      session=s, skip={"curated"})
        self.assertEqual(len(s.calls), 4)                      # 2 hotels × (nominatim + photon)
        self.assertEqual((st["miss"], st["skipped_budget"]), (2, 3))
        asked = {c[1]["params"]["q"].split()[1] for c in s.calls}
        self.assertNotIn("Rosa", asked)
        self.assertNotIn("Curated", asked)
        self.assertNotIn("Pinned", asked)

    def test_rate_limit_stops_host_and_caches_nothing(self):
        s = FakeSession(nominatim=[], photon={"features": []}, status={"nominatim": 429, "photon": 429})
        hs = {"a": hotel(hid="a"), "b": hotel("Hotel Other", hid="b")}
        st = self.run_apply(hs, s)
        self.assertEqual(len(s.calls), 2)                      # one try per host, then left alone
        self.assertEqual(st["miss"], 0)
        self.assertEqual(json.loads(Path(self.cache).read_text(encoding="utf-8"))["entries"], {})

    def test_beach_estimate_flagged_and_optional_fill(self):
        beach = {"elements": [{"type": "way", "tags": {"natural": "beach", "surface": "sand"},
                               "geometry": [{"lat": 41.8251, "lon": 23.4850}, {"lat": 41.8251, "lon": 23.4875}]}]}
        s = FakeSession(nominatim=[nom("Dumanov", 41.8241, 23.4862)], overpass=beach)
        hs = {"tl-1": hotel(season="summer")}
        self.run_apply(hs, s, beach=True)
        self.assertEqual(hs["tl-1"]["geo"]["beach_m"], 110)
        self.assertIsNone(hs["tl-1"]["family"].get("beach_m"))   # not a stated fact unless asked
        s2 = FakeSession()
        hs2 = {"tl-1": hotel(season="summer")}
        self.run_apply(hs2, s2, beach=True, fill_beach_m=True)   # beach answer is cached too
        self.assertEqual(s2.calls, [])
        self.assertEqual((hs2["tl-1"]["family"]["beach_m"], hs2["tl-1"]["family"]["beach_m_estimate"]), (110, True))

    def test_disabled(self):
        s = FakeSession()
        self.assertEqual(self.run_apply({"tl-1": hotel()}, s, enabled=False), {"enabled": False})
        self.assertEqual(s.calls, [])
        self.assertEqual(gc.apply({"tl-1": hotel()}, CFG, session=s), {"enabled": False})   # no [geocode] block

    def test_resort_points_from_config(self):
        self.assertEqual(gc.resort_points(CFG), {(41.83, 23.48)})


if __name__ == "__main__":
    unittest.main()
