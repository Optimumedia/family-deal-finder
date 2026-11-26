# al_me_coast — Albanian sandy coast (Golem, Lalzi Bay, Shëngjin, Velipojë) via Vlero.com

Agent: `al_me_coast` · checked 2026-11-26

## What the source is
**Vlero.com** is an Albanian booking portal. Hotels and apartment owners list their own rooms, and the guest pays the property in cash or by bank transfer. It is not a Booking.com reseller. Each beach area has a GET keyword page with up to 40 room cards. A card shows:
- property type and stars, plus the zone (Golem, Shkembi Kavajes, Gjiri i Lalzit, Shengjin, Velipoje)
- nightly price in EUR or Lek
- beds and **capacity (adults + children)**
- **distance to the beach in metres**, and size in m²
- what's included (breakfast, own kitchen, pool)
- a hotlinkable photo (hotlinking checked: 200, no hotlink block)

Property names are not shown; Vlero keeps them for the booking. Hotels are therefore named "Apartment in Golem (Vlero #1354)", with id `vl-<property no.>`.

The module is `trips/sources/al_me_coast.py`. Tests are in `tests/test_al_me_coast.py` (10 tests, all pass, no network). Fixtures are `tests/fixtures/al_me_coast_{golem,shengjin,velipoje,lalzi}.html`.

## robots.txt (https://www.vlero.com/robots.txt, 2026-11-26)
```
User-agent: *
Disallow: /*&language=*
Disallow: /*leadrent*
Disallow: /*ontop.php*
Disallow: /*count_view.php*
```
The keyword pages we read are allowed, and PoliteSession's robots check passes. We never call the search form (a POST), `ontop.php`, or the `&language=` links.

## TOML block for config.toml
Drive times are estimates for Skopje → Blace → Prizren → Morinë/Vërmicë → Kukës → A1 motorway (Milot), with 2 borders (MK→XK→AL).
```toml
[sources.al_me_coast]
# vlero.com — Albanian portal, owners/hotels list their own rooms (pay the property).
# robots.txt allows these pages. One request per area per run. Rooms that don't sleep 2+2 are dropped.
enabled = true
# all_per_eur = 100        # set to also keep rooms priced in Lek (skipped by default)

[[sources.al_me_coast.pages]]
# ~330 km, ~4h15 + 2 borders (A1 to Milot, then Thumanë–Durrës)
url = "https://www.vlero.com/dhoma-plazhi-ne-golem/l-al-c-26.html"
season = "summer"
area = "Durrës / Golem, Albania"
country = "AL"
lat = 41.245
lng = 19.523
nights = 7
check_in = "2027-06-20"
zones = ["Golem", "Shkembi Kavajes"]

[[sources.al_me_coast.pages]]
# ~300 km, ~3h55 + 2 borders (exit A1 at Fushë-Krujë/Hamallaj)
url = "https://www.vlero.com/dhoma-plazhi-gjiri-lalzit/l-al-c-26.html"
season = "summer"
area = "Lalzi Bay, Albania"
country = "AL"
lat = 41.43
lng = 19.47
nights = 7
check_in = "2027-06-20"
zones = ["Gjiri i Lalzit"]

[[sources.al_me_coast.pages]]
# ~280 km, ~3h40 + 2 borders (A1 to Milot, then Lezhë)
url = "https://www.vlero.com/banesa-me-qera-ne-shengjin/l-al-c-26.html"
season = "summer"
area = "Shëngjin, Albania"
country = "AL"
lat = 41.807
lng = 19.593
nights = 7
check_in = "2027-06-20"
zones = ["Shengjin"]

[[sources.al_me_coast.pages]]
# ~300 km, ~4h05 + 2 borders (A1 to Milot, Lezhë, then Velipojë road)
url = "https://www.vlero.com/hotele-ne-velipoje-after-plazhit/l-al-c-26.html"
season = "summer"
area = "Velipojë, Albania"
country = "AL"
lat = 41.86
lng = 19.42
nights = 7
check_in = "2027-06-20"
zones = ["Velipoje"]
```

