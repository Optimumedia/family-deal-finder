# bgski — BulgariaSki (bulgariaski.com) price lists for Bansko / Borovets / Pamporovo

## What it is
BulgariaSki is a Sofia ski-holiday agency (78 Krichim Str., Sofia) with one page per hotel in each
resort. Unlike Olympic/Travelland "from" cards, every hotel page carries the hotel's **full winter
2026/27 price list in plain HTML**: one row per room type (incl. "One-bedroom apartment",
"2-bedroom family apartment with kitchenette" …), its meal code (RO/BB/HB/FB/AI), and a rate per
season column whose date ranges sit in the column tooltip. Rates are EUR **per night per
room/apartment** (stated under the table), so a 5-night stay is priced night by night, across
season boundaries. The page also has promo boxes ("- 10 % discount until 30 Nov 2026") and price
notes (max occupancy per apartment, children's reductions age, baby-cot fee).

## robots.txt (https://www.bulgariaski.com/robots.txt, checked 2026-11-25)
```
User-agent: *
Disallow: /cms_view.php*
Disallow: /create_pdf.php*
Disallow: /booking.php*
Disallow: /search.php*
Disallow: *query=*
Disallow: *contact-us*
```
We only read `/<resort>/hotels/` (list) and `/<resort>/<hotel>.html|.shtml` (hotel pages) — both
allowed. No search form, booking form or query string is used. No bot wall seen.

## Config block to add to config.toml
```toml
[sources.bgski]
# bulgariaski.com — robots.txt allows the resort hotel lists and hotel pages. Each hotel page has
# the full price list (EUR per night per room/apartment, by season). We keep the cheapest
# 1-/2-bedroom apartment row per meal plan; hotels with only rooms/studios are skipped.
enabled = true
max_hotels = 30             # hotel pages per resort (after the name filter); ~6-10 s each
# match = "apart|residen|complex|club|chalet|holiday|family|villa|house|resort|suite"   # default name filter

[[sources.bgski.pages]]
url = "https://www.bulgariaski.com/bansko/hotels/"
season = "winter"
area = "Bansko, Bulgaria"
country = "BG"
lat = 41.83
lng = 23.48
nights = 5
check_in = "2027-01-15"

[[sources.bgski.pages]]
url = "https://www.bulgariaski.com/borovets/hotels/"
season = "winter"
area = "Borovets, Bulgaria"
country = "BG"
lat = 42.266
lng = 23.606
nights = 5
check_in = "2027-01-15"

[[sources.bgski.pages]]
url = "https://www.bulgariaski.com/pamporovo/hotels/"
season = "winter"
area = "Pamporovo, Bulgaria"
country = "BG"
lat = 41.652
lng = 24.692
nights = 5
check_in = "2027-01-15"
```
A page may instead carry `hotels = ["https://www.bulgariaski.com/bansko/regnum_apartments.html", …]`
to skip the list page and the name filter; `match = ""` (empty) fetches every hotel on the list.

## Live check (2026-11-25, check-in 2027-01-15, 5 nights)
LIVE_RESULTS

## How offers are built
- Per hotel and meal code: the cheapest row whose name says one/two/three-bedroom (or "separate
  bedroom") → `family.separate_bedroom = True`, `kind = "apartment"` when the row is an apartment.
- No bedroom row → cheapest apartment / suite / family row, `separate_bedroom` left unknown.
  Only singles/doubles/studios → no offer.
- `price_eur` = sum of the nightly rates for the stay; if a night falls outside the price list
  the row is skipped (no guessing).
- Discount: the best promo whose deadline is still ahead and carries no "not valid for period …"
  condition → `was_eur` = list price, `price_eur` = list × (1 − %), label "Early booking -10%",
  `valid_until` = the deadline.
- `occupancy` is always "2+0": the rate is per apartment, but pages say children's reductions
  start at age 2 and many 1-bedroom units are listed as "2 adults + 1 child" — that fact is put in
  the hotel `notes`, together with the baby-cot fee when stated.
- Hotel id `bs-<site hotel number>` (from the photo path), photo hotlinked from
  `/hotel-images/big/<n>_0.jpg`.

## Known limits
- List prices are the agency's published rack rates; the real quote comes from their booking
  form (robots-disallowed `/booking.php`), so "2+2" totals and cot counts stay "ask".
- "7=6 / 14=12" free-night extras are not applied (our stays are 5 nights).
- Promos with period exclusions are ignored rather than half-applied.
- The site sends no charset header; requests decodes as Latin-1. All prices/names we use are ASCII,
  so this only affects the odd Cyrillic word in descriptions we don't store.
- Name filter is a heuristic: some hotels with apartment rows but a plain "Hotel" name are skipped
  unless `match = ""` or listed under `hotels`.
- About 1 request per hotel page; with the default filter a full run is ~45 requests (~7 min at
  6–10 s spacing).

## Needs the integrator
- Add `bgski` to `AUTO_SOURCES` in `trips/run.py` (import from `.sources`).
- Add the TOML block above to `config.toml`.
- No new fields: offers use the existing shape; `board` may be "RO" for rent-only apartments.
