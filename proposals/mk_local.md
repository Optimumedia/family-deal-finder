# Proposal: `mk_local` source (Kajak.mk, destinations in North Macedonia)

Module: `trips/sources/mk_local.py` · Tests: `tests/test_mk_local.py` (24 tests, no network) ·
Fixtures: `tests/fixtures/mk_local_list_*.html` (4 region lists, one English), `tests/fixtures/mk_local_*.html` (10 listings).

## What the source is
**Kajak.mk** is a Macedonian accommodation portal. Hosts list their own apartments, villas, cabins and
small hotels. You send a request and the host replies with a price. It is not a Booking/Airbnb reseller,
and there is no booking engine or API. It covers every place in the brief:
Mavrovo (≈140 listings), Popova Šapka (≈60), Kruševo (≈60), Pelister (inside the Bitola region:
Nižepole, Trnovo, Magarevo), Ohrid (≈400), Struga (≈80) and Dojran (≈40).

The module reads two kinds of page:
- the region list (`/smestuvanja/<id>-<region>?Page=N`): cards with a place label, a title, a "Цена од"
  from-price per night in MKD, and a "МОМЕТАЛНО НЕ РАБОТАТ" (closed for now) badge;
- each listing (`/smestuvanje/<slug>`), in Macedonian or English, which gives:
  - whole-unit rental ("СЕ ИЗНАЈМУВА ЦЕЛО СМЕСТУВАЊЕ" / "ENTIRE ACCOMMODATION IS RENTED");
  - max guests;
  - the "Вклучено во цена" price lines;
  - bedrooms, studio, minimum stay and breakfast.

**Pricing rules.** Nothing is guessed.
1. A "Цена за 4 лица: 2.200 ден" line (a price for 4 or more people) gives that price as **2+2**.
2. A whole-unit rental for 4 or more guests, with no per-person or for-two wording, gives the from-price as **2+2**.
3. A per-person price gives ×2 adults as **2+0**. A for-two price ("за двајца", "Цена за 2 лица"), or anything else, gives the from-price as **2+0**.

Listings for fewer than 4 guests are skipped. Whole villas for more than `max_capacity` (8) guests are skipped too, since those are party houses.
`separate_bedroom` is set as follows:
- **True** when the page says "спална соба / спални соби / bedroom";
- **False** for studios;
- otherwise **None**, and the note says to ask.

Board is SC when "Храна" (food) is listed as not included, BB when "Појадок: вклучен" (breakfast included), and HB for half board.

## robots.txt (kajak.mk, checked 2026-11-26)
```
User-agent: *
Allow: /
Disallow: /admin  /agency  /korisnik  /vlez  /izlez  /registracija  /lozinka/  /zacuvani
Disallow: /rezervacija/  /naracka/  /lang/  /search
Disallow: /ipn/  /api/  /ajax/  /analytics  /media/  /comment/  /meta/
```
The module uses only `/smestuvanja/...` and `/smestuvanje/...`. It never uses the reservation form, `/search`, `/lang/` or `/ajax/`.
Images are hotlinked from `cdn.kajak.mk` (the og:image or the card image).

