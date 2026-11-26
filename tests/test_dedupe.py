"""Duplicate-hotel matcher (no network): normalisation, guards, run-time merge, DB migration."""
import tempfile
import unittest
from pathlib import Path

from trips import db, dedupe


def H(id, name, season="winter", area="Bansko, Bulgaria", lat=41.83, lng=23.48, stars=None, **kw):
    return {"id": id, "name": name, "season": season, "area": area, "lat": lat, "lng": lng, "stars": stars,
            "family": {}, **kw}


def same(a, b, pool=()):
    return dedupe.match(a, b, dedupe.coord_counts([a, b, *pool]))[0]


# centroid pool: three cards on the same resort point make it a centroid, not a building
CENTROID = [H(f"x-{i}", f"Filler {i}") for i in range(3)]


class Normalise(unittest.TestCase):
    def test_fold_accents_and_cyrillic(self):
        self.assertEqual(dedupe.fold("Čardaci Šumska Kuća"), "cardaci sumska kuca")
        self.assertEqual(dedupe.fold("Гранд Ројал"), "grand rojal")
        self.assertEqual(dedupe.fold("Банско"), "bansko")

    def test_core_drops_stopwords_brands_stars_places(self):
        k = lambda n, a="Bansko, Bulgaria": dedupe.name_key(n, a)["cores"][0]
        self.assertEqual(k("Grand Royale Apart Hotel & Spa"), ("grand", "royale"))
        self.assertEqual(set(k("MPM Hotel Guinness")), {"guinness"})
        self.assertEqual(set(k("Guinness MPM 4*")), {"guinness"})
        self.assertEqual(k("St. Ivan Rilski Hotel, Spa & Apartments"), k("Sveti Ivan Rilski Spa Resort"))
        self.assertEqual(k("Aparthotel Saint George Palace"), k("St. George Palace Bansko"))
        self.assertEqual(k("Mursalitsa Hotel by HMG", "Pamporovo"), ("mursalitsa",))
        self.assertEqual(k("Radina's Way"), ("radinas", "way"))
        self.assertEqual(k("Grand Hotel Bansko"), ("grand", "bansko"))      # nothing specific: place kept

    def test_ex_name_is_an_alias_and_unit_is_split(self):
        key = dedupe.name_key("Chalet Evergreen (ex. Breza)", "Borovets, Bulgaria")
        self.assertIn(("breza",), key["cores"])
        key = dedupe.name_key("Apartmani Konaci — 2+1 Apt", "Kopaonik, Serbia")
        self.assertEqual(key["unit"], "2 1 apt")


