# Family prices from hotel pages (`family_prices`)

**Owner files:** `trips/family_prices.py` (new), `trips/enrich.py`, `tests/test_family_prices.py` (new, 17 tests),
`tests/test_enrich.py` (+1 test), `tests/fixtures/family_prices_cached_pages.json` (new: `page_summary()` of the 12
cached pages). Full suite: 186 tests OK.

## Why

276 of the 488 offers are "2+0" (2 adults only), so they can't be compared with real family prices. The detail pages
that `enrich.py` already reads say more: child-policy rules, price rows for 2 adults + 2 kids, room sizes, and a price per board.

## What it does

| Step | Rule | Output |
|---|---|---|
| 1. Real 2+2 rows | A price row with `Broj osoba: 2 (Deca: 2, Uzrast: a-b i c-d)` where both age ranges fit the twins on that date (`score.kids_age_on`), priced **per unit per day** or **per stay**. Rows priced per person are skipped because the kids' share isn't stated. The stay must fit inside the price period. You get one offer per period (the cheapest fitting room), at most 8 per page | Extra offers in the normal source shape: `occupancy "2+2"`, the same hotel/source/url, `room "<room> (family price from hotel page)"`, was/discount/valid_until taken from the row. `enrich()` appends them to the sightings list and skips duplicates |
| 2. Estimate | Only for a 2+0 offer priced **per person** (its room text says "osob") from the same site as the page. Both child 1 and child 2 need a stated rule at the twins' age: a `Popust` % (numbered or "each child") or a fixed `Doplata za N dete` € per night. Board supplements and the ambiguous "Dodatni ležaj … %" rules are ignored. When several rules apply to the same child, the dearest is used. No estimate if every room on the page sleeps fewer than 4 | `family_price_est` (€, whole stay) + `family_price_basis`, e.g. *"Estimate from the hotel's child policy for kids aged 3 on 2027-06-20: the first child stays free and the second child pays 20 % of an adult. +10 % for the kids. Needs a room for 4, which may cost more than the cheapest unit."* `price_eur` and `occupancy` are never changed |
| 3. Cheapest board | When the offer's board is "?" and the page prices 2 or more boards per person with one strictly cheapest | `board_cheapest` ("BB") + `board_cheapest_basis` ("Cheapest price on the hotel page is BB (€31.41 per person a night); HB from €36.89"). `board` stays "?" |

`enrich.apply()` now also keeps `rooms` (name, max_persons) and `board_prices` in `hotel["enriched"]`. That way `run.build`
can annotate offers read back from the DB (`family_prices.annotate(item, hotel["enriched"], cfg)`), which also works offline.
`enrich()` stats gain `family_offers`, `family_estimates` and `board_cheapest`, and these go into the log line.

## Integration diff: `trips/run.py` (integrator)

```diff
-from . import db, digest, enrich, geo, health, score, validate
+from . import db, digest, enrich, family_prices, geo, health, score, validate
@@ def build(con, cfg: dict, today: date, offline: bool = False)
             "campaigns": [{k: c[k] for k in ("title", "pct", "valid_until", "url")} for c in camps.get(h["id"], [])],
         }
+        # family_price_est/_basis (2+0 offers) and board_cheapest/_basis ("?" boards) from the hotel page
+        item.update(family_prices.annotate(item, h.get("enriched"), cfg))
         items.append(item)
```

No `db.py` or `config.toml` change is needed. The 2+2 offers from price tables are ordinary sightings, so they go
through validate → db → build like any other offer. The estimate fields are computed at build time from
`hotel["enriched"]`, which is already stored in the hotel row. The existing `hotel["enriched"]` rows have no `rooms` or `board_prices`
until the next live run re-applies the cache. Until then, estimates skip the room-size check and `board_cheapest` stays empty.

## Dashboard hint (`docs/index.html`, integrator)

In `priceBlock(h)`, after the `qual` span:

```js
const est = !fam && o.family_price_est
  ? `<span class="qual est" title="${esc(o.family_price_basis)}">≈ ${eur(o.family_price_est)} with the twins · estimate</span>` : '';
const bc = o.board === '?' && o.board_cheapest
  ? `<span class="qual" title="${esc(o.board_cheapest_basis)}">Board not stated · cheapest on the hotel page: ${BOARD[o.board_cheapest]}</span>` : '';
```

Suggested copy:
- **Estimate:** "≈ €554 with the twins · estimate". The tooltip is the basis text.
- **Real 2+2 rows:** they already show "2 adults + 2 kids"; the room ends in "(family price from hotel page)".
- **Board:** "Board not stated · cheapest on the hotel page: Bed & breakfast".

## Effect on the current data

Measured on the DB copy with `run.build(offline=True)` and `annotate`, and on `data/enrich_cache.json` (12 pages, 19 offers):

| | Before | After |
|---|---|---|
| 2+0 offers with a family estimate | 0 | **8** (Aegean Melathron ×2 +50 %, Elinotel Polis ×2 +10 %, Chrousso Village ×2 +25 %, Calypso ×2 +50 %) |
| Extra 2+2 offers from price tables (cache) | 0 | 0 (none of the 12 cached summer pages has a "Deca: 2" row) |
| Same, Grand Hotel Bansko fixture | – | **5** dated 2+2 offers (1-bed apartment, kids 0–5, e.g. 1–24 Dec €1,359 for 5 nights, was €1,699) |
| `board_cheapest` (cache) | 0 | 0 (Kassandra Palace's HB/FB rows carry no board tag; the others have one board or none) |
| Same, Mediterranean fixture | – | BB (€31.41 vs HB €36.89 pp/night) |

The other 11 cached-page offers get no estimate, for these reasons: Ammon Zeus, Kassandra Palace and Agnes have only extra-bed/board supplements; Alkyonis, Al Mare and Alkioni
have no child rules; Al Mare and Alkioni are priced per unit; Azul is a Travelland page with no rules. The cache only covers 12 of the ~174
Olympic/Travelland pages (budget 12 a run), so the counts should grow as the cache fills.

## Known limits
- An estimate assumes the cheapest unit's per-person price also applies to a room for 4. The basis says a family room may cost more.
- `child_rules()` de-duplicates rules across rooms and periods, so a room-specific rule can't be matched to its room. Using the dearest rule keeps the estimate on the high side.
- Age-range ends follow agency practice ("2 - 11" = 2.00–11.99). A trip right at a birthday edge can go either way.
- The cached price table keeps only the family rows plus 40 others, so `board_prices` comes from a sample of the rows.
- The 2+2 offers from price tables use the page's board only when it lists exactly one; otherwise "?".
- `tests/test_e2e.py::test_health_written_for_every_source` (another agent's file) expects `run.py` to pass the tracked session into `enrich.enrich(..., session=st_session)`. That is not related to this change.
