# Proposal: `winter_more` source (Halo Oglasi owner ads: Kopaonik, Stara Planina)

Module: `trips/sources/winter_more.py` · Tests: `tests/test_winter_more.py` (22 tests, no network) ·
Fixtures: `tests/fixtures/winter_more_list_*.html` (2 resort lists), `tests/fixtures/winter_more_*.html` (6 ads).
Contact-reveal tokens in the saved ads were replaced with `REDACTED`. The pages hold no phone numbers or e-mails, because those sit behind the reveal button.

## What the source is
**Halo Oglasi** (halooglasi.com) is Serbia's largest classifieds site. Its **Odmor › Planine** section holds owners' own
holiday-rental ads, with no booking engine and no reseller: the guest calls the owner. It is not on the excluded list.
Each ad page carries a JSON object (`QuidditaEnvironment.CurrentClassified`) with the owner's **structured fields**:
- `cena_noc_d`: EUR per night, for the whole unit;
- `kapacitet_smestaja_s`: number of guests;
- `tip_smestaja_s`: Apartman / Studio / Kuća za odmor / Hotel;
- `last_minute_b` and `po_dogovoru_b` (price on request);
- the map pin, the photo list and the free text.

This covers what the gap asked for. 7 of the 14 priced ads state a separate bedroom: "odvojena spavaća soba",
"jednoiposoban", "1 spavaću sobu". Cots are found too ("Moguć krevetac na zahtev").
Existing sources (JAT, Supernova) mostly leave Kopaonik's bedroom as unknown.

**Pricing rules.** Nothing is guessed.
- "Dogovor" cards (price on request) are not opened.
- An ad for 4–8 guests that is not a room gives price/night × `nights` as **2+2**.
- When the text says the price is per person, it is ×2 adults as **2+0**. The tourist-tax "po osobi dnevno" line is ignored.
- Prices above `max_night_eur` (a €2,200 time-share sale) are dropped.

**Family facts:**
- `separate_bedroom` is True only when the owner names a bedroom. It is False for studios / garsonjere. Otherwise it is None, and the note says to ask.
- `cots_mentioned` is set when the text or the bedroom equipment names a cot ("krevetac", "krevetić", "bebi krevet").
- `playroom` is set when the text names one ("igraonica", "dečiji kutak").
- Other facts are noted only: pool/spa, and distance to the centre.

Board is SC, the id is `ho-<ad id>`, and the photo is hotlinked from the large `/l/` image.

## robots.txt (https://www.halooglasi.com/robots.txt, checked 2026-11-28)
```
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /
...
User-agent: *
Disallow: /profil
Disallow: /postavite-oglas
Disallow: /upload
Disallow: img.halooglasi.com/slike/oglasi/Thumbs/*/m
Disallow: img.halooglasi.com/slike/oglasi/Thumbs/*/s
Disallow: *?print
Disallow: /prijava
Disallow: /registracija
```
The Cloudflare-managed block disallows named AI crawlers only (ClaudeBot, GPTBot, CCBot …), not our UA.
The module uses `/odmor/planine/<place>`, `?page=N` and `/odmor/planine/<slug>/<id>`, all of which are allowed.
It never uses the contact-reveal, profile or print URLs. The `/m/` and `/s/` thumbnails are not used; it hotlinks the `/l/` image.
The content signal (`ai-train=no`) is honoured: the module stores facts for a personal planner and trains nothing.
No bot wall was seen across ~20 page loads.

## TOML block for config.toml
```toml
[sources.winter_more]
# Halo Oglasi (halooglasi.com) — owners' holiday-rental ads, Odmor › Planine. robots.txt allows the
# lists and ads (only /profil, /prijava, /postavite-oglas, ?print and small thumbnails are off-limits).
# Owner's advertised EUR/night for the whole unit (season not stated) × nights; 4–8 guest units = "2+2".
# "Dogovor" (price on request) cards are skipped unopened.
enabled = true
list_pages = 2              # list pages per resort (20 ads each)
max_listings = 12           # ads opened per resort (one request each)
max_capacity = 8
max_night_eur = 400

[[sources.winter_more.pages]]
url = "https://www.halooglasi.com/odmor/planine/kopaonik"
place = "kopaonik"
season = "winter"
area = "Kopaonik, Serbia"
country = "RS"
lat = 43.285
lng = 20.81
nights = 5
check_in = "2027-01-16"

[[sources.winter_more.pages]]
url = "https://www.halooglasi.com/odmor/planine/stara-planina"
place = "stara planina"
season = "winter"
area = "Stara Planina, Serbia"
country = "RS"
lat = 43.373
lng = 22.606
nights = 5
check_in = "2027-01-16"
list_pages = 1
```
A full run costs about 17 requests: 3 list pages plus up to 13 ads, plus robots.txt.

## Live check (2026-11-28, check-in 2027-01-16, 5 nights)
| Resort | Ads | Priced | Opened | Offers |
|---|---|---|---|---|
| Kopaonik | 83 | 21 on pages 1–2 | 14 | 13 |
| Stara Planina | 1 | 1 | 1 | 1 |

The check found **14 priced offers, all "2+2"**. 5-night totals run from €150 to €550.
- Separate bedroom: 7 True, 1 False (a studio), 6 unknown.
- No priced ad mentioned a cot. The one cot mention found was in a Zlatibor "Dogovor" ad.
- The offers pass `validate.problems`, and all have a photo.
- Development used about 32 live requests: robots.txt, 6 list pages and 16 ads on halooglasi, plus 4 OSRM drive checks.

## Areas checked and not built
- **Zlatibor / Tornik**: out of reach. OSRM gives 343 min (Zlatibor) and 381 min (Tornik), plus the 30-min
  border buffer, which is above 300 + 45. Halo Oglasi has 270 Zlatibor ads, so the module works there (tested on a Zlatibor ad).
  Add a page only if the drive rule changes.
- **Brezovica**: `/odmor/planine/brezovica` returns 404. Web searches found only Booking/Expedia/Hotels.com (excluded)
  and no hotel with a published price list. **No viable source.**
- **Jahorina**: about 7h by road, so out.
- **Bansko/Borovets/Pamporovo/Dobrinishte aparthotels**: already covered with 1-bedroom rows by bgski (per-hotel price
  lists) and bg_more (Pochivka). Aparthotels' own sites (Winslow etc.) found by search price via booking engines or UK
  packages, so they add nothing that is allowed. Not rebuilt.
- **Mavrovo / Popova Šapka**: covered by mk_local (Kajak.mk). Halo Oglasi is Serbia-only.

## Known limits
- **The season is not stated.** It is the owner's current headline price, and Kopaonik's January–February rate may be higher. The notes say
  to confirm the price for the dates. There is no availability.
- About half of Kopaonik ads are "Dogovor" (no price) and are skipped, even when they state good facts.
- There are no discounts except the owner's `last_minute_b` flag (a label, with no `was_eur`).
- Ratings are none, so the hotel rating rule keeps these at "ask", as with the other owner sources.
- Some ads come from small agencies ("Stan Na Dan …", type Hotel). They are kept, and kind is "hotel".
- Bedroom and cot detection reads Serbian free text. Silence means unknown, never "no", except for studios.
- Stara Planina has a single ad today.

## For the integrator
- Add `winter_more` to the imports and to `AUTO_SOURCES` in `trips/run.py`, and add the TOML block above.
- No new fields. `family` uses the existing keys `separate_bedroom`, `cots_mentioned` and `playroom`.
- Optional: add `"www.halooglasi.com" = 8` to the host delays if the run uses `host_delays`.