## Live check (2026-11-26, 4 page fetches + 1 room page, ≥6 s apart)
**45 priced 2+2 offers** from 45 properties:

| Area | Offers | 7-night price | Within 150 m of the beach |
|---|---|---|---|
| Golem / Shkëmbi i Kavajës | 15 | €231–616 | 11 |
| Shëngjin | 11 | €231–693 | 8 |
| Velipojë | 13 | €231–1,750 | 8 |
| Lalzi Bay | 6 | €385–924 | 3 |

Boards: self-catering (own kitchen) 20, room only 20, breakfast 5, half board 0.

Occupancy is an honest "2+2". The price is per room per night, and a room is kept only if its stated capacity is at least 2 adults and at least 4 people in total.

## Known limits
- **No half board.** Vlero sells rooms, not board. Under `[summer] need_board = ["HB","FB","AI"]` the engine will treat every offer as failing the board rule. These offers are real 2+2 self-catering and B&B prices with a known beach distance. That is useful as a comparison, or if the family relaxes the board rule for apartments.
- **Prices are not tied to dates.** The card shows the room's listed nightly price, which is the top of its range: the room page's JSON-LD had low 150 / high 165, and the card showed 165. Vlero's calendar only opens to 2027-05-25, so summer 2027 dates can't be quoted yet. Offers are stored as price × 7 at the page's default check-in, with "dates on request".
- **Anonymous properties.** There's no hotel name until booking, so cross-source dedupe against Olympic or Fibula hotels won't match.
- **Mixed pages.** Keyword pages mix in a few featured rooms from other towns. `zones` filters them out.
- **Lek prices are skipped** unless `all_per_eur` is set. Watch out: the schema.org meta says EUR even when the visible price is "14,300 Leke". The parser reads the visible word, and a test covers this.
- **Only the first page per area is read** (up to 40 cards). Pagination links are session-style `?&page=2` on a generic URL, so we don't follow them.

## Checked and not viable (Montenegro / agencies)
- **Ulcinj / Ada Bojana:** Olympic and Travelland already cover these.
  - montenegro.com shows only a "from €25" price. Its rates and calendar come from `/api/`, which robots.txt disallows.
  - bookaweb.com had only 2 Velika Plaža listings.
  - turizzam.com is allowed by robots, but its owner prices are free text, often without a year.
  - sobe-smestaj.com and halooglasi.com carry Content-Signal `ai-train=no` with bot blocks. Left alone.
- **Kosovar and Albanian agencies:**
  - eurokoha.com is a parked domain.
  - Sharr Travel and Arditi or Auloni Tours sell bus tickets, not hotel packages.
  - No Prishtina or Tirana agency site with a public Golem package price list turned up.
- **Serbian agencies:**
  - filiptravel.rs returns 403.
  - argus.rs and grandtours.rs have no Albania program.
  - flyflytravel.com redirects to an unrelated site.
- **Hotel own sites:** rafaeloresort.com (Shëngjin) shows no prices, only a booking engine.

## For the integrator
1. **Campaign worth adding to `hotel_direct`:** Flower Hotels & Resorts, Golem. Page: `https://www.hotel-flower.com/packages/early-booking-all-inclusive-2027`.
   - "15% off All Inclusive", stays 15 May–30 Sep 2027, book by **30 Nov 2026**, minimum 2 nights.
   - The page also states: children 0–4.5 free, 5–11.5 at −50%.
   - robots.txt has only a Sitemap line, so everything is allowed.
2. **Border buffer:** the Kukës route crosses **two** borders (MK→XK, XK→AL). With `border_buffer_minutes = 30` applied once, the router may underestimate. Consider a per-page `borders = 2` field or a larger buffer for AL.
3. **Board rule:** optionally a switch that lets `SC` apartments with a kitchen pass `need_board` in summer. Otherwise this source mostly feeds comparison and history.
4. **Sand fact:** Golem, Lalzi, Shëngjin and Velipojë are all sandy. The cards don't say so, so `sand_beach` is left unknown, and `unknown_cap` will cap the ratings. An area-level `sand_beach = true` page setting would need a small engine change.
