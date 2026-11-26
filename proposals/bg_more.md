# bg_more — Pochivka.bg apartment price tables (Bansko, Razlog, Dobrinishte, Borovets, Pamporovo)

## What it is
[Pochivka.bg](https://pochivka.bg) is Bulgaria's biggest accommodation directory. Owners,
agencies and aparthotels post their own listing with a **price table per unit type**:
`тип / места / брой от типа` and a rate for high/low summer, **high/low winter** and "other",
headed "*цената е обща за помещението на вечер" (the price is for the whole unit per night).
So a 4-place apartment gives a real whole-unit price for 2 adults + the twins: `occupancy = "2+2"`.
Bansko alone has 186 apartment listings; Razlog, Dobrinishte (t80), Borovets (t11) and
Pamporovo (t46) have their own lists. None of these units come from BulgariaSki, Micazu,
AtlantiS, Olympic or Travelland.

## robots.txt (https://pochivka.bg/robots.txt, checked 2026-11-26)
```
User-agent: *
Allow: /
Disallow: /ajax/
Disallow: /cgi-bin/
Disallow: /user3/*
Disallow: /execute/
Disallow: /redirects/
Disallow: /tester/
Disallow: /backend
```
We read only `/apartamenti-<resort>-t<N>[/<page>]` (list) and `/<name>-o<id>` (listing) pages,
both allowed. No search form, no AJAX, no booking, no query strings. No bot wall seen. Photos are
hotlinked from `static.pochivka.bg` (checked: served to a foreign Referer, no CORP header).

## Config block to add to config.toml
```toml
[sources.bg_more]
# pochivka.bg — owners' and aparthotels' own price tables (EUR per whole unit per night, by
# season). Cards for fewer than 4 places are skipped unopened; winter stays use the HIGH-winter
# rate (season dates aren't published). robots.txt allows list and listing pages.
enabled = true
list_pages = 2              # list pages per resort (10 cards each)
max_listings = 12           # listing pages opened per resort (~6-10 s each)

[[sources.bg_more.pages]]
url = "https://pochivka.bg/apartamenti-bansko-t6"
season = "winter"
area = "Bansko, Bulgaria"
country = "BG"
lat = 41.83
lng = 23.48
nights = 5
check_in = "2027-01-15"
list_pages = 3

[[sources.bg_more.pages]]
url = "https://pochivka.bg/apartamenti-razlog-t53"
season = "winter"
area = "Razlog, Bulgaria"
country = "BG"
lat = 41.886
lng = 23.465
nights = 5
check_in = "2027-01-15"
list_pages = 1

[[sources.bg_more.pages]]
url = "https://pochivka.bg/apartamenti-dobrinishte-t80"
season = "winter"
area = "Dobrinishte, Bulgaria"
country = "BG"
lat = 41.822
lng = 23.563
nights = 5
check_in = "2027-01-15"
list_pages = 1

[[sources.bg_more.pages]]
url = "https://pochivka.bg/apartamenti-borovets-t11"
season = "winter"
area = "Borovets, Bulgaria"
country = "BG"
lat = 42.266
lng = 23.606
nights = 5
check_in = "2027-01-15"

[[sources.bg_more.pages]]
url = "https://pochivka.bg/apartamenti-pamporovo-t46"
season = "winter"
area = "Pamporovo, Bulgaria"
country = "BG"
lat = 41.652
lng = 24.692
nights = 5
check_in = "2027-01-15"
list_pages = 1             # this list shows 20 cards per page
```
Page keys `list_pages` / `max_listings` override the source-level defaults.

## Live check (2026-11-26, check-in 2027-01-15, 5 nights)
8 list pages + 39 listing pages (≈50 requests, 6–8 s apart, no block): **30 priced "2+2" offers**,
one per listing. Bansko 10 (Bansko list pages 1–2), Pamporovo 10, Borovets 5, Razlog 3,
Dobrinishte 2. 5-night totals €275–€1,125 (median €575), all with a hotlinked photo.
15 of 30 have `separate_bedroom = True` from the owner's text; 5 are 4-place studios (kept, with the
bedroom left unknown, so the winter rule will still treat them as "ask"/doesn't fit). 9 listings
list a kids' corner. No listing text mentioned a cot.

## How offers are built
- Card filter: a card that shows a place count below adults + kids (4) is not opened. Cards
  without a count (several unit types) are opened.
- Per listing: the cheapest row with ≥ 4 places that is not a room (`стая`) or bed (an apartment
  row is preferred over a cheaper studio row); price =
  high-winter rate × nights (low-winter rate if no high-winter rate is given; no winter rate → no
  offer). Board `SC`, `occupancy "2+2"`, `kind "apartment"`, id `pv-<listing id>`.
- `family.separate_bedroom = True` **only** when the owner's text names a bedroom ("две спални",
  "2 спални", "една спалня", "спалнята", "обзаведена спалня", "спалня с …", or "двустаен" /
  "тристаен", the Bulgarian way of saying living room + 1 / 2 bedrooms) and the row isn't a studio. "двойна/френска спалня" (= a double bed) is removed first. Otherwise left unknown.
- `family.kids_corner` when the listing's own amenities list has "детски кът". Notes say whether
  a cot is mentioned ("кошара", "бебешко легло"); cots stay "ask" (never verified).
- Hotel-level map point from the listing's `place:location` meta (falls back to the page point).
- Old "лв" prices are converted at 1.95583 BGN/EUR.

## Known limits
- **Season dates aren't published**, so we price at the high-winter rate (worst case). Mid-January
  may really be "low winter" at some listings; the dashboard price can then be a bit high, never low.
- No discounts: the tables are list prices (`was_eur`/`discount_label` stay empty). Pochivka's
  separate package site oferti.pochivka.bg (robots allows it except `/out.php`, `*-o`, `*-ht`) has
  dated ski packages with "-X%" labels, but they are per person / per double room from hotels:
  a possible later module.
- Owner-entered tables can be stale (a few still in лв); we can't see availability.
- Some listings say "при повече от 3 нощувки цената се договаря" (longer stays negotiated): the
  price is a ceiling.
- The bedroom check reads Bulgarian free text; a listing whose text never names a bedroom is left
  unknown rather than guessed (the dashboard then asks).
- Ski kindergarten ages / lift-pass packages: not on Pochivka listings. Checked and not built:
  Balkan Holidays (UK operator: UK flights only, packages per person) and bulgariatravel.org
  (official tourism portal, no prices). BulgariaSki's kindergarten/ski-school pages are already
  that agency's domain (its `/booking.php` and `/search.php` stay off-limits).
- ~1 list page + up to 12 listing pages per resort: about 60–70 requests per full run (~8 min at
  6–10 s spacing).

## Needs the integrator
- Add `bg_more` to `AUTO_SOURCES` in `trips/run.py` (import from `.sources`).
- Add the TOML block above to `config.toml`.
- New optional family key `kids_corner` (bool) — ignore it if the scorer doesn't know it.
- Hotel names are in Bulgarian (Cyrillic) as the owners wrote them; dedupe with BulgariaSki's
  Latin names (e.g. "Флоримонт Хайтс" = Florimont Heights) won't match by name, only by map point.
