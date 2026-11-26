# Ops: trustworthy twice-daily runs — integration notes

New/changed (already in place): `trips/validate.py`, `trips/health.py`, `trips/http.py`
(per-host delay, ETag/Last-Modified cache, `stats` counters), `trips/geo.py` (OSRM → openrouteservice
→ straight-line estimate), `run_local.ps1`, `setup_schedule.ps1`, tests `tests/test_validate.py`,
`tests/test_health.py`, README "Operations".

Nothing below is wired in yet: `trips/run.py`, `.gitignore`, `config.toml` and `docs/index.html` belong
to the integrator. Without the run.py hooks the run behaves as before (no validation, no health.json),
except that geo now returns a straight-line estimate instead of `None` when OSRM is down.

## 1. `trips/run.py` hooks (exact diff against HEAD)

```diff
--- a/trips/run.py
+++ b/trips/run.py
@@
-from . import db, digest, geo, score
+from . import db, digest, geo, health, score, validate
+from .http import PoliteSession
 from .sources import hotel_direct, manual, micazu, oliverstravels, olympic, travelland
@@ def build(con, cfg: dict, today: date, offline: bool = False) -> tuple[list[dict], list[dict]]:
     drives = {hid: db.cached_drive(con, hid, h["lat"], h["lng"]) for hid, h in hotels.items()} if offline \
         else geo.drive_minutes(con, hotels, home)
+    estimated = set() if offline else set(geo.last_estimated)
     offers = db.offers(con)
@@
             "season": h["season"], "lat": h.get("lat"), "lng": h.get("lng"), "notes": h.get("notes"),
+            "drive_estimate": h["id"] in estimated,   # straight-line guess: OSRM was down this run
             "image": h.get("image") or photos.get(h["id"]),
@@ def main(argv=None) -> int:
     curated = manual.load_hotels()
     sightings = manual.load() if cfg["sources"].get("manual") else []
+    hl = health.RunHealth()
+
+    def session() -> PoliteSession:
+        sc = cfg["sources"]
+        return PoliteSession(sc["delay_seconds"], sc["jitter_seconds"], sc["timeout_seconds"],
+                             host_delays=sc.get("host_delays"), cache_path="data/http-cache.sqlite")
+
     if not args.offline:
         known = list(curated)
         photos: dict[str, str] = {}        # known hotel id -> photo of an agency card folded into it
         for src in AUTO_SOURCES:
-            auto_hotels, auto_offers = src.fetch(cfg, today)
+            s = session()
+            auto_hotels, auto_offers = [], []
+            with hl.track(getattr(src, "SOURCE", src.__name__), s) as st:   # catches a crashing source
+                auto_hotels, auto_offers = src.fetch(cfg, today, session=s)
+                st.offers_parsed = len(auto_offers)
+            for h in auto_hotels:
+                if validate.bad_image(h):
+                    h["image"] = None
             added = merge_auto(known, auto_hotels, auto_offers, photos)  # also matches hotels found by earlier sources
@@
     for h in curated:                      # curated facts always win
         db.upsert_hotel(con, h)
+    sightings, rejects = validate.split(sightings, today, cfg)
+    validate.log_rejects(rejects)
+    hl.add_rejects(validate.by_source(rejects))
     new = sum(db.add_sighting(con, o) for o in sightings)
     new_camps = []
     if not args.offline:
         names = {h["id"]: h["name"] for h in curated}
-        for c in hotel_direct.fetch(cfg, today):
+        s, camps = session(), []
+        with hl.track(hotel_direct.SOURCE, s) as st:
+            camps = hotel_direct.fetch(cfg, today, session=s)
+            st.offers_parsed = len(camps)
+        for c in camps:
             if db.add_campaign(con, c):
@@
     shown = sum(not i["excluded"] for i in items)
     log.info("%d offers (%d new sightings), %d fit the family, %d alerts, digest: %s",
              len(items), new, shown, len(alerts), result)
-    return 0
+    if args.offline:
+        return 0
+    report = hl.write("docs/health.json")   # + data/health-history.json (last 60 runs, for the 7-run average)
+    # 3 = finished, but a source crashed / was blocked / suddenly returned 0. run_local.ps1 still publishes.
+    return 3 if report["status"] == "fail" else 0
```

Notes:
- Validation runs on manual sightings too. A `data/offers.toml` entry whose check-in has passed is
  now rejected (logged) instead of adding a new snapshot; its old price history stays in trips.db.
- With today's data, the only reject would be Oliver's Travels "Villa Lagomandra" (€25,905 / 7 nights =
  €3,701/night > €2,500). To keep it, add `[validate] max_eur_per_night = 4000` to config.toml.
- Optional per-host minimum delays: `[sources] host_delays = { "www.olympic.rs" = 10 }`.
  The default minimum for every host is `delay_seconds` (+ jitter), as before, now counted per host.

## 2. `.gitignore` additions

```
data/logs/
data/run.lock
data/http-cache.sqlite
data/health-history.json
```

(`run_local.ps1` only ever stages `docs/data.json` and `docs/health.json`, so these can't be
committed by the scheduled run even before this lands; they would only show as untracked.)

## 3. Dashboard (`docs/index.html`, optional)

`docs/health.json` shape:

```json
{"generated": "2026-11-25T13:04", "status": "ok|warn|fail", "failed_sources": ["Olympic"],
 "problems": ["Olympic returned 0 offers today (usually ~31); the page layout may have changed"],
 "sources": [{"name": "Olympic", "status": "ok|partial|blocked|error|zero|idle", "pages_fetched": 9,
              "not_modified": 3, "offers_parsed": 98, "offers_rejected": 0, "blocked": 0, "errors": 0,
              "duration_s": 74.2, "avg_offers_7": 97.4, "messages": []}],
 "rejected_by_source": {"Oliver's Travels": {"rejected": 1, "reasons": {"price per night": 1}}}}
```

Suggested UI: fetch `health.json` next to `data.json`; when `problems` is non-empty show a small
banner ("⚠ Olympic failed today …"). Show "≈" before the drive time when `item.drive_estimate`.

## 4. Task Scheduler

`setup_schedule.ps1` is unchanged in behaviour (still `-MultipleInstances IgnoreNew`); re-running it is
not required. Task Scheduler's "Last Run Result" now shows `run_local.ps1`'s exit code
(0 ok, 3 a source failed, 4 skipped because a run was still going, 5/6/7 git pull/commit/push failed).