class Matcher(unittest.TestCase):
    def test_cross_source_spellings_merge(self):
        pairs = [("Grand Royale", "Grand Royale Apart Hotel & Spa"),
                 ("MPM Hotel Guinness", "Guinness Mpm"),
                 ("Mpm Hotel Merryan", "Merryan Mpm"),
                 ("Radina's Way", "Radinas Way"),
                 ("Iglika", "Iglika Borovets Hotel"),
                 ("Amira", "Amira Boutique Residence Hotel"),
                 ("Regnum Aparthotel", "Regnum Bansko Mountain Resort"),
                 ("Мурсалица", "Mursalitsa Hotel by Hmg"),
                 ("Edelweis Palace", "Edelweiss Palace")]                   # near spelling
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertTrue(same(H("ol-1", a), H("tl-1", b), CENTROID))

    def test_same_source_exact_duplicates_merge(self):
        a = H("ol-103035", "Secret Paradise Hotel & Spa", "summer", "Kassandra, Halkidiki", 40.02, 23.43, 4)
        b = H("ol-114144", "Secret Paradise Hotel and Spa", "summer", "Kassandra, Halkidiki", 40.02, 23.43, 4)
        self.assertTrue(same(a, b, CENTROID))

    def test_never_merge_generic_or_different_hotels(self):
        no = [("Grand Hotel Bansko", "Grand Royale Apart Hotel & Spa"),
              ("Grand Hotel & Spa", "Grand Hotel"),
              ("Palace", "Palace Hotel"),
              ("Iglika", "Iglika Palace"),
              ("St. George Ski & Holiday", "St. George Palace Bansko"),
              ("Bansko", "Lion Bansko"),
              ("Mediterranean Resort", "Mediterranean Village"),
              ("Kleopatra Beach", "Kleopatra Ada Beach"),
              ("Lion Bansko", "Lion Borovets")]                            # place words conflict
        for a, b in no:
            with self.subTest(a=a, b=b):
                self.assertFalse(same(H("ol-1", a), H("tl-1", b), CENTROID))

    def test_same_source_needs_exact_core(self):
        self.assertFalse(same(H("cs-1", "Villa Bernice", kind="villa"), H("cs-2", "Villa Bernie", kind="villa")))
        self.assertFalse(same(H("ol-1", "4u Apartments"), H("ol-2", "4u Family"), CENTROID))

    def test_guards(self):
        self.assertFalse(same(H("ol-1", "Iceberg"), H("tl-1", "Iceberg", season="summer")))
        self.assertFalse(same(H("cur", "Lagomandra Beach & Suites"), H("ot-1", "Villa Lagomandra", kind="villa")))
        self.assertFalse(same(H("kop-a", "Apartmani Konaci — 2+1 Apt"), H("kop-b", "Apartmani Konaci — 2+2 Apt")))
        self.assertFalse(same(H("ol-1", "Iceberg", area="Borovets, Bulgaria", lat=42.266, lng=23.606),
                              H("tl-1", "Iceberg", area="Bansko, Bulgaria")))                   # 50 km
        self.assertFalse(same(H("ol-1", "Iceberg", stars=5), H("tl-1", "Iceberg", stars=3), CENTROID))
        self.assertTrue(same(H("ol-1", "Iceberg", stars=5), H("tl-1", "Iceberg", stars=4), CENTROID))
        self.assertFalse(same(H("ol-1", "Poseidon Palace"), H("ol-2", "Poseidon Palace+, Leptokaria"), CENTROID))

    def test_hotel_level_coordinates(self):
        a = H("sv-a", "Kleopatra Beach", "summer", "Alanya, Turkey", 36.55159865, 31.97716304, 4)
        far = H("sv-b", "Kleopatra Beach", "summer", "Alanya, Turkey", 36.620568, 31.766258, 4)    # ~20 km
        self.assertFalse(same(a, far))
        twin = H("sv-c", "Kleopatra Beach", "summer", "Alanya, Turkey", 36.5516, 31.9772, 1)       # same building
        self.assertTrue(same(a, twin))                    # coordinates override noisy stars
        self.assertTrue(same(H("sv-d", "Palm", "summer", "Kusadasi", 37.866623, 27.26457),
                             H("sv-e", "Palm", "summer", "Kusadasi", 37.866528, 27.264755)))

    def test_area_less_hotels_still_match(self):              # the contract of the old merge_auto tests
        self.assertTrue(same({"id": "ol-1", "name": "Grand Royale", "season": "winter"},
                             {"id": "tl-1", "name": "Grand Royale Apart Hotel & Spa", "season": "winter"}))


class MergeAutoV2(unittest.TestCase):
    def test_same_contract_as_merge_auto(self):
        known = [{"id": "tl-1", "name": "Grand Royale Apart Hotel & Spa", "season": "winter"},
                 {"id": "tl-2", "name": "Lion Bansko", "season": "winter"}]
        hs = [{"id": "ol-1", "name": "Grand Royale", "season": "winter"},
              {"id": "ol-2", "name": "Bansko", "season": "winter"}]
        os_ = [{"hotel": "ol-1"}, {"hotel": "ol-2"}]
        add = dedupe.merge_auto_v2(known, hs, os_)
        self.assertEqual(os_[0]["hotel"], "tl-1")
        self.assertEqual([h["id"] for h in add], ["ol-2"])

    def test_photo_goes_to_known_without_one(self):
        photos = {}
        dedupe.merge_auto_v2([{"id": "casa", "name": "Casa Karina Apartments", "season": "winter"}],
                             [{"id": "tl-9", "name": "Casa Karina", "season": "winter", "image": "p.jpg"}],
                             [], photos)
        self.assertEqual(photos, {"casa": "p.jpg"})
        photos = {}
        dedupe.merge_auto_v2([{"id": "casa", "name": "Casa Karina", "season": "winter", "image": "own.jpg"}],
                             [{"id": "tl-9", "name": "Casa Karina", "season": "winter", "image": "p.jpg"}],
                             [], photos)
        self.assertEqual(photos, {})

    def test_duplicates_within_one_batch_fold_together(self):
        hs = [H("ol-103035", "Secret Paradise Hotel & Spa", "summer", "Kassandra, Halkidiki", 40.02, 23.43),
              H("ol-114144", "Secret Paradise Hotel and Spa", "summer", "Kassandra, Halkidiki", 40.02, 23.43)]
        os_ = [{"hotel": "ol-103035"}, {"hotel": "ol-114144"}]
        log = []
        add = dedupe.merge_auto_v2([], hs, os_, log=log)
        self.assertEqual([h["id"] for h in add], ["ol-103035"])
        self.assertEqual({o["hotel"] for o in os_}, {"ol-103035"})
        self.assertEqual(log[0][:2], ("ol-114144", "ol-103035"))

    def test_known_db_hotels_keep_their_id(self):
        known = [H("ol-1", "Iceberg"), *CENTROID]                  # auto hotel already in the DB
        os_ = [{"hotel": "tl-1"}, {"hotel": "ol-1"}]
        add = dedupe.merge_auto_v2(known, [H("tl-1", "Iceberg Borovets"), H("ol-1", "Iceberg")], os_)
        self.assertEqual([h["id"] for h in add], ["ol-1"])          # refreshed once, the duplicate folded
        self.assertEqual({o["hotel"] for o in os_}, {"ol-1"})


