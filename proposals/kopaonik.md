# Proposal: `kopaonik` source (Serbian ski resorts: Kopaonik, Stara Planina)

Module: `trips/sources/kopaonik.py` · Tests: `tests/test_kopaonik.py` (15 tests, no network) ·
Fixtures: `tests/fixtures/kopaonik_jat_*.html` (3), `tests/fixtures/kopaonik_sn_*.html` (6).

## What it reads
This module reads published winter 2026/27 **price lists**. It uses no booking engines and no APIs. Each page sets its own `parser`:

1. **`jat`: JAT Apartmani's own site** (jatapartmani.com, a hotel-direct source). `/en/price-list` is a
   server-rendered table with per-unit EUR rates per night for 6 periods (29.11.2026–04.04.2027). The
   table also shows a 7-night total that is 10% lower in the promo periods. The unit pages
   (`/en/accommodation/apartman-d|e|f`) say how many rooms each unit has. Only units for 4 or more guests are used:
   Studio D, Apartment E and Apartment F. Per run this costs 4 requests.
2. **`supernova`: Supernova Travel** (supernovatravel.rs, a Serbian agency). It has one price page per property, as Joomla
   tables in RSD. The parser reads the period header, the minimum-nights row and the unit rows. A note row under each block says what the numbers mean:
   per night (`PO NOĆI`), for the stated nights (`ZA NAVEDENI BROJ NOĆI` / `ZA 7 NOĆI`), or per person
   (`PO OSOBI`). Per-person blocks are skipped. A `CENA | Dnevna | Nedeljna` row sets the basis per column instead. Columns it can't read
   (merged periods, `/` cells) are skipped. Prices are converted at `rsd_per_eur`.

All prices are per unit, so units for 4 or more guests are stored as **occupancy "2+2"**. Board is "SC" for rentals and "HB"
for the Stara Planina hotel apartments (half board plus). `kind` is "apartment", or "hotel" for Stara Planina.
**`separate_bedroom`** follows these rules:
- `False` for studios: the page says "one room", or the unit is labelled STUDIO/STD.
- `True` only when the page says two rooms or a bedroom.
- Otherwise `None`. All the "APARTMAN/APT" units are `None`, and the notes say to ask. JAT Apartment E has a two-room
  variant (E2), and the note says so.

## robots.txt
- jatapartmani.com: `User-Agent: *` / `Allow: /` / `Disallow: /api/`. This module only reads `/en/price-list` and
  `/en/accommodation/...`.
- supernovatravel.rs: `Disallow: /administrator/`, `/api/`, `/components/`, `/modules/`, `/plugins/` … (Joomla
  system folders only). `/cenovnici/...` is allowed.
- infokop.net was checked but is **not used**. It disallows `/images/stories/smestaj/` and `/components/`, and its listing
  pages (e.g. `/apartmani-centar-kopaonik/apartman-duplex-2-spavace-sobe.html`) have no prices, only contact details.

## TOML block for config.toml
```toml
[sources.kopaonik]
# Kopaonik / Stara Planina winter price lists, read as tables (no booking engines, no APIs).
# parser "jat": JAT Apartmani's own price list (robots.txt: only /api/ disallowed).
# parser "supernova": Supernova Travel per-property price pages (robots.txt: Joomla system dirs only).
# Prices are per unit (RSD converted at rsd_per_eur), so 4+ guest units are stored as "2+2".
enabled = true
rsd_per_eur = 117.2

[[sources.kopaonik.pages]]
parser = "jat"
url = "https://jatapartmani.com/en/price-list"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/apartments-konaci-kopaonik-cenovnik.html"
name = "Apartmani Konaci"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/apartmani-kraljevi-cardaci-kopaonik-cenovnik.html"
name = "Apartmani Kraljevi Čardaci"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.30
lng = 20.84
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/apartmani-marija-lux-kopaonik-cenovnik.html"
name = "Apartmani Marija Lux"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/apartmani-srbijasume-kopaonik-cenovnik.html"
name = "Apartmani Šumarstvo (ex Srbijašume)"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/vila-zvoncica-kopaonik-cenovnik.html"
name = "Vila Zvončica"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 7

[[sources.kopaonik.pages]]
parser = "supernova"
url = "https://www.supernovatravel.rs/cenovnici/austrija-cenovnici/hotel-stara-planina-cenovnik.html"
name = "Hotel Stara Planina"
kind = "hotel"
season = "winter"
area = "Stara Planina, Serbia"
country = "RS"
lat = 43.373
lng = 22.606
nights = 7
```

## Live check (2026-11-25, 10 requests via PoliteSession)
The check found **20 units and 180 priced offers**:

| Source | Units | Offers |
|---|---|---|
| JAT | 3 | 18 |
| Konaci | 4 | 56 |
| Kraljevi Čardaci | 3 | 30 |
| Marija Lux | 3 | 27 |
| Šumarstvo | 1 | 7 |
| Zvončica | 4 | 32 |
| Stara Planina | 2 | 10 |

The cheapest offer is Konaci 2+1 STD at €147 for 3 nights (29 Nov). JAT Studio D costs €698.89 for 7 nights from 29 Nov (−10% promo).

## Known limits
- **Separate bedroom is mostly unknown.** Serbian "APARTMAN" usually means a separate bedroom, but no page says so,
  so these units are capped at "ask". Only studios are definite (a "no").
- **Cots:** the pages say nothing about cots. JAT's Serbian homepage FAQ mentions a free baby cot on request. The module does not read it (one cot ≠ two).
- JAT's **Lux tab** (Family Apartment, Superior Apartment, Family rooms) is drawn by JavaScript from a bundled chunk, so the module doesn't read it. Unit
  pages give only a "from" price for the cheapest period.
- Supernova offers use the stated minimum-stay nights. Some periods are 3-night stays (early December), and per-night
  columns are multiplied by `nights`. Weekday and weekend daily tables (Konaci tables 2–3) are ignored.
- Early-booking campaigns are not modelled as discounts. Supernova's dates mostly passed (15.11 / 30.11), and the JAT early-booking
  deal runs until 1 Dec 2026. `was_eur` exists only for JAT's 7-night −10% rows.
- RSD→EUR uses a fixed rate from config.
- Supernova's tables are hand-made and could change per page. A page that stops parsing just yields 0 offers (logged).
  Other Supernova pages were not checked: vila-kopaonik, vila-ras, jolly-kop, hotel Babin Zub and Midžor (Stara
  Planina). They are listed in `/sitemap.xml` and may parse; check one before adding it.
- Brezovica: no allowed source with prices was found. Supernova and JAT don't cover it.

## For the integrator
- Register the module: add `kopaonik` to the imports and to `AUTO_SOURCES` in `trips/run.py`.
- No new fields are needed. Hotel ids are `kop-jat-<letter>` / `kop-sn-<property>-<unit>`, with one "hotel" per unit
  type, because bedroom facts differ per unit.
- Optional: add `https://jatapartmani.com/en/offers` to `hotel_direct` pages, with hotel `kop-jat-d` or another unit, to catch its
  campaigns (Ski opening −15%, Early booking −10% by 1 Dec 2026).
