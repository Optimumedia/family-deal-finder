# manual_tools: `python -m trips.add_offer` + parent-facing README

## What changed

- **NEW `trips/add_offer.py`.** A CLI that appends correctly formatted `[[offer]]` entries to `data/offers.toml`.
  - **Flag mode** (default): `--hotel --check-in --nights --board --room --occupancy --price --was --label --valid-until --url --source --seen`.
  - **`--interactive` / `-i`**: asks one question at a time, with defaults in `[brackets]`, and asks again after a bad answer.
  - **`--paste "<Fibula result line>"`** fills in price, "was", board and hotel, plus nights, date and discount text when the line has them. For example, `… HB … 1.721 € ВКУПНО ОД 1.205 €` gives price 1205, was 1721, board HB. The price is the one after "ВКУПНО"; otherwise it's the lowest, and the "was" price is the highest one above it. Number formats `1.721`, `1.205,50` and `1,721` all work.
  - **`--again <no.|key|unique part of key>`**: copies the latest entry for that offer and records today's price. If the offer's `valid_until` has passed, the old was/label/deadline is dropped (`--clear-discount` forces that). The offer key is unchanged, so the price history builds up.
  - **`--list`**: offers whose last sighting is more than 7 days old (`--days N`), skipping trips that have already happened. Each is numbered for `--again`. `--list --all` shows every offer.
  - **Hotel names:** matched fuzzily to `data/hotels.toml`. Only near-identical spellings (ratio ≥ 0.88) count as a match. A merely similar name stops with "Did you mean …? (--hotel id)", and `--new-hotel` overrides that. This keeps "Xenios Possidi Holidays" from turning into Xenios Possidi Paradise.
  - **Unknown hotels** get a minimal `[[hotel]]` stub in `data/hotels.toml`: summer stubs go before the WINTER section, winter ones at the end. The stub has id, name, season, area, country, lat/lng, `border`, a note and `[hotel.family] verified = []`. Season, area and coordinates are copied from a known hotel in the same area (`--area Possidi` becomes "Possidi, Kassandra, Halkidiki"), or from the closest name. `docs/data.json` (the auto-found hotels) is used as a read-only extra reference. If nothing fits, it asks for `--season/--area/--lat/--lng`.
  - **Safety:**
    - Every entry goes through `trips.validate.problems` (using the `[validate]` config limits) plus `manual.REQUIRED`.
    - A second price for the same offer on the same day is refused: `db.add_sighting` ignores it for manual entries anyway.
    - After writing, both files are re-read with `manual.load` / `manual.load_hotels`. On any failure, both are restored.
    - `--dry-run` saves nothing.
- **NEW `tests/test_add_offer.py`** (22 tests). Covers:
  - paste formats and fuzzy matching
  - stubs (summer/winter, area lookup, the auto-found reference)
  - validation rejects that leave the file byte-identical
  - same-day duplicates
  - `--again` by number and by key, including a promotion that has ended
  - `--list`
  - interactive mode, including re-asking after bad input
  - TOML round-trip
  - an engine check: the stub plus offer go through `validate.split → db → run.build` and get scored, with "Sandy beach" left as an unknown must-have
- **`README.md` rewritten for the parents.** It covers:
  - what the dashboard shows
  - 2+2 vs 2 adults
  - verified / not confirmed / fake? discounts, and confirmed / agency / ask facts
  - adding Fibula prices
  - the schedule
  - what to do when a source fails, with the exit codes
  - short technical notes and a sources table
- **`data/offers.toml`:** header comment only (how to use the tool). No entry changed.

## Integration diffs

None needed: this is a stand-alone tool that writes the files the run already reads.

Optional, for the integrator: a weekly "re-check Fibula" reminder in the digest and What's new (`trips/run.py`, after `alerts = new_camps + alerts`):

```diff
     items, alerts = build(con, cfg, today, offline=args.offline)
     alerts = new_camps + alerts
+    from . import add_offer
+    old = add_offer.stale(add_offer.groups(sightings), today)
+    if old and db.mark_alert(con, f"recheck|{today.isocalendar()[0]}-W{today.isocalendar()[1]}", today.isoformat()):
+        alerts.append({"type": "recheck", "icon": "🔁", "url": "https://www.fibula.com.mk/",
+                       "text": f"{len(old)} Fibula price(s) are over 7 days old: run python -m trips.add_offer --list"})
```

Before adding it, check that `docs/index.html` renders an unknown alert `type` gracefully.

## Effect on current data

- **No change to the data.** `data/offers.toml` still loads 12 entries, 12 offers.
- **`--list` today (2026-11-26):** "Nothing to re-check: all 12 offers still ahead were checked in the last 7 days". All were seen on 2026-11-25.
- **From 2026-12-03,** all 12 will be listed for re-checking.
- **Dry runs on the real files:**
  - The README's example paste resolves to `xenios-anastasia` at €1205, was €1721, HB.
  - "Hotel Pirin Golf" becomes a winter stub in Bansko, using coordinates from the auto-found Pirin.

## Tests

- `python -m unittest tests.test_add_offer`: 22 OK.
- **Full suite: 281 tests, 3 failures and 7 errors, all in other agents' in-progress modules** (`test_audit`, `test_conditions`, `test_e2e`). None involve `add_offer`.

## Known limits

- **Paste parsing is a heuristic.** If a line has a per-person price but no "ВКУПНО", the lowest € amount is taken as the price. The tool prints what it read ("From the pasted line: …"), so check that line.
- **Stub coordinates are approximate** (copied from a hotel in the same town), and the stub's family facts are all unknown. That's intended: the rating stays capped and the dashboard says "ask".
- **`--again` numbers are positions** of unique offers in `offers.toml`. They stay stable while entries are only appended, but reordering the file by hand renumbers them.
- **The same-day price can't be corrected** by the tool: it says to edit `price_eur` by hand.
- **A stub whose name matches an auto-found hotel** gets folded into it by `run.merge_auto`, as for any curated hotel. The stub's (empty) facts win over the auto hotel's.
