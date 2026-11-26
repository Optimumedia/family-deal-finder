"""Audit tests (no network): each check finds its problem in a small hand-made data set."""
import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from trips import audit, db

TODAY = date(2026, 11, 26)
CFG = {
    "reach": {"max_drive_minutes": 300, "tolerance_minutes": 45},
    "sources": {
        "charters": {"pages": [{"area": "Antalya region, Turkey", "region": "Antalya region, Turkey", "nights": 7}]},
        "kopaonik": {"rsd_per_eur": 117.2, "pages": [{"area": "Kopaonik, Serbia", "nights": 7}]},
    },
}


def item(**kw):
    it = {"key": "k", "hotel_id": "h1", "kind": "hotel", "name": "Sunny Beach", "stars": 4, "area": "Kassandra, Halkidiki",
          "season": "summer", "lat": 40.0, "lng": 23.4, "image": "https://cdn.x/a.jpg", "source": "Olympic",
          "url": "https://www.olympic.rs/x/1/", "check_in": "2027-06-20", "nights": 7, "board": "HB", "room": "Family",
          "occupancy": "2+0", "price_eur": 700.0, "was_eur": None, "discount_label": None, "first_seen": "2026-11-25",
          "last_seen": "2026-11-25", "excluded": False, "family": {"drive_minutes": 240}}
    it.update(kw)
    return it


def peers(n=6, **kw):
    return [item(hotel_id=f"p{i}", name=f"Peer Hotel {i}", price_eur=700.0 + 10 * i, **kw) for i in range(n)]


def checks(items, hotels=None, cfg=CFG, today=TODAY):
    return {f["check"]: f for f in audit.audit(items, hotels or {}, cfg, today)["findings"]}


