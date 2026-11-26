# Parser fixes: Travelland, Olympic, hotel websites (agent: `parsers`)

Done on 2026-11-26. I made 14 live requests, 6–7 s apart, all through `PoliteSession`
(robots.txt fetched and obeyed on both hosts): 3 robots.txt, 2 Travelland destination
pages, 7 Travelland list calls (one connection reset and retried) and 2 Olympic list calls.
No full live run. Saved answers are now fixtures.

## What I changed

### `trips/sources/travelland.py`
- **Tag-category pages.** The new optional page key is `tag_category = 564`. It sends
  `/services/list/?destination=&tagCategoryId=564&…` and needs no page request. Without
  `destination` or `tag_category`, the page is fetched as before. Its code now comes from the
  offer list itself (`<div class="list-featured" data-destination=…>`), not from the search form.
  If that code is empty, the page's `data-tagCategoryId` is used.
- **Paging bug (new finding).** Travelland answered `paginate=1`, `2` and `3` for Thassos with the
  same 12 hotels. On 25.11 the log said "Bansko: 36 offers", but `data.json` has only 12 Bansko
  offers, because the same 12 hotels came three times. Hotels 13–30 were never reached.
  - `fetch` now also sends `_page=N`, the parameter Olympic's copy of the platform honours.
  - It stops as soon as a page adds no new hotel id, and never adds the same hotel twice.
  - I had no request budget left to check that Travelland honours `_page`, so I didn't verify it.
    If it does, Bansko goes from 12 to about 30 hotels. If it doesn't, nothing changes except that
    one request per destination is saved.
- **Kassandra and Sithonia gave 0 (checked live, 2 list calls).** Both list answers are
  `{"html":"<p class=\"lead\">Ponuda stiže uskoro!</p>","total":0}` ("offer coming soon").
  Travelland simply has nothing listed there yet. Sithonia uses the region code `89:1042`, which is
  also the Athos code. The parser is fine. Keep the pages: they'll fill for 2027. They need a
  `check_in` (diff below), or summer cards would get today's date.
- The log line now says `hotels of total listed, offers`.

### `trips/sources/olympic.py`
- **All pages are read (checked live on Ohrid).** `_page=2` and `_page=3` gave 12 and 2
  hotels that don't repeat (26 in total). The 25.11 run's "26 listed, 16 priced" was correct.
  `fetch` now counts distinct hotel ids. It stops when it has seen `total` hotels, when a page is
  empty, or when a page adds nothing new, so it can't loop or double-count.
- **Board in other markup.** The board is now read from any `div`, `span` or `p` with a
  `text-uppercase…` class under "Najbolja cena". The fallback is a clear board phrase anywhere on
  the card (Polupansion, Pun pansion, All inclusive, Noćenje i doručak).
- Most "?" boards are genuine: Bansko cards and many Ohrid cards have no board line at all, so
  enrich has to fill those. The 114 "?" out of 139 Olympic offers mostly stay "?" from the list.

### `trips/sources/hotel_direct.py`
- **One fetch per URL per run.** A page shared by several hotel entries is fetched once, and a
  failure is cached too. With the current 28 entries that saves 7 requests (mpmhotels ×5,
  acrotel ×3, secretparadise ×2).
- **New keywords:**
  - Bulgarian: отстъпка, намаление, промоция, оферта, ранно записване / ранни записвания
  - Greek: έκπτωση, προσφορά, έγκαιρη/πρώιμη κράτηση
  - Serbian Latin and Cyrillic: popust, akcija, ponuda, ranije rezervacije, попуст, акција, рано резервисање
  - also: `first minute`, `EB`
- **Loyalty is skipped by default.** These count as loyalty:
  - a loyalty word in the % clause: returning, repeat or regular guests, members, loyal,
    "visit us often", "continued trust", stalni gosti, постоянни клиенти, член, μέλη, πιστοί πελάτες
  - a loyalty word in the sentence or in the heading line above it, when that holds only this one %
  - a page with `kind = "loyalty"`, or a members/loyalty URL

  With `include_loyalty = true` they're kept as `kind: "loyalty"`. Every campaign now carries
  `kind` (`campaign` or `loyalty`).
- **Noise is checked per clause**, so "EB −10% … 30% payment in advance" keeps the 10% and drops the 30%.
  - Payment terms: deposit, prepayment, payment in advance, депозит, аванс, προκαταβολή, kapara, avans
  - Taxes: VAT, tax, ДДС, ΦΠΑ, PDV
  - Spa, massage, restaurant and drinks extras
  - "Book 60 days in advance and save 15%" is kept.
- **Near-identical campaigns on a page are kept once**, with the fuller text. Two count as the same
  when they have the same %, and either the same deadline or ≥70 % shared words.

## Effect on current data (offline, same pages)

I ran the old and new `campaigns()` on every hotel page in `data/http-cache.sqlite` plus the 3
fixtures. Old: 19, new: 15 (plus 2 loyalty when `include_loyalty`).

