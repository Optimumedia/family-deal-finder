"""Detail-page enrichment tests on saved Olympic / Travelland hotel pages (25.11.2026). No network."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from trips import enrich as en
from trips import run
from trips.http import Blocked

FIX = Path(__file__).parent / "fixtures"
CFG = run.load_config(Path(__file__).resolve().parents[1] / "config.toml", local=None)
TODAY = date(2026, 11, 25)

URLS = {
    "mediterranean": "https://www.olympic.rs/letovanje/grcka/paralia-katerini/hotel-mediterranean-resort/102986/",
    "porfi": "https://www.olympic.rs/letovanje/grcka/nikiti/hotel-porfi-beach/102872/",
    "grandbansko": "https://www.olympic.rs/zimovanje/bugarska/bansko/hotel-grand-hotel-bansko/115313/",
    "grandroyale": "https://www.travelland.rs/smestaj/bugarska/bansko/hotel-grand-royale-apart-hotel-spa/111164/",
    "adults": "https://www.travelland.rs/smestaj/bugarska/bansko/hotel-elida/113685/",
}
FILES = {"mediterranean": "enrich_olympic_mediterranean.html", "porfi": "enrich_olympic_porfi.html",
         "grandbansko": "enrich_olympic_grandbansko.html", "grandroyale": "enrich_travelland_grandroyale.html"}

# Hand-made page in Travelland's layout, using the wording of the live Hotel Elida page
# (adults-only, one board), so the single-board path is covered without a 5th fixture.
ADULTS_ONLY = """<html><body><nav>PORODIČNI POPUSTI</nav><h1 class="mb-0 me-2"> Hotel ELIDA </h1>
<div><p>HOTEL SAMO ZA ODRASLE 12+ godina</p>
<p>Položaj : Hotel Elida je namenjen osobama koje imaju min 12 god. i više. Udaljen je oko 700m od gondole.</p>
<p>Usluga : Noćenje sa doručkom na bazi švedskog stola - samoposluživanje.</p></div>
<h5>Udaljenosti</h5><div class="row"><div class="col">Centar</div><div class="col-auto">700 m</div></div>
<div class="container"><h3>Moglo bi vam se sviđati</h3><div>Hotel Pirin Polupansion dečiji klub</div></div>
<footer>x</footer></body></html>"""


def page(name):
    return ADULTS_ONLY if name == "adults" else (FIX / FILES[name]).read_text(encoding="utf-8")


def facts(name):
    return en.extract(page(name), URLS[name])


class Boards(unittest.TestCase):
    def test_board_words(self):
        self.assertEqual(en.board_codes("Noćenje sa doručkom ili polupansion (doručak i večera)"), ["HB", "BB"])
        self.assertEqual(en.board_codes("Polupansion"), ["HB"])
        self.assertEqual(en.board_codes("BB – bed and breakfast"), ["BB"])
        self.assertEqual(en.board_codes("All inclusive"), ["AI"])
        self.assertEqual(en.board_codes("Pun pansion"), ["FB"])
        self.assertEqual(en.board_codes("Noćenje i doručak"), ["BB"])
        self.assertEqual(en.board_codes("Najam"), ["RO"])
        self.assertEqual(en.board_codes("švedski sto"), [])


class Extract(unittest.TestCase):
    def test_mediterranean_beach_kids_and_child_policy(self):
        f = facts("mediterranean")
        self.assertEqual(f["source"], "olympic")
        self.assertEqual(f["hotel_name"], "Hotel Mediterranean Resort")
        self.assertEqual(f["board_options"], ["BB", "HB"])            # two boards: offer board stays "?"
        fam = f["family"]
        self.assertEqual(fam["beach_m"], 80)
        self.assertTrue(fam["kids_pool"] and fam["playground"] and fam["half_board"])
        self.assertEqual(fam["first_child_free_max_age"], 2)          # "Popust za 1 dete (0 - 2)" 100 %
        self.assertNotIn("kids_free_max_age", fam)                    # only the 1st child is stated
        self.assertNotIn("sand_beach", fam)                           # "zlatna plaža" is not a beach type
        self.assertNotIn("kids_club", fam)
        rule = next(r for r in f["child_policy"] if r["age_to"] == 11)
        self.assertEqual((rule["kind"], rule["child"], rule["age_from"], rule["pct"]), ("discount", 1, 3, 50))
        row = f["price_table"][0]
        self.assertEqual((row["room"], row["board"], row["from"], row["to"]),
                         ("Economy Room Ground Floor", "BB", "2027-04-23", "2027-04-28"))
        self.assertEqual((row["price"], row["was"], row["min_nights"], row["valid_until"]),
                         (31.41, 41.88, 3, "2026-11-30"))
        self.assertEqual({r["board"] for r in f["price_table"]}, {"BB", "HB"})

    def test_porfi_rooms_and_beachfront(self):
        f = facts("porfi")
        fam = f["family"]
        self.assertEqual(fam["beach_m"], 10)
        self.assertTrue(fam["beachfront"] and fam["kids_animation"] and fam["kids_pool"])
        self.assertTrue(fam["separate_bedroom"])
        self.assertIn("Family Suite", f["evidence"]["separate_bedroom"])
        rooms = {r["name"]: r for r in f["rooms"]}
        self.assertTrue(rooms["Family Suite"]["separate_bedroom"])
        self.assertIsNone(rooms["Junior Suite"]["separate_bedroom"])  # "kombinovani dnevni boravak-spavaća soba"
        self.assertIsNone(rooms["Promo room"]["separate_bedroom"])
        self.assertTrue(rooms["Junior Suite"]["family"])
        self.assertNotIn("kids_club", fam)                            # animation is not a kids' club
        sup = next(r for r in f["child_policy"] if r["kind"] == "supplement")
        self.assertEqual((sup["child"], sup["age_from"], sup["age_to"]), (2, 2, 11))
        self.assertLess(sup["eur_min"], sup["eur_max"])

    def test_grand_bansko_two_boards_kids_club_and_family_prices(self):
        f = facts("grandbansko")
        self.assertEqual(f["board_options"], ["HB", "AI"])            # "polupansion … ili All Inclusive"
        fam = f["family"]
        self.assertTrue(fam["kids_club"] and fam["kids_pool"] and fam["separate_bedroom"])
        self.assertTrue(fam["price_2plus2_listed"])
        self.assertNotIn("beach_m", fam)
        self.assertEqual([r["name"] for r in f["rooms"]], ["1-BED ROOM APARTAMENT", "DELUXE ROOM", "EXECUTIVE ROOM"])
        twins = [r for r in f["price_table"] if (r["occupancy"] or {}).get("kid_ages") == "0-5 i 0-5"]
        self.assertTrue(twins)
        first = twins[0]
        self.assertEqual((first["room"], first["from"], first["to"], first["price"], first["was"]),
                         ("1-BED ROOM APARTAMENT", "2026-12-01", "2026-12-24", 326.5, 408.12))
        self.assertEqual(first["unit"], "po jedinici po danu")

    def test_grand_royale_travelland_rooms(self):
        f = facts("grandroyale")
        self.assertEqual(f["source"], "travelland")
        self.assertEqual(f["board_options"], ["BB", "HB"])
        fam = f["family"]
        self.assertTrue(fam["kids_club"] and fam["playroom"] and fam["kids_welcome"] and fam["separate_bedroom"])
        self.assertEqual(f["distances"], {"Skijalište": 600})
        r = {x["name"]: x for x in f["rooms"]}
        self.assertEqual((r["1 BEDROOM APARTMENT"]["max_persons"], r["1 BEDROOM APARTMENT"]["from_eur"],
                          r["1 BEDROOM APARTMENT"]["was_eur"]), (4, 73.0, 81.0))
        self.assertTrue(r["2 BEDROOM APARTMENT"]["separate_bedroom"])
        self.assertEqual(f["price_table"], [])                         # Travelland loads its price list later

    def test_adults_only_and_scope(self):
        f = facts("adults")
        self.assertEqual(f["board_options"], ["BB"])
        self.assertEqual(f["family"], {"adults_only": True, "adults_only_min_age": 12})
        self.assertNotIn("Hotel Pirin", " ".join(en.lines_of(en.scope(ADULTS_ONLY))))

    def test_beach_type_words(self):
        sand = '<h1>H</h1><p>Hotel je na 50 m od peščane plaže.</p>'
        pebble = '<h1>H</h1><p>Plaža je šljunkovita.</p>'
        mixed = '<h1>H</h1><p>Plaža je od peska i sitnog šljunka.</p>'
        self.assertEqual(en.extract(sand)["family"], {"beach_m": 50, "beach_type": "sand", "sand_beach": True})
        self.assertEqual(en.extract(pebble)["family"], {"beach_type": "pebble", "sand_beach": False})
        self.assertEqual(en.extract(mixed)["family"], {"beach_type": "mixed"})
        free = '<h1>H</h1><p>Deca do 2 godine borave besplatno.</p>'
        self.assertEqual(en.extract(free)["family"], {"kids_free_max_age": 2})


class Enrich(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "enrich_cache.json"
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        name = next(k for k, u in URLS.items() if u == url)
        return page(name)

    def data(self):
        hotels = [
            {"id": "ol-102986", "season": "summer", "family": {"verified": []}},
            {"id": "xenios", "season": "summer", "family": {"beach_m": 20, "verified": ["beach_m"]}},  # curated
            {"id": "tl-113685", "season": "winter", "family": {"verified": []}},
            {"id": "manual", "season": "summer", "family": {"verified": []}},
        ]
        offers = [
            {"hotel": "ol-102986", "url": URLS["mediterranean"], "board": "?", "source": "Olympic"},
            {"hotel": "xenios", "url": URLS["mediterranean"] + "?x=1", "board": "?", "source": "Olympic"},
            {"hotel": "tl-113685", "url": URLS["adults"], "board": "?", "source": "Travelland"},
            {"hotel": "manual", "url": "https://www.fibula.com.mk/x", "board": "?", "source": "Fibula (manual)"},
        ]
        return hotels, offers

    def test_fills_unknown_facts_and_single_board_only(self):
        hotels, offers = self.data()
        st = en.enrich(offers, hotels, CFG, TODAY, budget=5, cache_path=self.cache, fetch=self.fetch)
        self.assertEqual(st["fetched"], 2)                    # same page for two offers = one read
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("https://www.fibula.com.mk/x", self.calls)
        h = {x["id"]: x for x in hotels}
        self.assertEqual(h["ol-102986"]["family"]["beach_m"], 80)
        self.assertEqual(h["ol-102986"]["family"]["verified"], [])
        self.assertEqual(h["ol-102986"]["enriched"]["board_options"], ["BB", "HB"])
        self.assertEqual(h["xenios"]["family"]["beach_m"], 20)          # curated value kept
        self.assertTrue(h["xenios"]["family"]["kids_pool"])            # unknown one filled
        self.assertEqual(h["xenios"]["family"]["verified"], ["beach_m"])
        self.assertTrue(h["tl-113685"]["family"]["adults_only"])
        self.assertEqual([o["board"] for o in offers], ["?", "?", "BB", "?"])
        self.assertEqual(offers[2]["board_from"], "detail page")
        saved = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertIn("olympic.rs/letovanje/grcka/paralia-katerini/hotel-mediterranean-resort/102986/", saved["pages"])

    def test_cache_weekly_and_budget(self):
        hotels, offers = self.data()
        en.enrich(offers, hotels, CFG, TODAY, budget=1, cache_path=self.cache, fetch=self.fetch)
        self.assertEqual(len(self.calls), 1)                  # budget 1: the other page waits
        hotels, offers = self.data()
        st = en.enrich(offers, hotels, CFG, TODAY + timedelta(days=1), budget=5, cache_path=self.cache,
                       fetch=self.fetch)
        self.assertEqual((st["fresh_cache"], st["fetched"]), (1, 1))
        self.assertEqual(len(self.calls), 2)
        hotels, offers = self.data()
        st = en.enrich(offers, hotels, CFG, TODAY + timedelta(days=3), budget=5, cache_path=self.cache,
                       fetch=self.fetch)
        self.assertEqual((st["fetched"], st["fresh_cache"]), (0, 2))   # nothing re-read within the week
        self.assertEqual(offers[2]["board"], "BB")                     # facts still applied from cache
        hotels, offers = self.data()
        st = en.enrich(offers, hotels, CFG, TODAY + timedelta(days=8), budget=0, cache_path=self.cache,
                       fetch=self.fetch)
        self.assertEqual((st["fetched"], st["stale_cache"]), (0, 2))   # stale, no budget: old facts used
        self.assertEqual(hotels[0]["family"]["beach_m"], 80)
        st = en.enrich(offers, hotels, CFG, TODAY + timedelta(days=8), budget=5, cache_path=self.cache,
                       fetch=self.fetch)
        self.assertEqual(st["fetched"], 2)                             # a week old: re-read

    def test_family_prices_added(self):
        """2+2 rows → extra 2+2 offers; "?" boards → board_cheapest; summary kept on the hotel."""
        hotels, offers = self.data()
        hotels.append({"id": "ol-115313", "season": "winter", "family": {"verified": []}})
        offers.append({"hotel": "ol-115313", "url": URLS["grandbansko"], "board": "?", "source": "Olympic",
                       "seen": TODAY.isoformat(), "check_in": "2027-01-15", "nights": 5, "occupancy": "2+0",
                       "room": "cheapest unit, dates on request (po jedinici po danu)", "price_eur": 1500.0})
        n = len(offers)
        st = en.enrich(offers, hotels, CFG, TODAY, budget=5, cache_path=self.cache, fetch=self.fetch)
        fam = offers[n:]
        self.assertEqual(st["family_offers"], len(fam))
        self.assertGreater(len(fam), 0)
        self.assertTrue(all(o["occupancy"] == "2+2" and o["hotel"] == "ol-115313"
                            and "family price from hotel page" in o["room"] for o in fam))
        self.assertEqual(offers[n - 1]["occupancy"], "2+0")            # the base offer is unchanged
        self.assertEqual(offers[n - 1]["price_eur"], 1500.0)
        self.assertNotIn("family_price_est", offers[n - 1])          # per-unit price: no estimate
        self.assertEqual(offers[0]["board"], "?")
        self.assertEqual(offers[0]["board_cheapest"], "BB")          # Mediterranean: BB cheaper than HB
        self.assertEqual(st["board_cheapest"], 2)
        h = {x["id"]: x for x in hotels}
        self.assertEqual(h["ol-102986"]["enriched"]["board_prices"].keys(), {"BB", "HB"})
        self.assertTrue(any(r["max_persons"] == 4 for r in h["ol-115313"]["enriched"]["rooms"]))
        st = en.enrich(offers, hotels, CFG, TODAY, budget=5, cache_path=self.cache, fetch=self.fetch)
        self.assertEqual(st["family_offers"], 0)                       # already there: not added twice

    def test_block_stops_that_host(self):
        def blocked(url):
            self.calls.append(url)
            raise Blocked("403")
        hotels, offers = self.data()
        offers.append({"hotel": "ol-102986", "url": URLS["porfi"], "board": "?", "source": "Olympic"})
        st = en.enrich(offers, hotels, CFG, TODAY, budget=5, cache_path=self.cache, fetch=blocked)
        self.assertEqual(sorted(st["blocked"]), ["olympic.rs", "travelland.rs"])
        self.assertEqual(sum("olympic.rs" in u for u in self.calls), 1)    # 2 Olympic pages, 1 try
        self.assertEqual(st["skipped_blocked"], 1)                         # the other waits for next run
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
