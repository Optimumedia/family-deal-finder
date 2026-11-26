# tr_hotels: 2+2 hotel prices for Turkey (Antalya region, Bodrum, Kusadasi/Izmir), June 2027

**Result: not viable.** I found no robots-allowed source that publishes a **price for 2 adults + 2 small children** for Turkish beach hotels without a search request that robots.txt forbids, or without passing a bot wall. So I wrote no module, tests or fixtures. Everything below was checked on 26.11.2026 with the project user agent through `PoliteSession`, 6–8 s apart, using about 20 requests in total.

## What I checked

| Source | robots.txt / access | Prices in the static page? | Verdict |
|---|---|---|---|
| **etstur.com** | `/robots.txt` itself returns **403 with a Cloudflare challenge** | — | Blocked. Not used. |
| **tatilbudur.com** | robots.txt **403** | — | Blocked. |
| **setur.com.tr** | robots.txt **403** | — | Blocked. |
| **tatil.com** | robots.txt **520** (origin error) | — | Unreachable. |
| **odamax.com** | robots only disallows `/*?hotelCode`, but the home page answered **403 bot challenge** | — | Blocked. |
| **coraltatil.com** | robots allows hotel pages, but the home page is an **Incapsula bot wall** (`ROBOTS NOINDEX` interstitial) | — | Blocked. |
| **anextour.com** | `Disallow: *?*`, `Disallow: /*/$`, `Disallow: /*/*/$` for `*` | — | Effectively everything is disallowed. |
| **jollytur.com** | `Allow: /`, but `Disallow: /Hotel/Search`, `/Hotel/GetAvailableDates`, `/hotel/GetListPagePartials`, `/*?StartDate=*`, `/*&StartDate=*`, `/*?Rooms=*`, `/*&Rooms=*`, `/*?roomInfo=*`, `/hotel/detail*` | **No.** The list (`/belek-otelleri`) and hotel pages (`/tui-magic-life-masmavi`) render the price boxes empty. Prices load through `/hotel/GetAvailableDates` (disallowed) and date/room XHRs whose parameters (`StartDate`, `Rooms`) are disallowed. The static page has 2027 season dates and early-booking % windows only, with no amounts. | Not viable. Getting a 2+2 price would need the disallowed paths and parameters. |
| **tatilsepeti.com** | `Disallow: /*?ara` (its search/date/occupancy parameter) | **No.** List cards say "Fiyatlar için tarih seçiniz" (choose a date for prices), with `data-price="0"`. Hotel pages carry no amounts. | Not viable. A price needs `?ara=…`, which is disallowed. |
| **otelz.com** | `Allow: /`, `Disallow: /api/*`, `/search`, `*lang=*` | **No prices.** They come from `/api` (disallowed). Hotel pages do carry a **child policy** in `__NEXT_DATA__`, e.g. Concorde De Luxe Lara: `maxFreeAge 11`, `freeChildrenPerRoom 2`, `babyAge 2`, plus the text "2 for each room. free for child(ren) under the age of 5". | No prices. It could be a child-policy enrichment source (see below). |
| **filiptravel.rs** (Serbia) | `Disallow: /sr/hotel/turkey/`, `Crawl-delay: 30` | — | Turkey hotels are explicitly disallowed. |
| **kontiki.rs** | robots.txt **500** | — | Unreachable. |
| **odeon.rs**, **ponte-travel.com** | connection timeout / error | — | Unreachable. |
| **argus.rs** (Serbia) | `Disallow:` (everything allowed) | Its Turkey offer is **bus** packages (Kusadasi, Marmaris bus 2027) and Istanbul city breaks. | Wrong product: no hotel-only or 2+2 prices for our resorts. |
| **grandtours.rs** | everything allowed | It has one `/destinacija/turska/` page. I didn't pursue it, since Grand Tours is a Belgrade package seller. | Not pursued. |
| **bigblue.rs** (Serbia, SanTSG/TourVisio B2C) | `Allow:*`, only `Disallow: /*.asmx` and `/*.ashx` | **Yes, in an embedded JSON.** Location pages (`/sr/location/belek/`, `…/kemer/`, `…/side/`, `…/alanja/`, `…/bodrum/`, `…/kusadasi/`) and the rotator `/sr/hotel/rotator/antalijska-regija-gratis-smestaj-za-dvoje-dece/` embed about 20 offers each: room, board (e.g. "Ultra All Inclusive"), check-in, nights, price, old price, lat/lng, stars, and the badge **"BESPLATAN SMEŠTAJ ZA DVOJE DECE U HOTELU"** (free hotel stay for two children). | **Wrong occupancy and wrong airport.** Every embedded offer is `roomCriteria [{"adult":2}]` / two adult travellers, **with the flight from Belgrade** (JU charters, departure list = BEOGRAD only). A 2+2 price needs the search handler (`SearchCriteriaHandler.ashx`, disallowed). The price includes a BEG flight, so it says nothing reliable about a hotel price for an SKP family. |

I didn't check these, and expect no better result:
- **Hotel chains' own sites** (Rixos, Titanic, Delphin, Barut, Limak, Kaya, Gloria, Voyage, Maxx Royal). Their prices come from third-party booking engines (HotelRunner, Reseliva, Elektraweb, Sedna and similar) through JS/API calls after a date and guest search. That's the same pattern as the OTAs.
- Booking.com and Expedia/Hotels.com are excluded by the brief.

## Why "no" is the sound answer

All Turkish OTAs price only after a dated search with child ages. That search is either explicitly disallowed (Jollytur `StartDate`/`Rooms`, Tatilsepeti `?ara`, Otelz `/api`) or sits behind a bot wall (ETS, Tatilbudur, Setur, Odamax, Coral). The one allowed Balkan source with real embedded prices (Big Blue) prices 2 adults plus a Belgrade flight.

## Useful facts for the integrator (no module needed)

1. **Child policy is often public even when prices aren't.** Otelz hotel pages (`https://www.otelz.com/en/hotel/<slug>`, robots-allowed, server-rendered `__NEXT_DATA__` → `pageProps.facility`) give `maxFreeAge`, `babyAge`, `freeChildrenPerRoom` and `childAgesDescriptions`. A future enrichment step could fill `family` facts for Savana (`sv-…`) hotels by name match: "kids 0–6 free, 2 per room". I didn't build it because the brief asks for priced sources. If wanted, it's a small, separate job (one request per hotel).
2. **Big Blue's "free stay for two children" badge** (theme id 315) marks Antalya and Aegean hotels where the kids' hotel part is free for 2027 (Blue Friday / first minute). For Savana hotels with the same name, a 2-adult Savana price is then close to the real 2+2 hotel cost, with only the kids' flight seats extra. That's useful as a **manual check**. I would not auto-ingest it because the prices are Belgrade packages.
3. **Practical 2+2 route today:** ask Savana Travel (Skopje) for a 2+2 quote on the hotels the engine likes, or enter Fibula quotes by hand (`data/offers.toml`). Both already exist in the project.

## TOML block

None. No source is proposed.

## Live offer count

0 usable 2+2 offers. Big Blue's embedded data had about 20 offers per page, all 2-adult + BEG-flight packages, and these weren't ingested.
