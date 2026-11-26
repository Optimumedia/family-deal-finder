# More destination pages for Olympic and Travelland (agent: `destinations`)

Checked on 2026-11-25. No new module: everything below goes into the existing
`[sources.olympic]` / `[sources.travelland]` blocks. About 38 page requests in total,
5–6 s apart, all through `PoliteSession`.

## Source and robots.txt

Both sites run the same Yoast robots.txt, which allows every path:

```
User-agent: *
Disallow:

Sitemap: https://www.olympic.rs/sitemap_index.xml      (travelland.rs: same)
```

Each `sitemap_index.xml` lists one `page-sitemap.xml`: 467 URLs on Olympic, 511 on Travelland.
I filtered them for every resort within about 5h45 of Skopje. Then I fetched each candidate
page for its `data-destination` code and one `/services/list/` page (`perPage` is capped at 20).

## Results

"Priced" means the cards the current parser accepts, i.e. not "Dostupno na upit".

| Site | Page | Code | Listed | Priced | Drive from SKP | Verdict |
|---|---|---|---|---|---|---|
| Olympic | makedonija-letovanje/ohrid | `144:158:263:9157` | 26 | 13 of first 20 | ~2h45 | **Add.** Undated prices, no badge |
| Olympic | zimovanje/bugarska/pamporovo | `22:1252:2432:12625` | 6 | 3 | ~5h45 (borderline) | **Add.** RANI BUKING −9 to −15 %, valid until 30.11.2026 |
| Olympic | zimovanje/srbija/stara-planina | `190:25:2354:12470` | 1 | 1 | ~4h30 (via Niš, Knjaževac) | **Add.** 1 resort, RANI BUKING |
| Olympic | crna-gora-promotivne-cene/ulcinj | `140:26:496:9725` | 3 | 3 | ~5h15 (Prizren, Kukës, Shkodër) | **Add.** Azul Beach −30 %, valid until 2.12.2026 |
| Olympic | crna-gora-promotivne-cene/dobre-vode | `140:26:492:12127` | 2 | 1 | ~5h40 (borderline) | **Add.** Radisson Wind Rose |
| Olympic | albanija/drac (Durrës, Golem hotels show as "Drač") | `6:516:847:10073` | 26 | 0 (all on request) | ~4h45 | Watch: the code works, but there are no prices yet |
| Olympic | albanija/valona (Vlorë) | `6:1011:2089:12118` | 4 | 0 | ~5h20 | Watch |
| Olympic | grcka-promotivne-cene/kavala | `89:1044:2129:12164` | 0 | 0 ("Ponuda stiže uskoro") | ~4h15 | Watch: will fill for 2027 |
| Olympic | halkidiki/atos, atos/jerisos | none (`data-destination=""`, tag 310) | – | – | ~4h15 | Not usable. Olympic ignores `tagCategoryId` and returns the whole 613-hotel catalogue |
| Travelland | grcka/stavros | `89:129:2467:13429` | 1 | 0 | ~3h45 | Watch |
| Travelland | crna-gora/ulcinj | `140:26:496:9725` (same code as Olympic) | 3 | 1 card, **0 offers** | ~5h15 | Parser drops it: there's no date window (see below) |
| Travelland | halkidiki/atos | `89:1042` | 0 | 0 | ~4h15 | Nothing listed |
| Travelland | letovanje/hoteli/tasos | none (tag 564) | 31 via tag | 10 cards, **0 offers** | ~5h15 incl. ferry | Needs a new field and a parser fix |
| Travelland | grcka/olimpska-regija | none (tag page) | – | – | ~3h | Needs a new field (tag id not checked) |

**Ready now:** 21 priced offers from the five "Add" pages: Ohrid 13 (first list page only;
up to 6 more are on page 2), Pamporovo 3, Stara Planina 1, Ulcinj 3, Dobre Vode 1.

**Not on either site:** Asprovalta, Nea Vrasna, Velipojë, Shëngjin, Mavrovo and Popova Šapka.
Golem hotels appear under Drač.

**Already covered by the parent pages:** Sarti, Toroni and the other Sithonia villages, the
Kassandra villages, and the Olympic Riviera villages all have their own Olympic sub-pages, but
the configured parent codes already list those hotels.

**Too far (over 6h):** Sunny Beach, Nesebar, Sveti Vlas, Golden Sands, Budva and everything
north of Bar, Saranda, Ksamil, Jale, Parga, Sivota, Skiathos and Zlatibor (~5h45–6h, left out).
Alexandroupoli is ~5h30 but wasn't checked (out of request budget).

## TOML to paste (into config.toml, after the existing Olympic pages)

`destination` is an existing optional key that `fetch` already reads. Setting it skips the page
request on every run.

