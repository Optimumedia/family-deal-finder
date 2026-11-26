# mk_agencies: North Macedonian travel agencies (not Fibula)

## Result
Out of the agencies I checked, only **AtlantiS** (atlantis.mk / atlantisonline.mk, a Skopje agency on the Tournate booking platform) has prices in server-rendered HTML.
- It shows **winter Bulgaria** prices: Bansko, Razlog, Borovets and Pamporovo. Each price is the stay total for 2 adults, by room type and board, with "Apt 1 Bedroom" rooms shown separately.
- It shows **no summer prices**: Greece is "хотели на барање" (hotels on request).
- No agency I checked has an allowed, server-rendered price for Greece summer 2027.

Module: `trips/sources/mk_agencies.py` · tests: `tests/test_mk_agencies.py` (12 tests, passing) · fixtures: `tests/fixtures/mk_agencies_atlantis_{bansko,borovets,home_menu}.html`.

## How it works
The module reads the agency's own saved-search result pages, which are linked from its menu (`/hotels/bansko?PartialGuid=…`).

**What each hotel card gives:**
- hotel name, stars (sometimes) and photo
- the stay total in EUR for `data-adultcount` adults and `data-childcount` children: 2 adults and 0 children in every page I checked, so offers are stored as `"2+0"`
- the number of nights (4)
- every room type with its board and price
- for early-booking cards: the old price and the % off (`#EB Discount#`)

**Which room becomes the offer:**
- Winter: the cheapest room whose name states a bedroom ("Apt 1 Bedroom", "One Bedroom Apartment", …). That hotel gets `family.separate_bedroom = true` and `kind = "apartment"`. If the hotel lists no such room, the cheapest room is used and the fact stays unknown.
- Summer: the cheapest HB, FB or AI room.

**If a saved-search link goes stale:** the agency can refresh its saved-search GUIDs. When a configured page has no cards, the module looks up the current link in the homepage menu once and retries.

## robots.txt evidence (fetched 25.11.2026)
| Agency | Domain found | robots.txt | Prices server-side? |
|---|---|---|---|
| **AtlantiS** | www.atlantis.mk, atlantisonline.mk | Only `Content-Signal` comment lines, no `User-agent`/`Disallow` rules at all. Everything is allowed. | **Yes**: winter Bulgaria. Greece is on request. |
| Pilot Travel | pilottravel.com.mk | 404 (no file), so everything is allowed | No. The Next.js pages carry hotel lists and early-booking text ("За резервација до 30.11.2026 5% попуст…"), but prices load through a POST server action after a date search. |
| Kompas | www.kompas.com.mk ("Kompas International Official") | 404 | No. The 24 KB homepage has no offers. |
| Explora (Prilep) | explora.mk | `User-agent: *` / `Allow: /` | No for hotels. Greece and Bulgaria hotel pages are a client-side search form; only city-break tours show "од € 239". |
| Sama Holiday (Veles) | samaholiday.com.mk | 404 (Joomla error page), so everything is allowed | No. Halkidiki items carry campaign text only (e.g. Simantro Beach: "до 31.01.2027 20% попуст"). |
| Noa Tours | noatours.mk | WordPress default: disallows `/wp-admin/` and `?add-to-cart=` | No. /leto-grcija/ has no prices in the HTML. |
| AS Travel | astravel.com.mk | Disallows checkout/login and price filters, `Allow: /` | No prices on the homepage. Not pursued further. |
| Sv. Nikola Turs | www.svnikolaturs.mk | Cloudflare managed: `User-agent: *` `Allow: /`, but `ClaudeBot`, `anthropic-ai`, `GPTBot` … `Disallow: /` | Not fetched beyond the homepage. Left alone. |
| Atlantik Turs | atlantikturs.com | empty | No. Charter/own-allotment programmes as text, no price list in the HTML. |
| Eurotours | eurotours.mk / .com.mk don't resolve; eurotours.com is unrelated | – | Couldn't find an MK site |
| Mouse Tours | mousetours.com.mk / .mk don't resolve; mousetours.com is an unrelated company | – | Couldn't find an MK site |
| Bombi Travel | bombi(travel).mk / .com.mk don't resolve | – | Couldn't find a site |
| Zito | zito.com.mk is the Žito supermarket chain | – | No agency site |
| Ohrid Travel | ohridtravel.com is a New Jersey agency | – | Couldn't find an MK site |
| Sky Travel | skytravel.mk / .com.mk / sky-travel.mk don't resolve | – | Couldn't find a site |
| Feniks | feniks.mk redirects to feniks.net.mk, a publishing house | – | No agency site |
| Etiket | etiket.mk is an event-ticket shop | – | No agency site |

