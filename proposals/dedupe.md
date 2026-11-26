# dedupe: one hotel, one card

## What I changed (my files only)
- **NEW `trips/dedupe.py`**
  - `name_key()` normalises a name. It strips accents, turns Cyrillic into Latin letters, and treats St/Saint/Sveti/Agios as the same word. It drops hotel/apart/spa/resort/complex, the MPM/HMG/Karisma brands, star ratings, "(ex. …)" (kept as an alias), "by …" tails, apostrophes and resort place words. It keeps `+` as "plus" and the unit after an em dash ("Konaci — 2+1 Apt").
  - `match(a, b)` decides whether two rows are the same hotel. It returns `(bool, reason)`.
    - **Guards that never merge:** a different season; a villa with a hotel; a different unit; different numbers; conflicting place words ("Lion Bansko" vs "Lion Borovets"); a different area (no area word in common and more than 15 km apart); building-level coordinates more than 3 km apart; stars 2 or more apart (unless the coordinates are within 300 m).
    - **Names, after the guards:** an exact core match, a subset where the only extra words are soft (boutique/residence/mountain/suites/lux/club/lodge…), or a near spelling with the same number of words.
    - **Generic names:** a name made only of generic words ("Grand", "Palace", "Garden", "Mediterranean") never merges on the name alone.
    - **Same source:** two rows from the same source merge only on an exact core.
  - `merge_auto_v2(known, auto_hotels, auto_offers, images, log=None)` has the same contract as `run.merge_auto`. It also folds duplicates within one batch. When an auto id is already known, it returns that hotel again so its row is refreshed.
  - `find_clusters`, `near_misses`, `apply_clusters` and `aliases` handle the one-time database clean-up. Run it with `python -m trips.dedupe [--db …] [--apply]`. It is a dry run by default, and `--apply` makes a backup first.
- **NEW `tests/test_dedupe.py`**: 17 tests. The existing tests for olympic, travelland, bgski, rentals, mk_agencies and new_sources also pass with `run.merge_auto` swapped for v2.

## Measured on the real DB (copy, `trips.db`, 2026-11-26)
- **Hotels:** 262 → 241 (21 clusters, 21 duplicate rows). The old `merge_auto` folds 0 of them.
- **Offers:** 488 → 479. The other 13 offers move to the kept hotel, and 9 are the same offer under both ids, which fold together with the cheaper price kept.
- **Fitting hotel cards (offline build):** 229 → 211. Fitting offers go 398 → 390.
- **After the migration:** replaying every hotel through v2 with the DB-seeded `known` (diff below) maps all 21 onto the kept ids and creates no new ids.

**The 21 merges** (the first id is kept):
- st-ivan-rilski-bansko ← Sveti Ivan Rilski Spa Resort
- Alkyonis ← Alkyonis Hotel
- Secret Paradise Hotel & Spa ← … and Spa
- Mpm Hotel Merryan ← Merryan Mpm
- Mpm Hotel Musala ← Musala Hotel Mpm
- Radina's Way ← Radinas Way
- Regnum Aparthotel ← Regnum Bansko Mountain Resort
- Kamelia Hotel ← Kamelia Complex
- Aparthotel Saint George Palace ← St. George Palace Bansko
- Amira ← Amira Boutique Residence Hotel
- Iceberg / Iglika / Rila / Edelweiss ← "… Borovets (Hotel)"
- Mursalitsa ← Mursalitsa Hotel by Hmg
- Savana repeats on the same coordinates: Palm, Ponz, Aargau, Derici, Melike, Mesut

**Review list:**
- **Merges to eyeball:**
  - Regnum Aparthotel ← Regnum Bansko Mountain Resort (a subset match).
  - Amira ← Amira Boutique Residence (a subset match).
  - Kamelia Hotel ← Kamelia Complex.
  - Savana Derici 1★/4★ and Aargau 2★/3★: the stars are noise and the coordinates are identical. The kept row takes the higher star rating.
- **Deliberately not merged:**
  - Poseidon Palace vs Poseidon Palace+ (two Olympic products).
  - Iglika vs Iglika Palace.
  - St. George Palace vs St. George Ski & Holiday.
  - Kleopatra Beach vs Kleopatra Ada Beach (500 m apart).
  - 4u Apartments vs 4u Family.
  - Villa Lagomandra (villa) vs Lagomandra Beach (hotel).
  - Villa Bernice vs Villa Bernie.
  - Pirin vs Pirin Golf.
  - All the Kopaonik units.
- **Likely missed:** Malina Chalets (bs-10302, whose URL is malina_villas) vs Malina Villas (tl-111106). Chalets and villas are different words, so I left this pair for a human.
- `python -m trips.dedupe` prints all of this.

## Integration diff: `trips/run.py`
```diff
-from . import db, digest, enrich, geo, health, score, validate
+from . import db, dedupe, digest, enrich, geo, health, score, validate
@@ def main
     if not args.offline:
-        known = list(curated)
+        curated_ids = {h["id"] for h in curated}
+        # auto hotels already in the DB are known too, so a re-found duplicate folds into the id
+        # its price history is under (curated first in line, so curated still wins)
+        known = list(curated) + [h for hid, h in db.hotels(con).items() if hid not in curated_ids]
@@
-            added = merge_auto(known, auto_hotels, auto_offers, photos)  # also matches hotels found by earlier sources
+            added = dedupe.merge_auto_v2(known, auto_hotels, auto_offers, photos)  # + earlier sources, + DB
             added_all += added
-            known += added
+            ids = {k["id"] for k in known}
+            known += [h for h in added if h["id"] not in ids]
```
`norm_name`, `_contains` and `merge_auto` can stay in place for the old tests, or be deleted once those tests call v2. Seeding `known` from the DB matters: without it, the source that runs first would re-create a dropped id.

## Migration (one time, before the next live run)
```powershell
python -m trips.dedupe                 # dry run: clusters + review list
python -m trips.dedupe --apply         # backup data/trips.db.bak-dedupe-YYYYMMDDHHMM, then fold
python -m trips.run --offline          # rebuild docs/data.json
```
`apply_clusters` does the following:
- Re-keys offers (the key starts with the hotel id) and their snapshots. When both ids had the same offer, it keeps the cheaper price point.
- Moves campaigns and the `hotel_image` row to the kept id.
- Rewrites `alert_sent` keys so alerts are not sent again.
- Drops the folded ids' rows from `drive_cache` and `hotel`.
- Fills gaps in a kept **auto** hotel (photo, stars, building coordinates, unknown family facts) from the rows folded into it. Curated rows are never touched.

## Known limits
- **Saved shortlists:** browser shortlists (`fdf.short` in localStorage) hold hotel ids, so a shortlisted dropped id disappears from the list. If that matters, `dedupe.aliases(clusters)` gives old → new ids. You could export it into `data.json` as `"aliases"` and map ids in `index.html` when loading `short`; that is not done here.
- **Area-only coordinates:** Olympic, Travelland, AtlantiS and BulgariaSki only give resort-level coordinates, so the 3 km check only applies to curated hotels and Savana.
- **Word lists:** GENERIC, SOFT and PLACES are hand lists. A new resort that is not in PLACES still works through the area string. A new chain brand needs adding to BRANDS.
- **Refreshed rows:** once the integrator's diff is in, a refreshed auto row overwrites any gaps the migration filled in from a dropped row.
