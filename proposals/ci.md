# ci: end-to-end test, shared fake session, GitHub Actions

## What I changed (my files only)
- **NEW `tests/fakes.py`**: `FakeSession` has the same surface as `PoliteSession` that the sources, enrich and health use (`get`, `stats`, `requests_made`, `min_delay`). It serves fixture files by URL regex, and the first match wins. A route can also return a literal string, call a function, or raise an exception (e.g. `Blocked`). URLs that match nothing get `""` (what `PoliteSession` returns on a 404) and are logged in `.misses`. `FakeSession.factory(routes, log=[])` is a drop-in replacement for the class. `no_network()` makes any socket connect fail the test. Other agents can reuse it instead of the per-file fakes.
- **NEW `tests/test_e2e.py`**: 13 tests, about 1.8 s. It runs the real `run.main()` once on **every** `AUTO_SOURCES` module plus `hotel_direct` and enrich (37 fixture routes), then a second `--offline` run on the same DB. Conditions:
  - cwd is a temp dir, so the DB, `docs/data.json`, `docs/health.json`, the health history and the enrich cache are all temp files.
  - `today` is frozen at 2026-11-25.
  - The router is a straight-line stand-in.
  - Email is off. `ORS_API_KEY` is removed.
  - The config is the real `config.toml`, cut down to the pages we have fixtures for, with a made-up `kids_birthdate`.
  - `data/offers.toml` is replaced by one good offer and one past-dated offer.

  What it checks:
  - the `data.json` shape and the item keys the dashboard reads (as a subset)
  - every source gives at least 1 item
  - no duplicate keys
  - every item has tier, family and deal
  - sort order
  - campaign alerts appear
  - the rejected offer is counted in `health.rejected_by_source` and `offers_rejected`
  - `health.json` and the health history are written, with no source in error, blocked or zero
  - enrich read detail pages within budget and wrote its cache in the temp dir
  - the birthdate (the sentinel, plus the real local one if present) appears in no file under docs
  - the real `docs/data.json` is untouched
  - the offline rerun gives the same keys and no new alerts
- **NEW `.github/workflows/tests.yml`**:
  - runs on push and PR to main, plus manual dispatch
  - ubuntu-latest, Python 3.12 and 3.14 matrix, pip cache on `requirements.txt`
  - a guard step fails if `config.local.toml`, `data/trips.db` or `.email` is in the checkout
  - then runs `python -m unittest discover -s tests -t . -v`
  - read-only permissions, no network needed

## Effect
- Suite on this PC (Python 3.14):
  - At the start: 168 tests in 3.7 s.
  - Mid-round: 203 tests in about 5.5 s.
  - At the end: 309 tests in about 30 s wall time, while other agents were running jobs at the same time. Most of that is outside e2e: `test_add_offer` alone takes about 9.6 s.
  - `test_e2e`: 1.8 s alone at first, about 4.7 s of CPU at the end, because the pipeline now also runs dedupe and family_prices. There are no sleeps and no network, since FakeSession has no delay.