| page | old → new | why |
|---|---|---|
| mpmhotels.bg | 2 → 4 | the two 50 % items merged; three "до 25% отстъпка" hotel items are now found (Bulgarian keyword) |
| portocarras.com | 2 → 1 | 15 % "Direct Booking & Loyalty Benefits" is loyalty |
| saintivanrilski.com | 3 → 2 | 5 % "for your continued trust" is loyalty |
| sani-resort.com | 3 → 2 | two 5 % items with the same 1 December deadline merged |
| grandkopaonik.com | 2 → 1 | "50% popusta na spa tretmane" dropped |

The other 34 DB campaigns come from pages not in the cache. Applying the rules to their stored titles:
- Dropped as loyalty: Portes 5 %, Melathron members-club 10 %.
- Merged as duplicates: Royal Park "EB −10%" with its long version, and Pirin's two −10 % lines.

Net per run, with the mpm group fanned out to 5 hotels: about 34 → 36 campaigns and 28 → 21 requests.

Travelland: Thassos (tag 564) adds **7 priced offers** from list page 1 today: 7–27 % off,
valid until 30.11.2026. If `_page` is honoured, up to 31 hotels are listed. Bansko and Borovets
duplicates stop either way.

## Integration (config.toml, owned by the integrator)

1. Add `check_in` to the two Travelland Halkidiki pages:

```diff
 [[sources.travelland.pages]]
 url = "https://www.travelland.rs/destinacije/grcka/letovanje/hoteli/halkidiki/kasandra/"
+destination = "89:60:2364"
 season = "summer"
 area = "Kassandra, Halkidiki"
 country = "GR"
 lat = 40.02
 lng = 23.43
 nights = 7
+check_in = "2027-06-20"

 [[sources.travelland.pages]]
 url = "https://www.travelland.rs/destinacije/grcka/letovanje/hoteli/halkidiki/sitonija/"
+destination = "89:1042"
 season = "summer"
 area = "Sithonia, Halkidiki"
 country = "GR"
 lat = 40.10
 lng = 23.80
 nights = 7
+check_in = "2027-06-20"
```

2. New Travelland pages:

```toml
# Thassos: a tag-category page (data-destination=""), checked 2026-11-26: 31 listed, 7 priced on page 1
[[sources.travelland.pages]]
url = "https://www.travelland.rs/destinacije/grcka/letovanje/hoteli/tasos/"
tag_category = 564
season = "summer"
area = "Thassos"
country = "GR"
lat = 40.70
lng = 24.65
nights = 7
check_in = "2027-06-20"

# Olympic Riviera: also a tag page, tag id NOT checked. Leaving tag_category out makes fetch read the
# page's own data-tagCategoryId (1 page request per run). The URL is the one in proposals/destinations.md;
# confirm it opens before adding.
[[sources.travelland.pages]]
url = "https://www.travelland.rs/destinacije/grcka/olimpska-regija/"
season = "summer"
area = "Olympic Riviera (Paralia, Leptokaria)"
country = "GR"
lat = 40.27
lng = 22.60
nights = 7
check_in = "2027-06-20"
```

The `area` strings match the Olympic pages, so the same hotels merge across sources.

3. Optional hotel_direct keys (the defaults already work):

```toml
[sources.hotel_direct]
include_loyalty = false     # true: keep loyalty perks, tagged kind = "loyalty"

# per page, for a members-only page whose URL doesn't say so:
# kind = "loyalty"
```

4. Optional, for the dashboard to show loyalty perks greyed out (only if `include_loyalty = true`).
   `kind` is not stored yet. Changes needed in `trips/db.py`:
   - add `kind TEXT DEFAULT 'campaign'` to `CREATE TABLE campaign`, plus a migration:
     `ALTER TABLE campaign ADD COLUMN kind TEXT DEFAULT 'campaign'` inside a try/except
   - in `add_campaign`, insert `c.get("kind", "campaign")`

   In `trips/run.py` line 69, add `"kind"` to the copied fields:
   `{k: c.get(k) for k in ("title", "pct", "valid_until", "url", "kind")}`

No change is needed in `run.py` for the URL cache or the Travelland and Olympic fixes.

## Tests and fixtures

New fixtures:
- `travelland_list_thassos_tag564.json`
- `travelland_list_coming_soon.json`
- `olympic_list_ohrid_p2.json`
- `olympic_list_ohrid_p3.json`

New tests in `tests/test_travelland.py`, `tests/test_olympic.py` and `tests/test_new_sources.py`
(`HotelDirectLanguagesAndFilters`): 15 tests. My three files pass (40 tests). The full-suite
failures on 2026-11-26 come from other agents' files in progress: `trips/audit.py` has a syntax
error at line 502, and `tests/fixtures/conditions_overpass_bansko.json` is missing.

## Known limits

- Travelland `_page` is not verified live (request budget). The no-new-ids stop makes it safe either way.
- The Olympic Riviera tag id on Travelland and its exact URL are unchecked.
- Loyalty and noise detection is word-based. A loyalty perk phrased without any of the words
  (e.g. "Welcome back: 10%") still passes as a campaign.
- Dedupe can merge two genuinely different offers with the same % and the same deadline, such as
  Sani's general 5 % and its Suite Collection 5 %. The fuller text is kept.
- Travelland and Olympic summer cards still have no date window, so `check_in` is the page default.