Web search didn't surface official sites for Eurotours, Mouse Tours, Bombi, Sky Travel or Ohrid Travel. They may exist only on Facebook or Instagram, which is out of scope.

## TOML block to add to config.toml
```toml
# ------------------------------------------------- Macedonian agencies (AtlantiS) --
[sources.mk_agencies]
# atlantis.mk — Skopje agency, robots.txt has no Disallow rules. Saved-search result pages:
# stay total for 2 adults, every room type with board; the stay dates are the agency's and
# aren't shown, so check_in below is our assumption. Greece there is "on request" (no prices).
enabled = true
home = "https://www.atlantis.mk/"

[[sources.mk_agencies.pages]]
url = "https://www.atlantis.mk/hotels/bansko?PartialGuid=1f54d4c1-4682-415e-a6b3-854b99efbc22"
season = "winter"
area = "Bansko, Bulgaria"
country = "BG"
lat = 41.83
lng = 23.48
nights = 4
check_in = "2027-01-15"

[[sources.mk_agencies.pages]]
url = "https://atlantisonline.mk/hotels/razlog?PartialGuid=468975a6-b120-4ef1-8036-2daf601b04f6"
season = "winter"
area = "Razlog (Bansko area), Bulgaria"
country = "BG"
lat = 41.886
lng = 23.462
nights = 4
check_in = "2027-01-15"

[[sources.mk_agencies.pages]]
url = "https://atlantisonline.mk/hotels/borovets?PartialGuid=cf76af02-5ce1-415f-a46a-3fb269306d0b"
season = "winter"
area = "Borovets, Bulgaria"
country = "BG"
lat = 42.266
lng = 23.606
nights = 4
check_in = "2027-01-15"

[[sources.mk_agencies.pages]]
url = "https://atlantisonline.mk/hotels/pamporovo?PartialGuid=65ef5dd6-0a9a-4aac-8e78-7e318678387a"
season = "winter"
area = "Pamporovo, Bulgaria"
country = "BG"
lat = 41.652
lng = 24.692
nights = 4
check_in = "2027-01-15"
```

## Live check (25.11.2026)
4 pages were fetched through PoliteSession, 6–10 s apart.
- **28 priced offers:** Bansko 9, Razlog 5 (one of them also listed under Bansko and skipped as a duplicate), Borovets 6, Pamporovo 8. That is 27 unique hotels.
- **24 offers are 1-bedroom apartments**, from €339 for 4 nights (BB).
- **1 offer carries an early-booking discount:** Grand Hotel Bansko One Bedroom Apartment HB, €1,115, down from €1,312 (−15%).

## Known limits
- **Dates are hidden.** The saved search's check-in isn't in the HTML; the homepage "popular hotels" cards carry dates from 30.11.2026 to 06.03.2027. The configured `check_in` is an assumption, and if the agency changes its search dates the price can move without a real price change.
- **"2+0" only.** These pages never include children. The cots and kids' prices still need asking.
- **Stars are often blank** on these pages.
- **No `valid_until`:** the pages give none.
- **No summer coverage.** Pilot Travel and Sama Holiday publish Halkidiki 2027 early-booking campaigns as plain text, e.g. "for bookings until 31.01.2027, 10% off". Those could feed `hotel_direct`-style campaigns, but they would need a hotel-id mapping, so I didn't build that.

## For the integrator
- Add `mk_agencies` to `AUTO_SOURCES` in `trips/run.py`, and add the config block above.
- `merge_auto` will fold the Bansko hotels into the existing curated ones by name (e.g. Casa Karina).
- `family.separate_bedroom = true` is set from the room-type name. It isn't added to `verified`.
- The offer's `url` is the saved-search page where the price is shown. The hotel's own page is in `notes`.
