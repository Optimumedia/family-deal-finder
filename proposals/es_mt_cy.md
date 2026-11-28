# es_mt_cy: hotel-only prices near BCN, MLA and LCA (Itaka "Dojazd własny")

Agent `es_mt_cy`, 28.11.2026. 45 live requests (robots.txt included), all through `PoliteSession`.

**Verdict: partly viable.** One allowed source sells hotel-only stays in all four target areas with server-rendered prices. It is **not yet useful for 2+2 summer prices**, because I couldn't find the URL keys for the children's birth dates or for a date range. The parser is built and tested, and it reads the party from the page. Once someone supplies the right URLs it gives 2+2 summer offers with no code change. Until then I suggest `enabled = false`.

## Source: Itaka (itaka.pl)

Itaka is Poland's biggest tour operator. Its "Dojazd własny" (own transport) rates are a hotel-only "single tourist service": no flight, no transfer (`transferIncluded: false`, and the rate id carries the code `OTS`). Areas it covers:
- **Costa Daurada:** 20 own-transport rates in Salou, Cambrils and La Pineda (Best, H10, Ohtels, Golden, Ponient/PortAventura, La Siesta).
- **Maresme and southern Costa Brava:** 25 rates in Calella, Pineda, Santa Susanna, Malgrat and Lloret (GHT, Htop, Alegria, Aqua).
- **Malta:** 78 rates, among them db Seabank (Mellieħa), Paradise Bay, Ramla Bay, Pergola and Qawra Palace.
- **Cyprus:** 3 rates. Only Adams Beach is in Ayia Napa; the other two are in Paphos.

The page is `/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations=<region>`. Its `__NEXT_DATA__` holds the query the server ran and up to 15 rates. Each rate gives the hotel code, name, stars, pin, facility tags (`sandy-beach`, `by-the-beach`, `animations-for-kids`), the guest rating (1–6), a photo, the dates, room, meal, price per participant (in grosze) and the catalogue price. Each card links to the exact rate.

robots.txt (28.11.2026) allows these pages:

```
User-agent: *
Disallow: /reservation*
Disallow: /booking*
Disallow: /api*
Disallow: /_next/static/
Disallow: /zapytanie-ofertowe/*
Disallow: /rabat-za-newsletter
Disallow: /regulamin
```

## Live check

The plain URLs return Itaka's default search: **2 adults** on the most popular short stays (3–4 nights), mostly in April, May and October. Malta's default stays are in December and January. Offers found, out of 46 rates on the 4 pages:

| Months kept | Offers | Occupancy |
|---|---|---|
| 6–9 (default) | 1: Alegria El Mar, Santa Susanna, 24.09.2027, 3 nights, HB, 1,798 PLN ≈ €423 | 2+0 |
| 5–10 | 9 | 2+0 |
| any month | 42 | 2+0 |

None of them are 2+2.

## What I couldn't unlock (live requests ran out)

- **Children:** I tried `childs=2023-10-15,2023-10-15` and `adults[0]=2&childs[0]=…`. The server accepts both but ignores the children (its `rateParams.participantGroups[0].childrenBirthDates` stays `[]`). The card links use `adults[0]=2` and `id[0]=<rateId>`.
- **Dates:** URLs with `dateFrom`/`dateTo` (`YYYY-MM-DD`) returned a 5xx three times. The internal rewrite rules mention `dateFrom`/`dateTo`, so the date format or another key may be the problem.
- **Cheapest fix (no scraping):** on itaka.pl, choose the region, "Dojazd własny", 2 adults + 2 children (born 15.10.2023), early July and 7 nights. Then copy the address bar URL into `pages[].url`. The parser marks an offer "2+2" only when the page's own participants are 2 adults + 2 children, so a wrong URL can only give 2+0, never a false family price.

## TOML block (add to config.toml)

```toml
[sources.es_mt_cy]
# Itaka (itaka.pl) "Dojazd własny" = hotel only, no flight/transfer, near BCN / MLA / LCA.
# Off until the URLs carry the twins + July dates (see proposals/es_mt_cy.md); the plain URLs give
# 2-adult shoulder-season short stays only. 1 request per page.
enabled = false
pln_eur = 0.235             # PLN -> EUR (update now and then)
months = [6, 7, 8, 9]       # check-in months kept

[[sources.es_mt_cy.pages]]
url = "https://www.itaka.pl/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations=costa-dorada"
season = "summer"
area = "Costa Daurada (Salou, Cambrils, La Pineda)"
country = "ES"
lat = 41.07
lng = 1.13
max_km = 15                 # rates further than this from lat/lng are dropped
airport = "BCN"

[[sources.es_mt_cy.pages]]
url = "https://www.itaka.pl/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations=costa-brava"
season = "summer"
area = "Maresme / southern Costa Brava (Calella, Santa Susanna, Malgrat)"
country = "ES"
lat = 41.635
lng = 2.72
max_km = 20                 # keeps Calella..Lloret, drops Sant Feliu / Roses
airport = "BCN"

[[sources.es_mt_cy.pages]]
url = "https://www.itaka.pl/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations=malta"
season = "summer"
area = "Malta (Mellieħa, Qawra, St Julian's)"
country = "MT"
lat = 35.93
lng = 14.42
max_km = 30
airport = "MLA"

[[sources.es_mt_cy.pages]]
url = "https://www.itaka.pl/wyniki-wyszukiwania/wakacje/?ownTransport=true&destinations=cypr"
season = "summer"
area = "Ayia Napa / Protaras / Larnaca bay"
country = "CY"
lat = 34.98
lng = 33.85
max_km = 30                 # drops Paphos
airport = "LCA"
```

## Known limits

- **Prices are in PLN.** They're converted with a fixed `pln_eur`, and the room text keeps the PLN figure.
- **15 rates per page.** Paging (`skip`/`take`) is untested.
- **Each rate is a single stay** of 3–4 nights by default. The `nights` value comes from the page.
- **Ratings use Itaka's 1–6 scale** (`scale: 6.0`). The rating rule has no threshold for that scale, so the integrator must decide how to treat it.
- **Facility tags are thin.** `kids_animation` is stored for `animations-for-kids`. `beach_m` is usually null.
- **A cruise and Hotelbeds rates appear on the same pages.** Rates that aren't holidays, have no pin, or lack the `OTS` code are skipped.

## Checked and not viable

- **Best Hotels (besthotels.es):** robots.txt allows everything, but pages only show undated "from €50" teasers. The booking engine is Paraty, which is JS-only.
- **H10, Meliá, Ohtels:** booking engines only.
- **Hello Holidays (helloholidays.ro):** hotel-only seller, but returned 403. I stopped there.
- **wakacje.pl:** has Itaka's own-transport offers too, but offer pages are 2 adults only. A party needs a query string, and robots.txt disallows `/oferty/*?*` and `/*,*/`.
- **travelplanet.pl:** robots.txt disallows the date and filter parameters.
- **Relaxo.bg:** no Cyprus. Spain and Malta are sold only as flight packages from Sofia or Varna.
- **Web searches** found no 2027 price list for any Cyprus, Malta or Spain family hotel, and no Cypriot or Maltese operator with server-rendered hotel-only prices.

## For the integrator

- **Wiring:** add `es_mt_cy` to `AUTO_SOURCES` in `trips/run.py`. No new fields are needed.
- **Hotel ids** are `itk-<code>`, the source is `"Itaka (hotel only)"`, and `direct_flight_skp = True` is set (as in `flight_hotels`).