class AuditTest(unittest.TestCase):
    def test_clean_data_has_no_findings(self):
        self.assertEqual(checks(peers()), {})

    def test_dates(self):
        f = checks([item(check_in="2026-11-25", first_seen="2026-11-25", season="winter", area="Bansko, Bulgaria"),
                    item(hotel_id="h2", check_in="2028-08-01"),
                    item(hotel_id="h3", check_in="2027-01-20")])               # summer hotel in January
        self.assertEqual(f["past_check_in"]["count"], 1)
        self.assertEqual(f["check_in_is_scrape_date"]["count"], 1)
        self.assertEqual(f["check_in_too_far"]["count"], 1)
        self.assertEqual(f["wrong_season"]["count"], 1)
        self.assertEqual(f["past_check_in"]["severity"], "high")

    def test_nights_mismatch_against_config(self):
        f = checks([item(source="Savana Travel", area="Alanya, Antalya region, Turkey", nights=6),
                    item(hotel_id="h2", source="Savana Travel", area="Kemer, Antalya region, Turkey", nights=7),
                    item(hotel_id="h3", source="Supernova Travel", area="Kopaonik, Serbia", nights=3, season="winter",
                         check_in="2026-12-03", price_eur=round(34200 / 117.2, 2))])
        self.assertEqual(f["nights_mismatch"]["count"], 2)
        self.assertEqual(f["nights_mismatch"]["by_source"], {"Savana Travel": 1, "Supernova Travel": 1})

    def test_price_outliers_per_season_and_occupancy(self):
        f = checks(peers() + [item(hotel_id="cheap", name="Cheap", price_eur=140.0, room="cheapest (po osobi po danu)"),
                              item(hotel_id="dear", name="Dear", price_eur=20000.0)])
        self.assertEqual(f["price_low_outlier"]["examples"][0]["unit"], "po osobi po danu")
        self.assertEqual(f["price_high_outlier"]["count"], 1)

    def test_discounts(self):
        f = checks([item(was_eur=600.0), item(hotel_id="h2", was_eur=7000.0),
                    item(hotel_id="h3", was_eur=1000.0, discount_label="Rani buking -10%")])
        self.assertEqual(f["was_not_above_price"]["count"], 1)
        self.assertEqual(f["discount_too_big"]["count"], 1)
        self.assertEqual(f["discount_label_mismatch"]["examples"][0]["computed_pct"], 30)
        self.assertNotIn("discount_label_mismatch", checks([item(was_eur=1000.0, discount_label="-30%")]))

    def test_names_and_stars(self):
        f = checks([item(name="Forestia (ex. Moura)"), item(hotel_id="h2", name="MELIKE Hotel"),
                    item(hotel_id="h3", name="Serenity Suites (Adults only 12+)"),
                    item(hotel_id="h4", name="Naturist Camp", excluded=True),                 # already out: fine
                    item(hotel_id="h5", name="Bad Stars", stars=7),
                    item(hotel_id="sv-derici-4", name="Derici", stars=4, source="Savana Travel"),
                    item(hotel_id="sv-derici-1", name="Derici", stars=1, source="Savana Travel", price_eur=783.0)])
        self.assertEqual(f["name_ex_suffix"]["count"], 1)
        self.assertEqual(f["name_allcaps"]["examples"][0]["caps"], ["MELIKE"])
        self.assertEqual(f["family_unfit_name"]["count"], 1)
        self.assertEqual(f["stars_invalid"]["count"], 1)
        self.assertEqual(f["stars_conflict"]["examples"][0]["stars"], [1, 4])

    def test_geo_country_and_radius(self):
        hotels = {"h1": {"country": "BG"}, "h2": {"country": "GR"}, "far": {"country": "BG"},
                  "fly": {"country": "TR", "direct_flight_skp": True}}
        f = checks([item(),                                                     # Kassandra tagged BG
                    item(hotel_id="h2", lat=43.0, lng=21.0),                   # Greek hotel pinned in Serbia
                    item(hotel_id="far", area="Pamporovo, Bulgaria", season="winter", check_in="2027-01-15",
                         lat=41.65, lng=24.69, family={"drive_minutes": 424}, excluded=True),
                    item(hotel_id="fly", area="Alanya, Antalya region, Turkey", lat=36.5, lng=32.0,
                         family={"drive_minutes": 1500})], hotels)
        self.assertEqual(f["country_mismatch"]["examples"][0]["expected"], "GR")
        self.assertEqual(f["coords_outside_country"]["count"], 1)
        self.assertEqual(f["outside_drive_radius"]["count"], 1)                # the charter one is fine
        self.assertEqual(f["outside_drive_radius"]["examples"][0]["area"], "Pamporovo, Bulgaria")

    def test_duplicates(self):
        f = checks([item(room="Family"), item(room="Family sea view"),
                    item(hotel_id="sv-melike-3", name="Melike", source="Savana Travel", price_eur=625.0),
                    item(hotel_id="sv-melike-2", name="Melike", source="Savana Travel", price_eur=625.0),
                    item(hotel_id="ol-1", name="Alkyonis Hotel", price_eur=490.0),
                    item(hotel_id="ol-2", name="Alkyonis", price_eur=530.0)])
        self.assertEqual(f["duplicate_offer"]["examples"][0]["copies"], 2)
        self.assertEqual(f["duplicate_listing"]["examples"][0]["hotel_ids"], ["sv-melike-2", "sv-melike-3"])
        self.assertEqual(f["same_name_two_ids"]["examples"][0]["hotel_ids"], ["ol-1", "ol-2"])

    def test_images(self):
        f = checks([item(image="https://atlantisonline.mk/ExtraContent/Img/listdefaultthumb.png"),
                    item(hotel_id="h2", name="Villa A", image="https://pms.x/a.jpg?profile=sm"),
                    item(hotel_id="h3", name="Big", image="https://mcdn.pro/a_thumb_800x600.jpeg"),
                    item(hotel_id="h4", name="Alpha", image="https://x/same.jpg"),
                    item(hotel_id="h5", name="Beta", image="https://x/same.jpg")])
        self.assertEqual(f["placeholder_image"]["count"], 1)
        self.assertEqual(f["small_image"]["count"], 1)                         # 800 px thumb is fine
        self.assertEqual(f["image_shared"]["examples"][0]["names"], ["alpha", "beta"])

    def test_kopaonik_rsd(self):
        sn = dict(source="Supernova Travel", area="Kopaonik, Serbia", season="winter", check_in="2027-01-10",
                  occupancy="2+2")
        rows = [item(hotel_id="ok", price_eur=round(56280 / 117.2, 2), **sn),
                item(hotel_id="pp", price_eur=round(7 * 1500 / 117.2, 2), **sn)]            # €13/night: per person
        f = checks(rows)
        self.assertEqual(f["rsd_out_of_band"]["count"], 1)
        self.assertNotIn("rsd_rate_off", f)
        cfg = {**CFG, "sources": {**CFG["sources"], "kopaonik": {"rsd_per_eur": 1.172, "pages": []}}}
        self.assertEqual(checks(rows, cfg=cfg)["rsd_rate_off"]["count"], 1)

    def test_revalidate_stored_offers(self):
        f = checks([item(price_eur=7 * 3700.0, kind="villa")])
        self.assertIn("above", f["fails_validation"]["examples"][0]["reasons"][0])
        f = checks([item(check_in="2026-11-20")])                               # past: own finding only
        self.assertNotIn("fails_validation", f)

    def test_ranking_severity_then_count(self):
        rep = audit.audit([item(check_in="2026-11-20"), item(hotel_id="h2", name="A (ex. B)"),
                           item(hotel_id="h3", name="C (ex. D)")], {}, CFG, TODAY)
        sev = [f["severity"] for f in rep["findings"]]
        self.assertEqual(sev, sorted(sev, key=lambda s: -audit.SEVERITY[s]))
        self.assertIn("Check-in date already passed", audit.render(rep))

    def test_main_reads_files_and_writes_small_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "data.json").write_text(json.dumps({"items": [item(check_in="2026-11-20")]}), encoding="utf-8")
            (t / "config.toml").write_text("[reach]\nmax_drive_minutes = 300\n", encoding="utf-8")
            con = db.connect(t / "trips.db")
            db.upsert_hotel(con, {"id": "h1", "name": "Sunny Beach", "season": "summer", "area": "Kassandra, Halkidiki",
                                  "country": "GR"})
            con.execute("INSERT INTO offer VALUES('x','ghost','Olympic','u','2027-06-20',7,'HB','r','2+0','d','d')")
            con.commit()
            con.close()
            out = t / "audit.json"
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                audit.main(["--data", str(t / "data.json"), "--db", str(t / "trips.db"),
                            "--config", str(t / "config.toml"), "--out", str(out), "--today", "2026-11-26"])
            rep = json.loads(out.read_text(encoding="utf-8"))
            got = {f["check"] for f in rep["findings"]}
            self.assertTrue({"past_check_in", "orphan_offer", "offer_without_price"} <= got)
            self.assertIn("wrote", buf.getvalue())
            # the DB is opened read-only
            check = sqlite3.connect(t / "trips.db")
            self.assertEqual(check.execute("SELECT count(*) FROM offer").fetchone()[0], 1)
            check.close()


if __name__ == "__main__":
    unittest.main()
