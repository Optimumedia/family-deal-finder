# Detail-page enrichment (Olympic + Travelland)

**Module:** `trips/enrich.py` · **Tests:** `tests/test_enrich.py` (10 tests, no network) ·
**Fixtures:** `tests/fixtures/enrich_olympic_{mediterranean,porfi,grandbansko}.html`,
`tests/fixtures/enrich_travelland_grandroyale.html`. These were saved on 25.11.2026, with scripts, styles and `<option>` lists removed.

## Why

130 of the 149 offers are Olympic/Travelland list cards with `board = "?"` and `occupancy = "2+0"`, and their family facts are unknown. Each card links to the hotel's detail page. robots.txt allows that page on both sites, and it states most of what we need:

| On the detail page | Becomes |
|---|---|
| Per-room price tabs `BB – bed and breakfast` / `HB – half board`, the `data-pricelistsService` map, or the `Usluga: …` line | `board_options` (e.g. `["BB","HB"]`). `half_board = true` when HB/FB/AI is offered |
| `Udaljenosti → Plaža 80 m` | `beach_m` |
| `pesak / peščana` vs `šljunak` (in a beach sentence) | `beach_type`, `sand_beach` (stays unknown for mixed beaches or "zlatna plaža") |
| "direktno na plaži" | `beachfront` (no metre value is made up) |
| `Bazen za decu`, `dečiji klub`, `Dečije igralište`, `igraonica`, kids' animation, `Deca dobrodošla` | `kids_pool`, `kids_club` (+ `kids_club_min_age` when stated), `playground`, `playroom`, `kids_animation`, `kids_welcome` |
| `Samo za odrasle 12+` | `adults_only`, `adults_only_min_age` |
| `Popust za 1 dete (0 - 2)` 100 %, `Doplata za 2 dete (2 - 11)` | `child_policy` rules. `first_child_free_max_age` is set when only the 1st child is free, `kids_free_max_age` when every child is |
| Room cards "1 BEDROOM APARTMENT", "zasebnu spavaću sobu", "spavaća soba i dnevni boravak", Family rooms, max persons ≥ 4 | `rooms[]`, `separate_bedroom`, `family_room` ("kombinovani dnevni boravak-spavaća soba" does **not** count) |
| Price rows (period, min stay, offer label, valid until, old/new, unit, `Broj osoba: 2 (Deca: 2, Uzrast: 0-5 i 0-5)`) | `price_table[]`, `price_2plus2_listed` |

Nothing is ever set to `false` just because a word is missing. The only `false` is `sand_beach` when the page says pebble. The "Moglo bi vam se sviđati" block (other hotels) and the footer are cut off before parsing. Evidence is kept as the short matched term only (e.g. `"Bazen za decu"`), never as description text.

What came out of the five pages read live on 25.11.2026:
- **Mediterranean Resort:** BB/HB, beach 80 m, kids' pool, playground, 1st child 0–2 free.
- **Porfi Beach:** BB/HB, beach 10 m, beachfront, Family Suite with a separate bedroom, animation.
- **Grand Hotel Bansko:** HB or AI, kids' club, kids' pool, 1-bedroom apartment, real 2+2 prices for kids 0–5.
- **Grand Royale (Travelland):** BB/HB, kids' club, 1- and 2-bedroom apartments.
- **Elida (Travelland):** BB only, adults only 12+ (so its board would be set to BB).

## Integration in `trips/run.py`

Call it once, after all `AUTO_SOURCES` have run and been merged and before anything is stored, so the hotels and offer boards it fills are the ones written to the DB:

```python
from . import enrich            # new import

    if not args.offline:
        known = list(curated)
        added_all = []
        photos = {}
        for src in AUTO_SOURCES:
            auto_hotels, auto_offers = src.fetch(cfg, today)
            added = merge_auto(known, auto_hotels, auto_offers, photos)
            added_all += added                       # was: db.upsert_hotel(...) here
            known += added
            sightings += auto_offers
        if cfg["sources"].get("enrich", {}).get("enabled"):
            enrich.enrich(sightings, known, cfg, today)          # budget/cache from config
        for h in added_all:
            db.upsert_hotel(con, h)
        ...
    for h in curated:                      # curated facts always win (unchanged)
        db.upsert_hotel(con, h)
```

- `known` holds the curated hotels as well. enrich only fills keys that are still `None` and never touches `verified`, so a hand-entered value is never overwritten. Enriched facts count as *known but unverified*, so the confidence factor stays honest.
- Offers folded into a curated hotel by `merge_auto` already point at the curated id, so they enrich that hotel.
- `--offline` never calls it.

## Config block (add to `config.toml`)

```toml
[sources.enrich]
# Read each Olympic/Travelland offer's hotel page for board, child policy, beach and kids' facts.
# Facts are cached per page and re-read at most once a week.
enabled = true
budget = 12                 # live detail pages per run (6–10 s apart → about 2 minutes)
max_age_days = 7
cache = "data/enrich_cache.json"
```

There are about 130 agency pages. At 12 a run and 2 runs a day, the first pass takes about 6 days. After that, 24 reads a day covers the ~19 a day that the weekly refresh needs. While the cache is warming up, the pages that matter most go first: offers whose board is `?`, then hotels with unknown must-haves. A page older than a week is still used while it waits for budget. A bot wall (`Blocked`) stops that host for the rest of the run.

**Cache:** `data/enrich_cache.json` = `{"version":1,"pages":{"olympic.rs/<path>/": {fetched, parser, board_options, family, evidence, child_policy, distances, rooms, price_table (2-kid rows + ≤40 others)}}}`. That's about 15 KB a page, so about 2 MB in total. I suggest adding it to `.gitignore`, since runs happen on the home PC. Bumping `PARSER_VERSION` makes every entry count as stale.

## Things the integrator should know

1. **Offer key changes once.** `db.offer_key` includes `board`. An offer that goes from `?` to `BB` becomes a new key, so its price history restarts once. After that it stays stable, because the cache keeps giving the same board. If you'd rather keep the history, migrate the old key's snapshots (or drop `board` from the key) in the same change.
2. **Board stays `?` when there are 2 or more options.** Most Olympic hotels list both BB and HB, so `board` stays `?` for them. That's correct: the card price is the cheapest, usually BB. `score.py` could read `family.half_board` (HB is offered) to turn "Breakfast + dinner" from *unknown* into *available at extra cost*. That needs a small change in score.py.
3. **New fact keys that score.py doesn't use yet:** `adults_only` (should be a hard "no" for this family), `first_child_free_max_age` / `kids_free_max_age` (compare with the twins' age), `beachfront`, `price_2plus2_listed`.
4. **Real 2+2 prices.** For hotels like Grand Hotel Bansko, `price_table` rows with `occupancy.kids == 2` and `kid_ages` "0-5 i 0-5" are real family prices per unit per day. A follow-up could turn them into extra `"2+2"` offers. That isn't done here, because it changes how offers are counted.
5. **Travelland price lists** load after the page (JS), so we get only the room "from" prices (`rooms[].from_eur/was_eur`), not a price table.
6. Request count: `budget` counts page reads. robots.txt is fetched once per host per session by PoliteSession.