```toml
# --- added by proposals/destinations.md: priced offers on 2026-11-25 ---
[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/makedonija-letovanje/ohrid/"
destination = "144:158:263:9157"
season = "summer"
area = "Ohrid, North Macedonia"
country = "MK"
lat = 41.117
lng = 20.802
border = false
nights = 7
check_in = "2027-06-20"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/zimovanje/bugarska/pamporovo/"
destination = "22:1252:2432:12625"
season = "winter"
area = "Pamporovo, Bulgaria"
country = "BG"
lat = 41.652
lng = 24.692
nights = 5
check_in = "2027-01-15"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/zimovanje/srbija/stara-planina/"
destination = "190:25:2354:12470"
season = "winter"
area = "Stara Planina, Serbia"
country = "RS"
lat = 43.373
lng = 22.612
nights = 5
check_in = "2027-01-15"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/crna-gora-promotivne-cene/ulcinj/"
destination = "140:26:496:9725"
season = "summer"
area = "Ulcinj / Velika Plaža, Montenegro"
country = "ME"
lat = 41.90
lng = 19.27
nights = 7
check_in = "2027-06-20"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/crna-gora-promotivne-cene/dobre-vode/"
destination = "140:26:492:12127"
season = "summer"
area = "Dobre Vode, Montenegro"
country = "ME"
lat = 42.03
lng = 19.13
nights = 7
check_in = "2027-06-20"

# --- watch list: codes work, no prices yet (each costs one list request per run) ---
[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/albanija/drac/"
destination = "6:516:847:10073"
season = "summer"
area = "Durrës / Golem, Albania"
country = "AL"
lat = 41.28
lng = 19.48
nights = 7
check_in = "2027-06-20"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/albanija/valona/"
destination = "6:1011:2089:12118"
season = "summer"
area = "Vlorë, Albania"
country = "AL"
lat = 40.45
lng = 19.49
nights = 7
check_in = "2027-06-20"

[[sources.olympic.pages]]
url = "https://www.olympic.rs/letovanje/grcka-promotivne-cene/kavala/"
destination = "89:1044:2129:12164"
season = "summer"
area = "Kavala, Greece"
country = "GR"
lat = 40.94
lng = 24.41
nights = 7
check_in = "2027-06-20"
```

Travelland: these are worth adding only after the parser fix below. Until then they give 0 offers.

```toml
[[sources.travelland.pages]]
url = "https://www.travelland.rs/destinacije/crna-gora/ulcinj/"
destination = "140:26:496:9725"
season = "summer"
area = "Ulcinj / Velika Plaža, Montenegro"
country = "ME"
lat = 41.90
lng = 19.27
nights = 7

[[sources.travelland.pages]]
url = "https://www.travelland.rs/destinacije/grcka/stavros/"
destination = "89:129:2467:13429"
season = "summer"
area = "Stavros, Greece"
country = "GR"
lat = 40.665
lng = 23.70
nights = 7
```

## Needs the integrator

1. **Travelland summer cards are dropped.** Summer cards (Ulcinj, the Thassos tag list) have no
   hidden `display: none` date window. Their deadline line reads `VAŽE DO 30.11.2026` where the
   regex expects `VAŽI DO`. `to_hotel_and_offer` returns None when `date_from` is missing, which
   likely explains why the live run's Travelland Kassandra and Sithonia return 0 offers.
   Fix: fall back to the page's `check_in` when `date_from` is missing, and match `VA[ŽZ][IE] DO`.
2. **Tag-category pages (Travelland only).** Travelland's Thassos and Olympic Riviera pages have
   `data-destination=""` and fill their list from `data-tagcategoryid` (Thassos = 564). The call
   `/services/list/?destination=&tagCategoryId=564&template=featured&perPage=20&paginate=1`
   returned 31 Thassos hotels, 10 of them priced, at 7–27 % off. A `tag_category` page key plus
   fix 1 would unlock both pages. Olympic ignores `tagCategoryId`, so Olympic Athos can't use it.
3. **Olympic board is mostly "?".** Ulcinj and Ohrid cards use `<div class="text-uppercase small">`,
   but `_BOARD_TXT` expects exactly `class="text-uppercase"`. Loosen it to `class="text-uppercase[^"]*"`.
4. **Olympic price 0.** A card ("Palas", Petrovac) showed `€ 0`. `parse_list` should skip a price of 0.
5. **Olympic Thassos is already configured** but logged "0 hotels listed" today. The page has a
   code, but nothing is listed under it. Leave it in place; it may fill for 2027.

## Known limits

- Priced counts are from the first list page only (20 cards).
- Olympic Ohrid prices are undated: no badge and no valid-until. They may be 2026 rates carried
  over, not 2027 offers.
- Drive times are estimates for normal summer traffic, not route-planner output. Pamporovo and
  Dobre Vode are at the edge of the 5h + 45 min limit. Ulcinj and Dobre Vode assume the Kukës–Shkodër road.
- All occupancy stays "2+0" (agency "from" prices per person or per unit), as in the existing sources.
