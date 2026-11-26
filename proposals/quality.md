# quality: data audit + tighter validation

## What I changed (my files only)
- **NEW `trips/audit.py`**: `python -m trips.audit [--today YYYY-MM-DD] [--data …] [--db …] [--out docs/audit.json]`.
  - It is read-only. It opens the DB with `mode=ro` and never writes to `data.json`.
  - It prints a ranked report: severity first, then count. Each finding has counts by source, up to 3 examples, the likely cause, the file that owns the fix and the suggested fix.
  - It writes `docs/audit.json`: about 12 KB, one finding per line, 2 examples each.
  - It runs 15 checks:
    - **Stored offers:** each stored offer is re-validated against today's rules.
    - **Dates:** past check-in, check-in = scrape day, check-in more than 18 months ahead, season vs check-in month.
    - **Nights:** stay length against the page's configured nights.
    - **Prices:** per-night outliers per season, occupancy and kind.
    - **Discounts:** a "was" price not above the price, more than 80% off, and a badge % that doesn't match the was/price difference.
    - **Names:** adults-only or naturist properties shown as a fit, "(ex. …)" left in names, ALL-CAPS words, stars outside 1–5, and one hotel with several star counts.
    - **Places:** a country that doesn't match the area, coordinates outside the country, and areas beyond the drive radius.
    - **Duplicates:** the same offer twice, the same listing under two ids, and one name with several ids.
    - **Images:** placeholder, thumbnail-size and shared images.
    - **Kopaonik:** an RSD rate outside 110–125, and unit prices outside €30–600 a night.
    - **DB consistency:** orphan offers, offers with no snapshot, and hotels with no country.
- **`trips/validate.py`** (backward compatible: every new argument is optional):
  - **"Was" price:** it must be a number above the price, and the discount can be at most `max_discount_pct`. The default is 80, and it can be tuned in `[validate]`.
  - **`split(..., hotels=None)` / `problems(..., hotel=None)`:** when hotels are passed, a check-in outside the hotel's season is rejected. Summer is May–Oct, winter Nov–Apr.
  - **Duplicates in one batch:** a second row from the same source with the same hotel id, check-in, nights, board and price is rejected. With hotels passed, a row under another id with the same name and town is rejected too. This is the Savana star-category double listing.
  - **Placeholder photos:** agencies' "no photo" images (`listdefaultthumb.png`, `no-image`, `placeholder` …) now make `bad_image()` true, so `run.py` already nulls them on auto hotels with no diff needed. An offer `image` that is a placeholder is rejected.
- **Tests:** `tests/test_audit.py` has 13 tests. `tests/test_validate.py` has 4 new ones.
  - The full suite: 294 tests, all mine pass.
  - The 10 failures and errors are in other agents' in-progress files: `test_conditions` (a missing fixture) and `test_e2e` (Olympic parses 0 offers before validation).

## Integration diffs (files I don't own)

### `trips/run.py` — stop publishing past or now-invalid stored offers (finding #1, #2)
```diff
@@ def build(con, cfg: dict, today: date, offline: bool = False)
     offers = db.offers(con)
+    lim = validate.limits(cfg)
     photos = db.images(con)
@@
     for o in offers:
         h = hotels.get(o["hotel_id"])
         if not h:
             log.warning("offer for unknown hotel %s — add it to data/hotels.toml", o["hotel_id"])
             continue
+        last = o["history"][-1]
+        why = validate.problems({**o, "hotel": o["hotel_id"], "price_eur": last["price_eur"],
+                                 "was_eur": last.get("was_eur")}, today, lim, h)
+        if why:                       # past stay date, or saved before a rule existed: keep history, don't publish
+            log.info("not published %s: %s", o["key"], "; ".join(why))
+            continue
         peers = [p for p in offers if hotels.get(p["hotel_id"], {}).get("season") == h["season"]]
```

