# rentals — villas/apartments (Clickstay) + more hotel offers pages

## A. Clickstay (clickstay.com) — new source `trips/sources/rentals.py`

**What it is.** A UK "book direct from owners and agents" holiday-rental site (part of the Oliver's
Travels group). Region pages are server-rendered: each card gives name, property type
("2 bedroom villa", "2 bedroom duplex apartment"), sleeps, a hotlinkable photo (Clickstay's
CloudFront CDN) and "From £… per week" (lowest weekly rate). The same data sits in a JS state
object on the page (`{title:…,url:"/p/439052",…,propertyType:…,sleeps:4,…,price:1522}`), which is
what the parser reads.

**robots.txt** (fetched 2026-11-25), complete:

```
User-Agent: *

Sitemap: https://www.clickstay.com/sitemap-index.xml
```

No Disallow lines, so every path is allowed. We only read three region pages per run. Listing pages
(`/p/<id>`) carry no server-rendered price, so the module doesn't fetch them.

**Offers.** kind `villa` / `apartment`, board `SC`, occupancy `2+2` (only places that sleep 4 or more
are kept: the whole place is rented, so the price covers the family). price = weekly "from" GBP ×
`gbp_to_eur` × nights/7. If the owner's summary gives a beach distance in metres, that number is
stored as `family.beach_m` (the text itself isn't kept). `separate_bedroom` = 2+ bedrooms in summer,
1+ in winter. Ids are `cs-<clickstay id>`.

**Live check (2026-11-25): 18 priced offers** (16 on the Chalkidiki page, 1 Nikiti, 1 Pefkohori),
from €950 (2-bed house, Nea Propontida, about 300 m to the beach) to €9,523 a week.

**TOML block for config.toml:**

```toml
# --------------------------------------------------- villa/apartment rentals --
[sources.rentals]
# clickstay.com — robots.txt is "User-Agent: *" with no Disallow. Whole villas/apartments from owners
# and agents; "From £… per week" = lowest weekly rate (GBP, converted). Self-catering.
enabled = true
gbp_to_eur = 1.17

[[sources.rentals.pages]]
url = "https://www.clickstay.com/greece/chalkidiki"
season = "summer"
area = "Halkidiki (villa)"
country = "GR"
lat = 40.10
lng = 23.60
nights = 7
check_in = "2027-06-20"

[[sources.rentals.pages]]
url = "https://www.clickstay.com/greece/nikiti"
season = "summer"
area = "Nikiti, Sithonia (rental)"
country = "GR"
lat = 40.22
lng = 23.67
nights = 7
check_in = "2027-06-20"

[[sources.rentals.pages]]
url = "https://www.clickstay.com/greece/pefkohori"
season = "summer"
area = "Pefkohori, Kassandra (rental)"
country = "GR"
lat = 39.99
lng = 23.62
nights = 7
check_in = "2027-06-20"
```

**Known limits**
- Prices are "from" weekly rates with no dates and no discount or "was" price, so there's never a discount label.
- The Chalkidiki page shows at most 16 cards: "best" plus "private pool". `/greece/kassandra` and
  `/greece/sithonia` redirect to the same page, and "View all" is a client-side search, so we don't use it.
- **No Thassos, Olympic Riviera or Bansko coverage.** `/greece/thassos` returns an empty page,
  `/greece/pieria` is a client-side search page with no cards, and `/bulgaria/bansko` redirects to
  the Bulgaria page, which only has Black Sea and countryside villas (all over 5 h away).
- About 8 of the 16 Chalkidiki villas (Bernice, Bernie, Kitos, Griffin, Hekate, Gorgon, Kalypso and the
  two Vourvourou villas) are Oliver's Travels stock that also appears on oliverstravels.com.
  Their ids differ (`cs-` vs `ot-`), so the same villa can show twice.
- Most villas are luxury private-pool villas costing €3–9.5k a week. Only about 6 cost under €2k a week.

**Candidates checked and rejected**
- Interhome (interhome.com): `/greece/` and `/bulgaria/` both returned 403 (bot wall), so I stopped.
- Holidu, cozycozy: these are metasearch sites that resell Booking.com/Airbnb/Vrbo stock, which is
  excluded at the source, so I didn't use them.
- Belvilla: robots.txt disallows `/property/*`, and its region pages are client-rendered.
- Novasol, e-domizil: e-domizil uses Interhome's robots.txt (disallows `/search/`, `/details/`).
  Neither has Halkidiki or Bansko region pages worth the risk.
- Bansko agencies: web searches (English and Bulgarian) turned up only Airbnb/Booking/Vrbo/Expedia
  listings and no local agency site with server-rendered prices. Micazu remains the Bansko
  owner-rental source.

**Needs the integrator**
- Add `rentals` to `AUTO_SOURCES` in `trips/run.py` (and the import), and add the TOML block above.
- Optional: dedupe `cs-` vs `ot-` villas by name if both show up.

---

## B. More hotels' own offers pages for `hotel_direct`

**Method.** For about 45 hotels from `docs/data.json`, I guessed each hotel's own domain. I fetched its homepage with
`PoliteSession` (which checks robots.txt and stops on 403 or a challenge), followed on-site links that
contain offer/promo/special/deal/оферт/промо, and ran `trips.sources.hotel_direct.campaigns()` on the saved copy
(today = 2026-11-25). Every URL below was fetched without a robots block or bot wall. I skipped:
- sites that blocked us: ammoa.gr (robots.txt disallows `/`) and rilaborovets.com (403)
- guessed domains that belong to someone else: ammonzeus.gr, simantro.com, euphoriaclub.com, hotelputnik.rs
- sites whose TLS certificate didn't match: elinotel.gr, mediterranean-resort.gr, olympianbay.com

| hotel id | hotel | page | campaigns on 2026-11-25 |
|---|---|---|---|
| ol-102809 | Portes Beach (Kassandra) | portesbeach.com/special-offers | **2**: "save up to 25%", 5% returning guests |
| ol-103035, ol-114144 | Secret Paradise (Kassandra; two ids) | secretparadise.gr/special-offers-halkidiki-hotel | **2**: Black Friday / early 2027 up to 30% |
| ol-102886 | Aegean Melathron (Kassandra) | aegeanmelathron.gr/en-gb/offers-kassandra-halkidiki/melathron-members-club | **1**: 10% extra discount. The main offers page gave 0. |
| lagomandra-beach | Lagomandra Beach (Sithonia) | lagomandra.gr/ (home page) | **1**: Early Booking 2027 (30%). Check it's the same property: the site says "Lagomandra Beach Hotels & Spa". |
| ol-114032 | Kassandra Palace | kassandrapalace.com/bg/промоции-намаления.html | 0 (Bulgarian text; % not in the text) |
| ol-102951, ol-102957, ol-102955 | Acrotel Elea Beach / Lily Ann Village / Lily Ann Boutique | acrotel.gr/promotions-offers/ | 0 (offers likely loaded by JS) |
| ol-102912 | Anthemus Sea (Sithonia) | anthemussea.gr/special-offers/ | 0 |
| ol-102768 | Chrousso Village (Kassandra) | chroussovillage.com/sr/promocije-popusti.html | 0 |
| royal-park-bansko | Royal Park Bansko | royalparkbansko.com/deals-discounts.html | **2**: EB −10% for 03.01–06.03.2027. The home page also shows 45/50/20% items. |
| ol-115324 | Regnum Bansko | regnumbansko.com/special-offers | **1**: 15% early booking by 30.11.2026 |
| ol-115318 | Lucky Bansko | luckybansko.com/offers-lucky-bansko-packages-c92/ | **1**: package −10% until 20.12 |
| ol-1825 | Pirin Bansko | hotelpirin.com/en/offers | **6**: winter EB −10% until 30.11. Two of them are noise ("30% deposit"). |
| ol-115328, ol-115316, ol-115343, tl-111208, tl-111117 | MPM Sport / Guinness (Bansko), MPM Musala (Borovets; two ids), MPM Merryan (Pamporovo) | mpmhotels.bg/offers/ | **2**: Black Friday up to 50% (summer 2027), up to 25% (winter 26/27). This is a group page, so the campaign shows on all five. |
| tl-111164 | Grand Royale Bansko | grandroyale.bg/en/special-offers/ | 0 |
| ol-115314 | Green Life Bansko | greenlifebansko.bg/bg/bansko/oferti | 0 |
| ol-115335 | Festa Winter Palace (Borovets) | festahotels.com/bg/oferti | 0 |
| tl-111143 | Perelik (Pamporovo) | perelikhotel.com/category/оферти/ | 0 |
| ol-1116 | Grand Hotel & Spa (Kopaonik) | grandkopaonik.com/ (home page) | **2**: 10% until 31.1.2027, 50% off spa treatments |

**11 of 25 entries (8 sites) yield campaigns today.** The 0-yield pages are allowed and real offers pages, so
they're worth watching. Two quirks: `campaigns()` only counts a "%" near an English or Serbian keyword,
and it misses Bulgarian/Greek wording (отстъпка, намаление, έκπτωση) and JS-rendered offer lists.

**TOML block** (append under `[sources.hotel_direct]` in config.toml):

```toml
# summer — Halkidiki
[[sources.hotel_direct.pages]]
hotel = "ol-102809"
url = "https://www.portesbeach.com/special-offers"

[[sources.hotel_direct.pages]]
hotel = "ol-103035"
url = "https://www.secretparadise.gr/special-offers-halkidiki-hotel"

[[sources.hotel_direct.pages]]
hotel = "ol-114144"
url = "https://www.secretparadise.gr/special-offers-halkidiki-hotel"

[[sources.hotel_direct.pages]]
hotel = "ol-102886"
url = "https://www.aegeanmelathron.gr/en-gb/offers-kassandra-halkidiki/melathron-members-club"

[[sources.hotel_direct.pages]]
hotel = "lagomandra-beach"
url = "https://www.lagomandra.gr/"

[[sources.hotel_direct.pages]]
hotel = "ol-114032"
url = "https://www.kassandrapalace.com/bg/промоции-намаления.html"

[[sources.hotel_direct.pages]]
hotel = "ol-102951"
url = "https://www.acrotel.gr/promotions-offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-102957"
url = "https://www.acrotel.gr/promotions-offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-102955"
url = "https://www.acrotel.gr/promotions-offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-102912"
url = "https://anthemussea.gr/special-offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-102768"
url = "https://www.chroussovillage.com/sr/promocije-popusti.html"

# winter — Bansko, Borovets, Pamporovo, Kopaonik
[[sources.hotel_direct.pages]]
hotel = "royal-park-bansko"
url = "https://www.royalparkbansko.com/deals-discounts.html"

[[sources.hotel_direct.pages]]
hotel = "ol-115324"
url = "https://www.regnumbansko.com/special-offers"

[[sources.hotel_direct.pages]]
hotel = "ol-115318"
url = "https://luckybansko.com/offers-lucky-bansko-packages-c92/"

[[sources.hotel_direct.pages]]
hotel = "ol-1825"
url = "https://hotelpirin.com/en/offers"

[[sources.hotel_direct.pages]]
hotel = "ol-115328"
url = "https://mpmhotels.bg/offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-115316"
url = "https://mpmhotels.bg/offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-115343"
url = "https://mpmhotels.bg/offers/"

[[sources.hotel_direct.pages]]
hotel = "tl-111208"
url = "https://mpmhotels.bg/offers/"

[[sources.hotel_direct.pages]]
hotel = "tl-111117"
url = "https://mpmhotels.bg/offers/"

[[sources.hotel_direct.pages]]
hotel = "tl-111164"
url = "https://grandroyale.bg/en/special-offers/"

[[sources.hotel_direct.pages]]
hotel = "ol-115314"
url = "https://www.greenlifebansko.bg/bg/bansko/oferti"

[[sources.hotel_direct.pages]]
hotel = "ol-115335"
url = "https://www.festahotels.com/bg/oferti"

[[sources.hotel_direct.pages]]
hotel = "tl-111143"
url = "https://www.perelikhotel.com/category/оферти/"

[[sources.hotel_direct.pages]]
hotel = "ol-1116"
url = "https://www.grandkopaonik.com/"
```

**Needs the integrator (part B)**
- `hotel_direct.fetch` fetches pages one by one, so a page shared by several hotels (mpmhotels.bg ×5, acrotel.gr ×3,
  secretparadise.gr ×2) is fetched once per hotel. Caching by URL within a run would save 7 requests.
- The `ol-`/`tl-` ids come from agency scrapes. If an agency renumbers a hotel, its entry here stops matching.
- Optional: add Bulgarian/Greek keywords (`отстъпка|намаление|ранни записвания|έκπτωση|προσφορά`) to `hotel_direct.KEYWORDS`.
  Also add `deposit` to `_NOISE` (Pirin's "30% deposit" is read as a campaign).