class Migration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = db.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def _offer(self, hotel, price, seen="2026-11-20", source="S"):
        return {"hotel": hotel, "source": source, "url": "u", "seen": seen, "check_in": "2027-01-15", "nights": 5,
                "board": "BB", "room": "Apt", "occupancy": "2+2", "price_eur": price}

    def test_find_clusters_keeps_curated_and_no_chaining(self):
        hs = [H("st-ivan-rilski-bansko", "St. Ivan Rilski Hotel, Spa & Apartments", lat=41.829, lng=23.478),
              H("ol-115326", "Sveti Ivan Rilski Spa Resort"),
              H("ol-1", "Iglika", area="Borovets"), H("tl-1", "Iglika Borovets Hotel", area="Borovets"),
              H("atl-1", "Iglika Palace", area="Borovets"), *CENTROID]
        cl = dedupe.find_clusters(hs, curated_ids={"st-ivan-rilski-bansko"})
        got = {c["keep"]: set(c["drop"]) for c in cl}
        self.assertEqual(got["st-ivan-rilski-bansko"], {"ol-115326"})
        self.assertEqual(len(cl), 2)
        self.assertFalse(any("atl-1" in c["drop"] or c["keep"] == "atl-1" for c in cl))

    def test_apply_remaps_offers_and_keeps_cheaper_snapshot(self):
        for h in (H("ol-1", "Iceberg"), H("tl-1", "Iceberg Borovets")):
            db.upsert_hotel(self.con, h)
        db.add_sighting(self.con, self._offer("ol-1", 900))
        db.add_sighting(self.con, self._offer("tl-1", 850))                    # same key after the remap
        db.add_sighting(self.con, self._offer("tl-1", 800, source="T"))        # different source: moves
        db.save_image(self.con, "tl-1", "p.jpg", "2026-11-20")
        self.con.execute("INSERT INTO alert_sent VALUES('book|tl-1|2027-01-15|x', 'now')")
        stats = dedupe.apply_clusters(self.con, [{"keep": "ol-1", "drop": ["tl-1"]}])
        self.assertEqual(stats["hotels_removed"], 1)
        offers = db.offers(self.con)
        self.assertEqual({o["hotel_id"] for o in offers}, {"ol-1"})
        self.assertEqual(len(offers), 2)
        s = next(o for o in offers if o["source"] == "S")
        self.assertEqual([x["price_eur"] for x in s["history"]], [850])
        self.assertEqual(set(db.hotels(self.con)), {"ol-1"})
        self.assertEqual(db.images(self.con), {"ol-1": "p.jpg"})
        self.assertIsNotNone(self.con.execute("SELECT 1 FROM alert_sent WHERE key='book|ol-1|2027-01-15|x'").fetchone())
        self.assertEqual(self.con.execute("SELECT count(*) FROM snapshot").fetchone()[0], 2)

    def test_apply_fills_gaps_of_auto_keeper_only(self):
        keep = H("ol-1", "Amira", stars=5)
        drop = H("atl-1", "Amira Boutique Residence Hotel", image="a.jpg", family={"kids_pool": True})
        for h in (keep, drop):
            db.upsert_hotel(self.con, h)
        dedupe.apply_clusters(self.con, [{"keep": "ol-1", "drop": ["atl-1"]}])
        h = db.hotels(self.con)["ol-1"]
        self.assertEqual(h["image"], "a.jpg")
        self.assertTrue(h["family"]["kids_pool"])


if __name__ == "__main__":
    unittest.main()