## TOML block for config.toml
```toml
[sources.mk_local]
# Kajak.mk — Macedonian accommodation portal (hosts' own listings, requests go to the host; not a
# Booking/Airbnb reseller). robots.txt allows /smestuvanja/ (region lists) and /smestuvanje/ (listings);
# /search, /api/, /ajax/, /rezervacija/ are disallowed and never used.
# Prices are per-night "from" prices in MKD; see trips/sources/mk_local.py for when a price counts as 2+2.
enabled = true
mkd_per_eur = 61.5
max_list_pages = 2          # region list pages read (≈20 cards each)
max_listings = 15           # listing pages read per region (one request each)
max_capacity = 8            # skip whole villas for bigger groups

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/b588801e-mavrovski-region"
location = "Mavrovo"
season = "winter"
area = "Mavrovo (Zare Lazarevski ski centre), North Macedonia"
country = "MK"
lat = 41.66
lng = 20.74
nights = 5
check_in = "2027-01-16"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/3a80c2dd-popova-shapka-region"
location = "Popova Shapka"
season = "winter"
area = "Popova Šapka, North Macedonia"
country = "MK"
lat = 42.016
lng = 20.88
nights = 5
check_in = "2027-01-16"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/1de7eefe-krushevski-region"
location = "Krushevo"
season = "winter"
area = "Kruševo, North Macedonia"
country = "MK"
lat = 41.37
lng = 21.25
nights = 5
check_in = "2027-01-16"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/a16107ff-bitolski-region"
location = "Bitola"
title_match = "Пелистер|Нижеполе|Трново|Магарево|Pelister"
max_list_pages = 4
season = "winter"
area = "Pelister, North Macedonia"
country = "MK"
lat = 41.03
lng = 21.25
nights = 5
check_in = "2027-01-16"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/84bcd5d1-ohridski-region"
location = "Ohrid"
season = "summer"
area = "Ohrid, North Macedonia"
country = "MK"
lat = 41.117
lng = 20.80
nights = 7
check_in = "2027-07-03"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/3a6fa0bd-strushki-region"
location = "Struga"
season = "summer"
area = "Struga, North Macedonia"
country = "MK"
lat = 41.178
lng = 20.678
nights = 7
check_in = "2027-07-03"

[[sources.mk_local.pages]]
url = "https://kajak.mk/smestuvanja/586fa8f0-dojranski-region"
location = "Dojran"
season = "summer"
area = "Dojran, North Macedonia"
country = "MK"
lat = 41.18
lng = 22.72
nights = 7
check_in = "2027-07-03"
```
`location` must equal the card's place label. Every list also shows promoted cards from other regions,
such as a Gevgelija villa, and these are dropped.

**Cost per run** with these settings: about 2 list requests and 15 listing requests per region, so about 115
requests. At the 6–10 s delay that is about 15 min. Lower `max_listings` to make it cheaper.

## Live check
Checked 2026-11-26 with a capped run: 1 list page and 6 listings per region, 49 requests at a 6–8 s delay.
It found **36 priced offers from 36 listings, 13 of them priced at 2+2**:

| Region | Offers | 2+2 |
|---|---|---|
| Mavrovo | 6 | 3 |
| Popova Šapka | 3 | 2 |
| Kruševo | 6 | 2 |
| Pelister | 5 | 3 |
| Ohrid | 5 | 1 |
| Struga | 6 | 1 |
| Dojran | 5 | 1 |

Some examples:
- a lake-view apartment in Mavrovo for 4: €191 for 5 nights, SC;
- a two-bedroom apartment by the Mavrovo ski lift: €500 for 5 nights;
- the Dojran apartment, priced "for 4 people": €250 for 7 nights;
- the central Ohrid apartment: €280 for 7 nights.

The full settings (2 list pages and 15 listings per region) should give roughly 70–90 offers.

**Language:** the site serves its English edition when the request says `Accept-Language: mk,en`.
The project's default header does say that, and the English edition lists only the translated
subset of listings (Dojran: 18 of about 40). So `fetch()` sets `Accept-Language: mk` on its own session, which run.py creates per source.
English pages still parse (tests cover both editions).

## Known limits
- **All prices are "from" prices with dates on request.** The site has no calendar prices we may read: the
  availability form posts to `/rezervacija/`, which is disallowed. `check_in` is the configured date, and the
  real price in season or over the holidays can be higher. When a listing gives a range ("6.159–12.318 денари"), the note shows it.
- No discounts are published, so `was_eur`, `discount_label` and `valid_until` are always None.
- A list is ordered by the site, not by price. With `max_listings = 15`, only the first ≈15 matching cards
  of a region are read. Ohrid has about 19 list pages, so the deeper ones are not reached.
- Facts such as cots, a kids' club or the beach type are not stated in a structured way, so none are set beyond `separate_bedroom`.
- There are no real hotel family rooms (2+2 hotel prices) here, apart from the odd small hotel that lists "Цена за 4 лица".
  Hotels' own sites near Ohrid and Mavrovo were not built into this module. The ones I saw publish
  campaigns rather than price tables, or run booking engines.

## For the integrator
- Register `mk_local` in `trips/run.py` (`AUTO_SOURCES`) and paste the TOML block above.
- No new fields are needed. `family.separate_bedroom` is the same key `kopaonik` uses.
- Hotel ids are prefixed `kj-` and taken from the listing slug.
- `border` is False and `country` is "MK" for every page. The drive from Skopje is about 1.5 h (Mavrovo, Popova Šapka),
  2–2.5 h (Kruševo, Ohrid, Struga, Pelister) and 2 h (Dojran).