### `trips/run.py` — give validate the hotels (season rule + Savana double listings)
```diff
     for h in curated:                      # curated facts always win
         db.upsert_hotel(con, h)
-    sightings, rejects = validate.split(sightings, today, cfg)
-    auto_sightings, auto_rejects = validate.split(auto_sightings, today, cfg)
+    hv = db.hotels(con)                    # every hotel is upserted by now (auto + curated)
+    sightings, rejects = validate.split(sightings, today, cfg, hv)
+    auto_sightings, auto_rejects = validate.split(auto_sightings, today, cfg, hv)
```
If `dedupe.merge_auto_v2` (proposals/dedupe.md) lands, it already folds most same-source doubles. The validate rule then only catches what is left; both are safe together.

### `config.toml`
```toml
[validate]
max_discount_pct = 80      # optional; this is the default
```
**Areas beyond the drive limit (finding #5):**
- These pages are scraped every run, but every offer from them is excluded: Pamporovo is 424 min away, Ulcinj 386 and Dobre Vode 380, and they have no direct flight.
- That is 28 offers:
  - Pamporovo: Travelland 9, AtlantiS 8, Olympic 3, BulgariaSki 3
  - Ulcinj: Travelland 1, Olympic 3
  - Dobre Vode: Olympic 1
- Suggest `enabled = false` on the 4 Pamporovo pages, the Olympic and Travelland Ulcinj pages, and Dobre Vode, unless a charter makes them reachable.

## Source-parser bugs for the owners
| # | File:line | Problem (count on 2026-11-25 data) | Cause | Suggested fix |
|---|---|---|---|---|
| 1 | `trips/sources/travelland.py:142` | 3 winter offers have check-in = the scrape day (Grand Hotel Bansko, Casa Karina, Rila Borovets, 2026-11-25). The next day they are in the past. | `check_in = max(card["date_from"], today)`: when the card's price window has already started, the check-in becomes today. The winter pages have no `check_in` in config. | Use `max(date_from, page check_in or today + 14 days)`, and skip the card if `check_in + nights > date_to`. Add `check_in = "2027-01-15"` to the 3 winter Travelland pages. |
| 2 | `trips/sources/charters.py:135` (`"id": f"sv-{card['slug']}"`) | 3 hotels appear twice at the same price (Melike 2★/3★, Aargau 2★/3★, Mesut 2★/3★). Derici is listed as 4★ and as 1★ at different prices. | Savana publishes one card per star category, and the slug carries `-N-stars-`, so each category becomes its own hotel id. | Build the id from the slug with `-\d-stars` removed. In `fetch`, keep one card per id: the higher star count and the lower price. |
| 3 | `trips/sources/charters.py:49` (`_SLUG_TOWN`) | Slugs without `-N-stars-` get the page area (`otel-ponz-kusadasi-turkey` → "Kusadasi, Turkey" instead of "Kusadasi, Aegean coast, Turkey"). This splits one town into 2 areas. | The regex requires `-(\d)-stars-`. | Make the stars part optional: `(?:-\d-stars)?-(?P<town>[a-z]+)-(?P<country>…)$`, so the town is one word before the country. |
| 4 | `trips/sources/charters.py:122` (`_clean_name`) / the id | `otel-palm` and `palm` are both Palm, Kusadasi (2 ids). | Only the name drops "Otel", not the slug. | Strip `^otel-` / `-otel$` from the slug used for the id. |
| 5 | `trips/sources/charters.py:99` | 22 Antalya-region offers are 6-night stays, while the page is configured for 7. | It takes the stay whose price equals the "from" price, and that is often the 6-night one. | When `stays` includes the configured nights, use that stay and its own price. Fall back to the cheapest stay otherwise. |
| 6 | `trips/sources/kopaonik.py:309-310` | 8 Konaci offers are 3-night stays, while the page wants 7. | Columns with a "ZA NAVEDENI BROJ NOĆI" stay total and a 3-night minimum are kept with `n = p["nights"]`. | Skip a stay-basis column when `p["nights"] < want`, or use the period's daily table (the "DNEVNE CENE" block under it) times `want`. |
| 7 | `trips/sources/travelland.py:112`, `trips/sources/olympic.py:89`, `trips/sources/bgski.py:155` | 4 names keep "(ex. …)": Forestia (ex. Moura), Four Points by Sheraton Bansko (ex. Strazite), Chalet Evergreen (ex. Breza), and the config name "Apartmani Šumarstvo (ex Srbijašume)". | Only `charters._clean_name` strips it. | Apply `re.sub(r"\s*\(\s*ex\.?[^)]*\)", "", name, flags=re.I)` and keep the old name in `notes`. Rename the Kopaonik page `name` in config. |
| 8 | `trips/sources/mk_agencies.py:120` | Terra Hotel (Razlog) shows AtlantiS's "no photo" image (`atlantisonline.mk/ExtraContent/Img/listdefaultthumb.png`). | The card's default thumbnail is taken as the photo. | `validate.bad_image` now nulls it at merge time, so no change is needed. Optionally skip `/ExtraContent/Img/` in the parser. |
| 9 | `trips/sources/oliverstravels.py:48` | All 5 villa photos are `?profile=sm` thumbnails. | The slider's small profile is used. | Ask for the large profile (check one card for the right name, e.g. `profile=lg`) or drop the query. Also skip villas with more than 4 bedrooms: Villa Lagomandra has 5 bedrooms at €25.9k/week, which `validate` already rejects above €2,500/night. |
| 10 | `trips/score.py` (hard rules) or `trips/sources/olympic.py` | "Serenity Suites (Adults only 12+)" (Sithonia, 338 min) is shown as a fit for a family with toddlers. | Nothing reads "adults only" from the name. | In the source parser, set `family.adults_only = True` when the name matches `adults?[ -]only|\b1[2-8]\+`. Make it a failed must-have in `score.py`. |
| 11 | `trips/sources/olympic.py:116` | One hotel appears under 2 object ids: Secret Paradise `ol-103035`/`ol-114144` (same price) and Alkyonis `ol-103028`/`ol-114134`. | Olympic lists some hotels twice; the id is the object id. | This is covered by `dedupe.merge_auto_v2`. The validate name-dedupe drops the same-price copy until then. |

Checked and fine:
- **Kopaonik RSD:** JAT is natively in EUR. The Supernova Konaci and Stara Planina tables re-parse to the stored prices at 117.2 RSD/EUR. Stara Planina at €338–486/night is the per-apartment half-board-plus price ("PO APARTMANU PO NOĆI"), not a unit error.
- **No other problems found:** no country/area mismatches, no summer dates in winter, no check-ins more than 18 months ahead, and no "was" price at or below the price or more than 80% off.

## Effect on the current data
These are the new rules replayed over the 488 published offers, as sightings:

| today | hotels passed? | kept | rejected |
|---|---|---|---|
| 2026-11-25 | no (rules as now) | 487 | 1 (Villa Lagomandra, already over €2,500/night but stored before the rule) |
| 2026-11-25 | yes | 483 | 5 (+3 Savana and +1 Olympic same-price duplicates) |
| 2026-11-26 | yes | 480 | 8 (+3 Travelland past check-ins) |

- **Placeholder photo:** 1 hotel (`atl-terhotjjzt`) loses its placeholder at the next live run.
- **Audit:** `python -m trips.audit --today 2026-11-26` gives 14 kinds of problem in 98 rows. 6 of those rows are high severity.

## Known limits
- The price-outlier bands are relative (median ÷ 2.5, × 3 per season, occupancy and kind). Real luxury places (Sani Beach €878/night) and cheap apartments next to villas show up as low-severity notes, not as errors.
- The nights-mismatch check needs a page in config whose `area`/`region` is part of the offer's area. Manual offers are not checked.
- The adults-only and naturist check reads names only; a hotel whose name doesn't say it is missed.
- The audit reads the published `data.json`. Offers that `build()` skipped never show up in it.