- One e2e run sends 67 fake requests and gives 290 items across 11 sources. Every source is `ok` in `health.json`.
- Coverage (stdlib `trace`, whole suite):

  | Module | Coverage |
  |---|---|
  | `run` | 93% |
  | `enrich` | 96% |
  | `health` | 97% |
  | `validate` | 97% |
  | `db` | 95% |
  | `score` | 82% |
  | sources | 90–94% |
  | `hotel_direct` | 81% |
  | `geo` | 69% |
  | `digest` | 61% |
  | `http` | 25% |
  | `family_prices` (new, someone else's) | 44% |
- Other tests: none depend on `config.local.toml` (they all call `load_config(..., local=None)`) or on `data/trips.db`. A copy of the repo without those files, the caches and the history passes the suite, apart from the in-progress `test_dedupe` failure noted at the end.

## Integration diffs (files I don't own)
1. **`trips/run.py`: close the DB.** On Windows the open `trips.db` blocks temp-dir cleanup. The test works around this by wrapping `db.connect`.
```diff
-    items, alerts = build(con, cfg, today, offline=args.offline)
-    alerts = new_camps + alerts
-    con.commit()
+    items, alerts = build(con, cfg, today, offline=args.offline)
+    alerts = new_camps + alerts
+    con.commit()
+    con.close()
```
(`build()` is the last user of `con`.)

2. **`trips/run.py`: injectable paths and clock**, so tests don't need `chdir` or `mock.patch` of `run.date`, `run.load_config` and `run.PoliteSession`:
```diff
-def main(argv=None) -> int:
+def main(argv=None, *, today: date | None = None, session_factory=None, cfg: dict | None = None) -> int:
     ap = argparse.ArgumentParser()
     ap.add_argument("--offline", action="store_true")
+    ap.add_argument("--root", default=".", help="folder holding config.toml, data/ and docs/")
     ap.add_argument("--db", default="data/trips.db")
     args = ap.parse_args(argv)
+    root = Path(args.root)
     logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
-    cfg = load_config()
-    con = db.connect(args.db)
-    today = date.today()
-    curated = manual.load_hotels()
-    sightings = manual.load() if cfg["sources"].get("manual") else []
+    cfg = cfg or load_config(root / "config.toml")
+    con = db.connect(root / args.db)
+    today = today or date.today()
+    curated = manual.load_hotels(root / "data/hotels.toml")
+    sightings = manual.load(root / "data/offers.toml") if cfg["sources"].get("manual") else []
     auto_sightings: list[dict] = []
-    hl = health.RunHealth()
+    hl = health.RunHealth(root / "data/health-history.json")

     def session() -> PoliteSession:
         sc = cfg["sources"]
+        if session_factory:
+            return session_factory()
         return PoliteSession(sc["delay_seconds"], sc["jitter_seconds"], sc["timeout_seconds"],
-                             host_delays=sc.get("host_delays"), cache_path="data/http-cache.sqlite")
+                             host_delays=sc.get("host_delays"), cache_path=root / "data/http-cache.sqlite")
 ...
-            with hl.track("Detail pages", es) as st:
-                enrich.enrich(auto_sightings, known, cfg, today, session=es)
+            with hl.track("Detail pages", es) as st:
+                enrich.enrich(auto_sightings, known, cfg, today, session=es,
+                              cache_path=root / cfg["sources"]["enrich"].get("cache", "data/enrich_cache.json"))
 ...
-    export(items, alerts, cfg)
+    export(items, alerts, cfg, root / "docs/data.json")
 ...
-    report = hl.write("docs/health.json")
+    report = hl.write(root / "docs/health.json")
```
After this, `test_e2e._run_main` becomes `run.main(["--root", tmp], today=TODAY, session_factory=FakeSession.factory(ROUTES), cfg=cfg)`. Only the `geo._osrm` patch is still needed. I can make that switch once this lands.

3. **`trips/sources/kopaonik.py`: add a `SOURCE` name.** The module has no `SOURCE`, so `health.json` and the dashboard show the source as **"trips.sources.kopaonik"**:
```diff
 SOURCES = {"jat": "JAT Apartmani (own site)", "supernova": "Supernova Travel"}
+SOURCE = "Kopaonik (JAT + Supernova)"
```
(It only changes the health name, and the health history keys under the old name restart.)

Already fixed by the integrator during this round, and now a regression test in e2e (`test_health_counts_detail_pages`): enrich used its own session, so health always reported 0 detail pages.

## Coverage gaps (not covered by any test)
- **`trips/http.py` (25%)**: robots.txt handling, the per-host wait, 304/ETag cache, the 403/challenge → `Blocked` path, 404 → `""`, and 429/5xx retries. This is the politeness layer, so it should have unit tests with a fake `requests.Session`; its sleeps would need to be patched to stay fast.
- **`digest.py` (61%)**: `send()` and `load_settings()` (SMTP) are untested.
- **`geo.py` (69%)**: the ORS fallback and the OSRM failure → straight-line path. e2e uses a stand-in router.
- **`run.main`**: the exit code 3 path (a failed source) isn't covered end to end; e2e only shows "ok".
- **Sources**: `Blocked` and `Unavailable` branches in each `fetch` loop, mk_agencies' menu fallback (refreshed saved search), and bgski on Borovets/Pamporovo (no fixtures).
- **`hotel_direct`**: only 3 of the ~30 configured pages have fixtures.
- **Determinism**: `export`, `health` and `db.add_sighting` stamp `datetime.now()`. No test asserts on those fields, but a stable snapshot (golden `data.json`) would need them injectable too.

## Known limits
- e2e serves each listed page from one fixture saved on 25.11.2026. When a parser changes on purpose and a fixture goes stale, `test_every_source_lands_offers` names the source; refresh the fixture.
- Python 3.12 hasn't been run locally (only 3.14 is installed). The CI matrix will show any 3.12-only break.
- While I worked, `tests/test_conditions.py` (7 errors), `tests/test_add_offer.py` (4 failures) and `tests/test_dedupe.py` (1 failure) were failing. Those are other agents' unfinished work, not mine.
