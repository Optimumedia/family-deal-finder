# Scoring: Family Fit on the enrichment facts and tier calibration (agent `scoring`)

**Files:** `trips/score.py`, new `tests/test_family_fit.py` (21 tests). `tests/test_engine.py` and
`tests/test_deal_engine.py` pass without changes.

## What changed

### Family Fit (`family_fit`)
`score = sum(parts) × confidence`. Every part is listed in `family.parts`. The new `family.explain` says where the less obvious points come from, for example "1st child free up to 2: …" or "Separate bedroom from the room name (One-bedroom)".

| part | pts | summer | winter |
|---|---|---|---|
| sleep | 18 | separate bedroom 1 / family room 0.85, plus 2 cots | separate bedroom, 2 cots, unit for 4 or more |
| beach / activities | 22 | sand 0.5, distance or beachfront 0.35, shallow 0.15. Pebbles halve it | ski kindergarten 0.6, kids' pool 0.2, playroom/club 0.2 |
| travel | 15 | up to 3h = 100%, the 5h limit = 40%, borderline = 20%, direct flight = 80% | same |
| kids | 12 | kids' club for age 3, kids' pool, playground/playroom/animation | same |
| **kids_cost** | 8 | `kids_free_max_age` / `first_child_free_max_age` against the twins' age on check-in. The limit is exclusive: "0–2 free" means under 2 | same |
| food | 10 | HB/FB/AI 1, **HB offered but not priced 0.75**, `?` 0.35, SC 0.5, BB 0.2 | SC 0.9, HB+ 1, HB offered 0.8 |
| health / logistics / reviews | 5 / 4 / 6 | doctor, stroller, stars | same |

- **Unknown facts:** an unknown must-have scores 0.35 and still triggers the `unknown_cap`. An unknown nice-to-have scores 0.5.
- **Confidence:** `0.85 + 0.15 × the share of known facts that are verified`. It used to be `0.6 + 0.4 × …`, which held every unverified hotel below 60.
- **`half_board` with board `?`:** the checklist state is the new **`"available"`**, labelled "Breakfast + dinner — available (check price)". It counts as satisfied rather than unknown, and adds a question about the HB supplement. A *priced* BB offer still fails.
- **`beachfront`:** counts as being on the beach even when no distance in metres is given.
- **`sand_beach = false`:** the offer stays excluded (it is a must-have), and its beach points are halved. If `need_sand = false`, pebbles still cost at least 8 Fit points.
- **Winter separate bedroom:** filled in from the room name when the hotel fact is unknown. That covers "1-/One-bedroom", "2 rooms", "dvo/trosoban", "spavaća soba", maisonette and duplex. "Studio" and "2+1 Apt" stay unknown, and a hotel-level `false` always wins. "Up to N guests" with N ≥ 4 counts as fitting the four of them.
- **Adults-only:** still excluded.
- **Occupancy:** still never changes Family Fit (`kids_cost` comes from the policy).

### Deal and overall
- **Stated-only discount:** it earns `stated_pct / 0.5 × stated_weight`, where it used to be `/0.25`. A "−25%" claim is now worth at most about 4 overall points.
- **`UNPROVEN_CAP = 79`:** an offer without a `real` verdict cannot rise above "Great deal". "Exceptional" and "Once-in-a-lifetime" need a saving that our own price history confirms. When this applies, a note goes into `deal.notes`.
- **Tier floors unchanged** (90/80/70/55). They are now reachable:
  - fully confirmed, well-matched 2+2 HB offer at a flat price: Fit 97, **71.5 Great**
  - the same offer from agency info only: 63.5 Good
  - cots unknown: 68.9, capped at 69 or below
  - −60% claim stated only: held at 79

## Effect on current data
(`python -m trips.run --offline` on a copy of `data/trips.db`. `docs/data.json` and `data/digest.txt` were restored afterwards.)

| | before | after |
|---|---|---|
| tiers of the 398 fitting offers | 398 Worth a look | **3 Good deal**, 395 Worth a look |
| overall max / median | 54.4 / 29.8 | 59.3 / 38.3 |
| Family Fit max / median | 43.9 / 29.7 | 62.0 / 46.0 |
| offers ≥ 50 / ≥ 45 | 3 / 6 | 12 / 58 |
| summer board unknown → "available" | 0 | 9 (+2 winter) |
| winter separate bedroom "yes" | 35 | 51 (16 from room names) |
| unknown must "Breakfast + dinner" | 116 | 109 |

Why there is no "Great" yet: **all 398 offers have unknown cots**, and nothing is verified, so everything is capped at 69. The rest of the fitting offers sit below "Good" because:
- 206 are 2+0 prices, whose deal score is low by design;
- Halkidiki is at the 5h limit (travel 20–40%);
- only 12 hotels are enriched so far. As the enrich cache warms up, more summer hotels gain sand, beach, HB and kids facts and move into "Good".

## Integration
- **None needed** in `run.py`, `db.py` or `config.toml`.
- **UI (`docs/index.html`, owner: UI):** the checklist state `"available"` currently falls into "Not known yet: ask the hotel". The label still reads "available (check price)", so this is acceptable. Suggested change in `checklist()`: add a group `['Offered, not in this price', c => c.state === 'available', () => '<span class="mk yes unv" aria-hidden="true"></span>']` and exclude `'available'` from the "Not known" test. Optionally show `family.explain.kids_cost` in the drawer.

## Known limits
- The free-child limit is read as exclusive ("0–2" means under 2). Agencies that mean "up to and including 2" will be scored on the safe side.
- The room-name bedroom match is per offer. A hotel whose cheapest priced unit is a double room but which has a 1-bedroom apartment keeps the hotel-level fact.
- `doctor_near` and `stroller_ok` are never collected, so 9 points stay neutral (0.5) for every hotel.
