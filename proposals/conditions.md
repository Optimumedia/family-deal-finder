# conditions: sea, snow and family places per area

Owner: `conditions`. New files: `trips/conditions.py`, `tests/test_conditions.py`, and these fixtures: `tests/fixtures/conditions_overpass_borovets.json`, `conditions_overpass_kassandra.json`, `conditions_archive_bansko_2024_25.json` and `conditions_marine_kassandra_2025.json`. These are real answers from 26.11.2026, cut to one location each. The cache is `data/conditions_cache.json` (32 KB, all 28 areas filled).

## What it does
The data is fetched **per area**, not per hotel. An area is (season, `area` string with "(villa)"/"(rental)" dropped), placed at the median of its hotels' coordinates. The current data gives **28 areas**.

1. **Climate.** Typical values by month from the last 3 complete seasons (summers 2024–26, winters 2023/24–2025/26). The source is Open-Meteo: the `archive-api` (ERA5/ERA5-Land) and the `marine-api`.
   - Summer (June–September): sea °C, `sea_ok` (sea ≥ 24 °C), air max and mean, sunshine hours a day, and rainy days a month.
   - Winter (November–March): air mean, min and max, snowfall in cm a month, snow depth in cm (the mean of each day's maximum), and `snow_sure_pct` (the share of days with ≥ 30 cm).
   - Open-Meteo takes many coordinates in one call. So **all areas of a season share one request per year**: 3 × (archive + marine) for summer and 3 × archive for winter, **9 requests in total**.
   - If the marine grid cell snaps more than 25 km away, the area counts as having no sea. That is how Ohrid (a lake) gets `sea_c: null`.
2. **Family places** come from OSM through Overpass, with **one query per area point**. Areas within 2 km of each other share one query.
   - It counts playgrounds, water parks, doctors/clinics, `healthcare:speciality~paediatric` and pharmacies within 5 km.
   - Winter areas also count `piste:difficulty=novice` ways and `aerialway=magic_carpet` within 10 km.
   - It also finds the nearest `amenity=hospital` within 30 km, skipping defibrillators ("AED POINT") and ambulance posts that are mis-tagged as hospitals.
3. **Cache and limits.** Each area's climate and places are refetched after 30 days, or if the area point moves more than 1 km. The cache is saved after every step. Other limits:
   - a hard request budget (`max_requests`, 60)
   - an honest User-Agent
   - at least 5 s between requests to a host, and 15 s for Overpass, counted from the end of the last answer
   - a declared `[timeout:60]`
   - backing off and retrying on 429, 502, 503 and 504

   A failure is logged and never raised. Offline, the module reads the cache only.
4. **Output.** `update()` returns `{area_key: entry}`, and `attach(items, info)` sets `item["area_info"]`. Each `area_info` holds:
   - the climate for the trip month (from `check_in`) and the place counts
   - `hospital_km` and `hospital_name`
   - `toddler_flags`, for example "sea 25°C: warm for toddlers", "hot (33°C afternoons)", "below freezing all day (-1°C max)", "magic carpet (kids' ski lift) nearby", and "hospital 31 km away" (more than 25 km)

## robots.txt (needs your decision)
`archive-api` and `marine-api.open-meteo.com` serve `Disallow: /`, and `overpass-api.de` serves `Disallow: /api/`. Both are public APIs whose documented purpose is to be called by programs:
- Open-Meteo's terms allow free non-commercial use under 10,000 calls a day, under CC BY 4.0.
- Overpass's policy allows under 10,000 queries and 1 GB a day.

So, like `trips/geo.py`'s OSRM call, the module calls them directly instead of through `PoliteSession`, which would refuse them. If you read the project rule strictly, set `[conditions] enabled = false`. The dashboard then shows whatever the cache already holds, or nothing.

**Attribution to show on the dashboard footer:** "Weather: Open-Meteo.com (CC BY 4.0). Places: © OpenStreetMap contributors (ODbL)." It is `conditions.ATTRIBUTION`.

## Integration diff: `trips/run.py` (integrator)
```diff
-from . import db, digest, enrich, geo, health, score, validate
+from . import conditions, db, digest, enrich, geo, health, score, validate
@@ def main(argv=None) -> int:
     items, alerts = build(con, cfg, today, offline=args.offline)
     alerts = new_camps + alerts
+    if cfg.get("conditions", {}).get("enabled", True):
+        # sea / snow / family places per area: cached monthly, ~0 live requests on most runs
+        with hl.track("Area conditions", None) as st:
+            area = conditions.update(items, cfg, today, offline=args.offline)
+            st.offers_parsed = conditions.attach(items, area)
     con.commit()
     export(items, alerts, cfg)
```
If `hl.track` needs a real session for its stats, drop the `with` and call the two lines directly. `update()` never raises.

## Config block (`config.toml`, integrator)
```toml
[conditions]
# Sea/air temperature and snow (Open-Meteo, typical of the last 3 seasons) and family places
# within 5 km (OpenStreetMap / Overpass), per area. Cached in data/conditions_cache.json for 30 days.
enabled = true
max_requests = 60          # live requests per run, all hosts together (a full refresh is ~37)
places_radius_m = 5000
ski_radius_m = 10000       # ski towns sit below the beginner areas
hospital_radius_m = 30000
years = 3
```
Keep `data/conditions_cache.json` **in git**, unlike the enrich cache. It holds no private data, and a fresh clone or another PC then needs no live requests.

## Dashboard suggestion (`docs/index.html`, UI owner)
Add one chip to the existing chip row next to drive, board and dates, plus a line in the detail dialog. Reuse the existing classes:
```js
const areaChip = o => {
  const a = o.area_info; if (!a) return '';
  if (o.season === 'summer') {
    if (a.sea_c == null) return '';
    return `<span class="chip${a.sea_ok ? ' good' : ' warn'}" title="Typical sea in ${monthName(a.month)}, last 3 summers">Sea ${Math.round(a.sea_c)}°C · ${Math.round(a.air_max_c)}°C air</span>`;
  }
  return `<span class="chip" title="Typical ${monthName(a.month)} at the town, last 3 winters">${Math.round(a.air_max_c)}°C max · ${a.novice_pistes ?? 0} beginner runs${a.magic_carpets ? ' · magic carpet' : ''}</span>`;
};
```
Detail dialog: "Nearby (5 km): 25 playgrounds · 9 pharmacies · 1 water park · hospital 1.1 km (Поликлиника)". Show `toddler_flags` as small muted text. Show "hospital > 25 km" as `chip warn`. In the footer, add the attribution above. Don't put the snow depth on the card (see the limits).

## Measured effect (offline, current `docs/data.json`, 475 offers)
- **Before:** no area context.
- **After:** 475 of 475 offers have an `area_info`, from 28 areas, all with climate and places.
- **Sea:** 145 of 165 summer offers are `sea_ok` for their trip month (June 2027). The other 20 are Ohrid (16, a lake, no sea value) and Ulcinj in June (4, 23.9 °C).
- **Live requests used while building:**
  - 33 in the first run (9 Open-Meteo and 24 Overpass, of which 10 failed with 502)
  - 18 in the retry run, after raising the Overpass gap to 15 s
  - 2 for the last area
  - 5 probes and robots.txt checks

  That is 58 in total. A normal monthly refresh is 9 + about 25.
- The full suite passes (311 tests, 16 of them new). `python -m trips.run --offline` is OK.

Six sample areas (climate for July in summer and January in winter; `pg` = playgrounds, `wp` = water parks, `ph` = pharmacies):

| Area | Sea °C (Jun/Jul/Aug/Sep) | Air max | Sun h/day | Places within 5 km | Nearest hospital |
|---|---|---|---|---|---|
| Kassandra | 24.8 / 27.6 / 27.2 / 25.8 | 31.9 | 13.8 | pg 0, wp 0, ph 5, doctors 0 | 3.8 km (Kentro Ygeias Kassandreias) |
| Sithonia | 25.3 / 28.3 / 27.8 / 26.1 | 32.1 | 13.9 | pg 1, ph 3 | 1.6 km (Aegean Medical Centre) |
| Olympic Riviera | 25.1 / 28.0 / 27.8 / 26.1 | 32.6 | 13.9 | pg 13, wp 1, ph 6, doctors 6 | 13.4 km (Katerini General) |
| Antalya (Alanya) | 26.4 / 29.2 / 30.0 / 29.2 | 33.2 ("hot" flag) | 14.0 | pg 50, wp 1, ph 114, paediatric 1 | 1.3 km |

| Area | January air mean / min / max | Snowfall cm/month | Snow depth cm (town) | Ski within 10 km | Places within 5 km | Hospital |
|---|---|---|---|---|---|---|
| Bansko | 1.3 / −2.8 / 6.5 | 8 | 16 | 15 novice runs, 1 magic carpet | pg 25, ph 9, paediatric 1 | 1.1 km (Poliklinika) |
| Kopaonik | −5.3 / −8.9 / −1.0 ("below freezing" flag) | 21 | 13 | 13 novice runs, 3 magic carpets | pg 4, ph 1 | 15.8 km (Dom zdravlja Raška) |

## Known limits
- **Snow depth reads too low for resorts.** The reanalysis grid cell (about 9–25 km) averages the terrain, so Kopaonik in January shows about 13 cm while the pistes have far more and snowmaking. For that reason there is **no snow-reliability flag**, and snow is kept as relative data only. Temperatures do use the point's elevation.
- **Sunshine** (about 14 h a day in July) is Open-Meteo's modelled sunshine, close to day length in clear summers.
- **Sea is the modelled surface temperature.** The 3 summers include the record-hot 2024, so treat it as slightly warm-biased. It's fine for the ≥ 24 °C cut.
- **OSM is incomplete.** Kassandra shows 0 playgrounds and Pamporovo 0 pharmacies. Some health centres are tagged `amenity=hospital`. Zero means "not mapped", not "none".
- **Area points come from hotel coordinates.** Some are placeholders: "Halkidiki", "Nea Propontida" and "Vourvourou" all sit at 40.1, 23.6, so they show identical, inland-looking places (0 within 5 km). Fixing those coordinates in `data/hotels.toml` fixes the area. The cache refetches when a point moves more than 1 km.
- **Overpass needs patience.** The public instance answered 502 to every second query at a 5 s gap. With 15 s, a full refresh takes about 10–15 minutes, once a month.
- **Robots.txt** needs the decision above.
