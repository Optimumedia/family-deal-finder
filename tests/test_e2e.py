"""End-to-end: the whole `python -m trips.run` pipeline, offline, on saved fixtures.

sources (every AUTO_SOURCES module) -> merge -> enrich -> validate -> db -> hotel_direct -> build/score
-> export -> health. The network is replaced by tests.fakes.FakeSession (fixture files by URL
pattern) and a socket guard; the router by a straight-line stand-in. main() runs with the working
directory set to a temp folder, so data/trips.db, docs/data.json, docs/health.json, the enrich cache
and the health history are all temp files: the real ones are never read or written.
'today' is frozen at the day the fixtures were saved (25.11.2026).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from unittest import mock

from tests.fakes import EMPTY_LIST, FakeSession, no_network
from trips import db, geo, run
from trips.sources import hotel_direct, kopaonik

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 25)
# A made-up birthdate in the private-config slot: it must never reach any published file.
SECRET_BIRTHDATE = "2023-10-19"


class FrozenDate(date):
    @classmethod
    def today(cls):
        return TODAY


# URL pattern -> fixture. First match wins; anything else answers "" (like a 404).
ROUTES = [
    # Travelland: one Bansko list answer, then "past the end"; detail pages for enrich
    (r"travelland\.rs/services/list/(?=.*destination=e2e-tl-bansko)(?=.*[?&]paginate=1(?:&|$))",
     "travelland_list_bansko.json"),
    (r"travelland\.rs/services/list/", EMPTY_LIST),
    (r"travelland\.rs/smestaj/", "enrich_travelland_grandroyale.html"),
    # Olympic: Bansko + Kopaonik list answers; detail pages for enrich (winter / summer layout)
    (r"olympic\.rs/services/list/(?=.*destination=e2e-ol-bansko)(?=.*[?&]_page=1(?:&|$))", "olympic_list_bansko_p3.json"),
    (r"olympic\.rs/services/list/(?=.*destination=e2e-ol-kopaonik)(?=.*[?&]_page=1(?:&|$))", "olympic_list_kopaonik.json"),
    (r"olympic\.rs/services/list/", EMPTY_LIST),
    (r"olympic\.rs/zimovanje/", "enrich_olympic_grandbansko.html"),
    (r"olympic\.rs/letovanje/", "enrich_olympic_mediterranean.html"),
    # AtlantiS
    (r"atlantis\.mk/hotels/bansko", "mk_agencies_atlantis_bansko.html"),
    (r"atlantisonline\.mk/hotels/borovets", "mk_agencies_atlantis_borovets.html"),
    (r"atlantis\.mk/$", "mk_agencies_atlantis_home_menu.html"),
    # BulgariaSki: list + four hotel pages
    (r"bulgariaski\.com/bansko/hotels/$", "bgski_list_bansko.html"),
    (r"bulgariaski\.com/bansko/casa_karina", "bgski_casa_karina.html"),
    (r"bulgariaski\.com/bansko/pirin_golf", "bgski_pirin_golf.html"),
    (r"bulgariaski\.com/bansko/regnum", "bgski_regnum.html"),
    (r"bulgariaski\.com/bansko/royal_park", "bgski_royal_park.html"),
    # Savana Travel charters
    (r"savana\.travel/.*/antalya/.*/with-plane/2/", "charters_antalya_p2.html"),
    (r"savana\.travel/.*/antalya/", "charters_antalya.html"),
    (r"savana\.travel/.*/kusadasi/", "charters_kusadasi.html"),
    # Kopaonik: JAT price list + two unit pages, six Supernova price lists
    (r"jatapartmani\.com/en/price-list", "kopaonik_jat_price_list.html"),
    (r"jatapartmani\.com/en/accommodation/apartman-d", "kopaonik_jat_unit_d.html"),
    (r"jatapartmani\.com/en/accommodation/apartman-e", "kopaonik_jat_unit_e.html"),
    (r"supernovatravel\.rs/.*konaci", "kopaonik_sn_konaci.html"),
    (r"supernovatravel\.rs/.*cardaci", "kopaonik_sn_cardaci.html"),
    (r"supernovatravel\.rs/.*marija", "kopaonik_sn_marija.html"),
    (r"supernovatravel\.rs/.*srbijasume", "kopaonik_sn_srbijasume.html"),
    (r"supernovatravel\.rs/.*zvoncica", "kopaonik_sn_zvoncica.html"),
    (r"supernovatravel\.rs/.*stara-planina", "kopaonik_sn_stara_planina.html"),
    # villas / owner rentals
    (r"oliverstravels\.com/greece/halkidiki/", "oliver_halkidiki.html"),
    (r"clickstay\.com/greece/chalkidiki", "rentals_clickstay_chalkidiki.html"),
    (r"clickstay\.com/greece/nikiti", "rentals_clickstay_nikiti.html"),
    (r"micazu\.com/.*/bansko/comfortable-ski-retreat-51700/", "micazu_listing_bansko.html"),
    (r"micazu\.com/.*/bansko/$", "micazu_list_bansko.html"),
    # hotels' own offers pages
    (r"sani-resort\.com/offers", "direct_sani_offers.html"),
    (r"portocarras\.com/offers", "direct_portocarras_offers.html"),
    (r"saintivanrilski\.com/", "direct_stivanrilski_offers.html"),
]

# Every source that must land at least one offer in data.json (manual one is ours, see OFFERS_TOML).
EXPECTED_SOURCES = {"Travelland", "Olympic", "AtlantiS (MK)", "BulgariaSki", "Savana Travel",
                    *kopaonik.SOURCES.values(), "Oliver's Travels", "Clickstay", "Micazu (owner)", "E2E manual"}
# The keys the dashboard reads. Others may be added (checked as a subset, so new fields don't break this).
ITEM_KEYS = {"key", "hotel_id", "kind", "name", "stars", "area", "season", "lat", "lng", "notes", "drive_estimate",
             "image", "source", "url", "check_in", "nights", "board", "room", "occupancy", "price_eur", "was_eur",
             "discount_label", "valid_until", "first_seen", "last_seen", "history", "overall", "tier", "capped",
             "excluded", "family", "deal", "campaigns"}


def _pages(cfg: dict, name: str, *needles: str, **extra) -> list[dict]:
    """The real config.toml pages of a source whose url contains one of `needles`, so the e2e run
    keeps the production page settings (season, area, nights, check_in …) but only for fixtures we have."""
    pages = [p for p in cfg["sources"][name]["pages"] if any(n in p["url"] for n in needles)]
    assert pages, f"config.toml has no {name} page matching {needles}"
    return [{**p, **extra.get(p["url"], {})} for p in pages]


def e2e_config() -> dict:
    cfg = copy.deepcopy(run.load_config(ROOT / "config.toml", local=None))
    cfg["family"]["kids_birthdate"] = SECRET_BIRTHDATE      # as config.local.toml would set it
    cfg["email"]["enabled"] = False
    # Public APIs with live lookups (OSM geocoding, Open-Meteo/Overpass conditions) stay off: no network here.
    for key in ("geocode", "conditions"):
        if key in cfg:
            cfg[key]["enabled"] = False
    sc = cfg["sources"]
    sc["manual"] = True
    sc["travelland"]["pages"] = _pages(cfg, "travelland", "/bansko/", **{
        "https://www.travelland.rs/destinacije/bugarska/bansko/": {"destination": "e2e-tl-bansko"}})
    sc["olympic"]["pages"] = _pages(cfg, "olympic", "/bansko/", "/kopaonik-", **{
        "https://www.olympic.rs/zimovanje/bugarska/bansko/": {"destination": "e2e-ol-bansko"},
        "https://www.olympic.rs/zimovanje/srbija/kopaonik-zimovanje-skijanje/": {"destination": "e2e-ol-kopaonik"}})
    sc["mk_agencies"]["pages"] = _pages(cfg, "mk_agencies", "/bansko?", "/borovets?")
    sc["bgski"]["pages"] = _pages(cfg, "bgski", "/bansko/")
    sc["charters"]["pages"] = _pages(cfg, "charters", "/antalya/", "/kusadasi/")
    sc["kopaonik"]["pages"] = _pages(cfg, "kopaonik", "jatapartmani", "supernovatravel")
    sc["oliverstravels"]["pages"] = _pages(cfg, "oliverstravels", "/halkidiki/")
    sc["rentals"]["pages"] = _pages(cfg, "rentals", "/chalkidiki", "/nikiti")
    sc["micazu"]["pages"] = _pages(cfg, "micazu", "/bansko/")
    sc["hotel_direct"]["pages"] = _pages(cfg, "hotel_direct", "sani-resort", "portocarras", "saintivanrilski")
    sc["enrich"].update(enabled=True, budget=6, cache="data/enrich_cache.json")   # relative: inside the temp cwd
    return cfg


def _offers_toml(hotel_id: str) -> str:
    """One good manual offer and one that validate must reject (check-in in the past)."""
    good = (f'[[offer]]\nhotel = "{hotel_id}"\nsource = "E2E manual"\nurl = "https://example.test/a"\n'
            'seen = "2026-11-25"\ncheck_in = "2027-06-20"\nnights = 7\nboard = "HB"\nroom = "Family room"\n'
            'occupancy = "2+2"\nprice_eur = 1200\nwas_eur = 1500\ndiscount_label = "Early booking -20%"\n')
    bad = (f'[[offer]]\nhotel = "{hotel_id}"\nsource = "E2E manual"\nurl = "https://example.test/b"\n'
           'seen = "2026-11-25"\ncheck_in = "2026-01-10"\nnights = 7\nboard = "HB"\nroom = "Past room"\n'
           'occupancy = "2+2"\nprice_eur = 900\n')
    return good + "\n" + bad


def _fake_osrm(home, points):
    """Router stand-in: straight-line minutes as seconds, so drive times are cached like real ones."""
    return [geo.estimate_minutes(home, lat, lng) * 60 for lat, lng in points]


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.dir = Path(cls.tmp.name)
        (cls.dir / "data").mkdir()
        shutil.copy(ROOT / "data" / "hotels.toml", cls.dir / "data" / "hotels.toml")
        curated = run.manual.load_hotels(cls.dir / "data" / "hotels.toml")
        cls.summer_hotel = next(h["id"] for h in curated if h["season"] == "summer")
        (cls.dir / "data" / "offers.toml").write_text(_offers_toml(cls.summer_hotel), encoding="utf-8")
        cls.cfg = e2e_config()
        cls.sessions: list[FakeSession] = []
        real_out = ROOT / "docs" / "data.json"
        cls.real_mtime = real_out.stat().st_mtime if real_out.exists() else None
        cls.code = cls._run_main()
        cls.data = json.loads((cls.dir / "docs" / "data.json").read_text(encoding="utf-8"))
        cls.health = json.loads((cls.dir / "docs" / "health.json").read_text(encoding="utf-8"))
        cls.items = cls.data["items"]

    @classmethod
    def _run_main(cls, *argv: str) -> int:
        factory = FakeSession.factory(ROUTES, log=cls.sessions)
        env = {k: v for k, v in os.environ.items() if k != "ORS_API_KEY"}
        cons = []                                   # main() never closes its DB: we do (Windows locks it)

        def connect(*a, **kw):
            cons.append(real_connect(*a, **kw))
            return cons[-1]
        real_connect = db.connect
        quiet = logging.NullHandler()               # keep the run's warnings out of the test output
        logging.getLogger().addHandler(quiet)
        old = os.getcwd()
        os.chdir(cls.dir)
        try:
            with no_network(), \
                    mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch("logging.basicConfig"), \
                    mock.patch.object(run, "load_config", return_value=copy.deepcopy(cls.cfg)), \
                    mock.patch.object(run, "PoliteSession", factory), \
                    mock.patch("trips.enrich.PoliteSession", factory), \
                    mock.patch.object(run, "date", FrozenDate), \
                    mock.patch.object(geo, "_osrm", _fake_osrm),                     mock.patch.object(db, "connect", connect):
                return run.main(["--db", str(cls.dir / "data" / "trips.db"), *argv])
        finally:
            os.chdir(old)
            logging.getLogger().removeHandler(quiet)
            for c in cons:
                c.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---------------------------------------------------------------- data.json ---
    def test_exit_code_and_top_level_shape(self):
        self.assertEqual(self.code, 0, self.health.get("problems"))
        self.assertEqual(set(self.data), {"generated", "family", "alerts", "items"})
        self.assertEqual(set(self.data["family"]), {"adults", "kids", "home", "max_drive_minutes"})
        self.assertIsInstance(self.data["alerts"], list)
        self.assertGreater(len(self.items), 0)

    def test_every_item_has_full_shape_and_scores(self):
        for it in self.items:
            with self.subTest(key=it["key"]):
                self.assertFalse(ITEM_KEYS - set(it), "missing keys")
                self.assertTrue({"key", "icon"} <= set(it["tier"]), it["tier"])
                self.assertIsInstance(it["family"], dict)
                self.assertIsInstance(it["deal"], dict)
                self.assertIn("days_left", it["deal"])
                self.assertIsInstance(it["overall"], (int, float))
                self.assertGreater(it["price_eur"], 0)
                self.assertGreaterEqual(it["check_in"], TODAY.isoformat())
                self.assertTrue(it["history"])

    def test_every_source_lands_offers(self):
        counts = Counter(i["source"] for i in self.items)
        missing = {s for s in EXPECTED_SOURCES if not counts.get(s)}
        self.assertFalse(missing, f"no items from {missing}; got {dict(counts)}")

    def test_no_duplicate_keys(self):
        dupes = [k for k, n in Counter(i["key"] for i in self.items).items() if n > 1]
        self.assertEqual(dupes, [])

    def test_sorted_fitting_first_then_by_score(self):
        order = [(i["excluded"], -i["overall"]) for i in self.items]
        self.assertEqual(order, sorted(order))

    def test_hotel_direct_campaigns_become_alerts(self):
        camp = [a for a in self.data["alerts"] if a["type"] == "campaign"]
        self.assertTrue(camp, "no campaign alert from the hotels' own pages")

    # -------------------------------------------------------------- validation ---
    def test_validate_rejects_counted(self):
        self.assertNotIn("https://example.test/b", {i["url"] for i in self.items})
        self.assertIn("https://example.test/a", {i["url"] for i in self.items})
        rej = self.health["rejected_by_source"]
        self.assertGreaterEqual(rej.get("E2E manual", {}).get("rejected", 0), 1, rej)
        src = {s["name"]: s for s in self.health["sources"]}
        self.assertGreaterEqual(src["E2E manual"]["offers_rejected"], 1)

    # ------------------------------------------------------------------ health ---
    def test_health_written_for_every_source(self):
        self.assertTrue((self.dir / "data" / "health-history.json").exists())
        self.assertIn(self.health["status"], ("ok", "warn"))
        names = {s["name"] for s in self.health["sources"]}
        want = {getattr(m, "SOURCE", m.__name__) for m in run.AUTO_SOURCES} | {"Detail pages", hotel_direct.SOURCE}
        self.assertTrue(want <= names, want - names)
        by = {s["name"]: s for s in self.health["sources"]}
        for name in want:
            with self.subTest(source=name):
                self.assertNotIn(by[name]["status"], ("error", "blocked", "zero"), by[name])
                self.assertGreater(by[name]["offers_parsed"], 0, by[name])

    def test_health_counts_detail_pages(self):
        """Regression: enrich() must use the session main() tracks, or health says 0 detail pages."""
        by = {s["name"]: s for s in self.health["sources"]}
        self.assertGreater(by["Detail pages"]["pages_fetched"], 0)

    def test_enrich_ran_on_fixtures_and_cached_in_temp(self):
        cache = json.loads((self.dir / "data" / "enrich_cache.json").read_text(encoding="utf-8"))
        self.assertTrue(cache["pages"])
        detail = [u for s in self.sessions for u in s.urls if re.search(r"(olympic|travelland)\.rs/(zimovanje|letovanje|smestaj)/", u)]
        self.assertTrue(detail, "enrich never asked for a detail page")
        self.assertLessEqual(len(detail), self.cfg["sources"]["enrich"]["budget"])   # budget respected
        self.assertTrue(any(i["board"] != "?" for i in self.items if i["source"] in ("Olympic", "Travelland")))

    # ----------------------------------------------------------------- privacy ---
    def test_private_birthdate_never_published(self):
        secrets = {SECRET_BIRTHDATE}
        local = ROOT / "config.local.toml"
        if local.exists():                   # the real one too, when this runs on the owner's PC
            import tomllib
            real = tomllib.loads(local.read_text(encoding="utf-8")).get("family", {}).get("kids_birthdate")
            if real:
                secrets.add(str(real))
        for path in (self.dir / "docs").rglob("*"):
            text = path.read_text(encoding="utf-8")
            for s in secrets:
                self.assertNotIn(s, text, f"private birthdate leaked into {path.name}")
        self.assertNotIn("kids_birthdate", json.dumps(self.data))

    # ------------------------------------------------------------------ hermetic ---
    def test_real_outputs_untouched_and_no_live_requests(self):
        real_out = ROOT / "docs" / "data.json"
        self.assertEqual(real_out.stat().st_mtime if real_out.exists() else None, self.real_mtime)
        self.assertTrue(self.sessions, "FakeSession was never used")
        self.assertTrue(all(isinstance(s, FakeSession) for s in self.sessions))

    def test_offline_rerun_is_stable(self):
        """--offline on the same temp DB: no session at all, same offers, nothing new to alert."""
        before = len(self.sessions)
        code = self._run_main("--offline")
        self.assertEqual(code, 0)
        again = json.loads((self.dir / "docs" / "data.json").read_text(encoding="utf-8"))
        self.assertEqual(len(self.sessions), before)
        self.assertEqual(sorted(i["key"] for i in again["items"]), sorted(i["key"] for i in self.items))
        self.assertFalse([a for a in again["alerts"] if a["type"] == "new"])


if __name__ == "__main__":
    unittest.main()
