"""Destination context for 3-year-olds, per AREA (not per hotel): sea and air temperature,
sunshine, snow, and family places nearby. Cached in data/conditions_cache.json, refreshed monthly.

Sources (free, no key):
- Open-Meteo historical weather (archive-api.open-meteo.com, ERA5 / ERA5-Land reanalysis) and
  marine (marine-api.open-meteo.com) APIs. Free tier: non-commercial use, < 10,000 calls a day,
  data under CC BY 4.0 ("Weather data by Open-Meteo.com"). One request asks for ALL areas of a
  season at once (Open-Meteo takes comma-separated coordinates), one request per past season:
  3 summers x (archive + marine) + 3 winters x archive = 9 requests for every area together.
- OpenStreetMap via the public Overpass API (overpass-api.de). Usage policy: < 10,000 queries
  and < 1 GB a day; declare a [timeout:]; back off on 429/504. One small query per area point.
  Data (c) OpenStreetMap contributors, ODbL.

Both hosts' robots.txt disallow crawlers ("Disallow: /" and "Disallow: /api/"). These are
documented public APIs meant to be called by programs, so - like the OSRM drive-time lookup in
trips/geo.py - they are called directly with an honest User-Agent, >= 5 s between requests to
a host, a request budget per run, and a monthly cache, instead of through PoliteSession (which
would refuse them on robots.txt grounds). See proposals/conditions.md.

Climate values are typical values ("climatology") from the last 3 complete seasons, by month:
- summer (June-September): sea surface temperature (mean of the hourly values), air max/mean,
  sunshine hours a day, rainy days; `sea_ok` = sea >= 24 C (toddler-comfortable).
- winter (November-March): air mean/min/max, monthly snowfall (cm), typical snow depth (mean of
  the daily maximum, cm) and the share of days with >= 30 cm of snow on the ground.
Reanalysis is a ~10-25 km grid with the point's elevation applied to temperature; it reads the
weather at the hotel/town point, not on the upper slopes.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import statistics
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import requests

log = logging.getLogger(__name__)

USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner; contact via project owner)"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_PATH = Path("data/conditions_cache.json")
ATTRIBUTION = "Weather: Open-Meteo.com (CC BY 4.0). Places: © OpenStreetMap contributors (ODbL)."

SUMMER_MONTHS = (6, 7, 8, 9)
WINTER_MONTHS = (11, 12, 1, 2, 3)
SEA_OK_C = 24.0
SNOW_SURE_CM = 30.0
MAX_AGE_DAYS = 30            # "refresh monthly"
MIN_GAP_S = 5.0              # between two requests to one host (from the end of the last answer)
HOST_GAPS = {"overpass-api.de": 15.0}   # the public Overpass instance answered 502 to every 2nd query at 5 s
SEA_SNAP_KM = 25.0           # marine grid cell farther than this from the area = no sea (e.g. Ohrid, a lake)
SHARE_POINT_KM = 2.0         # areas this close share one Overpass query

DEFAULTS = {
    "enabled": True,
    "max_requests": 60,      # live requests per run, all hosts together
    "places_radius_m": 5000,
    "ski_radius_m": 10000,   # ski towns sit below the slopes (Bansko town -> beginner area ~7 km)
    "hospital_radius_m": 30000,
    "years": 3,
    "overpass_url": OVERPASS_URL,
}

Fetch = Callable[[str, dict | None, str | None], object]   # (url, params, post_body) -> parsed JSON


# ------------------------------------------------------------------------------ areas ---

_PAREN = re.compile(r"\s*\((villa|villas|rental|apartment|apartments)\)\s*$", re.I)


def area_key(season: str, area: str) -> str:
    """'Kassandra, Halkidiki (villa)' -> 'summer|kassandra, halkidiki'. Villa/rental tags dropped."""
    name = _PAREN.sub("", (area or "").strip())
    return f"{season}|{' '.join(name.lower().split())}"


def areas_from_items(items: list[dict]) -> dict[str, dict]:
    """One entry per (season, area) with the median of its hotels' coordinates."""
    pts: dict[str, list] = defaultdict(list)
    names: dict[str, str] = {}
    for it in items:
        if not it.get("area") or it.get("lat") is None or it.get("lng") is None:
            continue
        k = area_key(it["season"], it["area"])
        pts[k].append((it["lat"], it["lng"]))
        names.setdefault(k, _PAREN.sub("", it["area"].strip()))
    out = {}
    for k, p in sorted(pts.items()):
        out[k] = {"key": k, "season": k.split("|", 1)[0], "name": names[k],
                  "lat": round(statistics.median(x for x, _ in p), 4),
                  "lng": round(statistics.median(y for _, y in p), 4), "hotels": len(set(p))}
    return out


def haversine_km(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


# ------------------------------------------------------------------------------ http ---

class Budget(Exception):
    """The run's live-request budget is used up; the rest waits for the next run."""


class Client:
    """requests + honest User-Agent + >= MIN_GAP_S per host + a hard request budget."""

    def __init__(self, max_requests: int = 60, timeout: float = 90, gap: float = MIN_GAP_S):
        self.max_requests, self.timeout, self.gap = max_requests, timeout, gap
        self.made = 0
        self._last: dict[str, float] = {}
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def __call__(self, url: str, params: dict | None = None, body: str | None = None):
        host = url.split("/")[2]
        for attempt in range(3):
            if self.made >= self.max_requests:
                raise Budget(f"{self.made} live requests made")
            last = self._last.get(host)
            gap = max(self.gap, HOST_GAPS.get(host, 0.0))
            if last is not None and (wait := gap - (time.monotonic() - last)) > 0:
                time.sleep(wait)
            self.made += 1
            log.info("conditions: request %d -> %s", self.made, host)
            try:
                r = (self.s.post(url, data={"data": body}, timeout=self.timeout) if body is not None
                     else self.s.get(url, params=params, timeout=self.timeout))
            except requests.RequestException as e:
                self._last[host] = time.monotonic()
                log.warning("conditions: %s failed (%s): %s", host, attempt + 1, e)
                time.sleep(10 * (attempt + 1))
                continue
            self._last[host] = time.monotonic()
            if r.status_code in (429, 502, 503, 504):   # busy / slot cool-down -> back off, retry
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        raise requests.RequestException(f"gave up: {url}")


# --------------------------------------------------------------------------- climate ---

def season_ranges(season: str, today: date, years: int = 3) -> list[tuple[str, str]]:
    """The last `years` COMPLETE seasons before today (archive data lags ~5 days)."""
    out = []
    if season == "summer":
        y = today.year if today >= date(today.year, 10, 10) else today.year - 1
        for yy in range(y - years + 1, y + 1):
            out.append((f"{yy}-06-01", f"{yy}-09-30"))
    else:
        y = today.year if today >= date(today.year, 4, 10) else today.year - 1   # season ending in March of y
        for yy in range(y - years + 1, y + 1):
            out.append((f"{yy - 1}-11-01", f"{yy}-03-31"))
    return out


def _as_list(resp) -> list[dict]:
    return resp if isinstance(resp, list) else [resp]


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _by_month(times: list[str], values: list) -> dict[int, list]:
    out: dict[int, list] = defaultdict(list)
    for t, v in zip(times, values or []):
        if v is not None:
            out[int(t[5:7])].append(v)
    return out


def _daily_max_from_hourly(times: list[str], values: list) -> tuple[list[str], list]:
    days: dict[str, float] = {}
    for t, v in zip(times, values or []):
        if v is not None:
            d = t[:10]
            days[d] = max(days.get(d, v), v)
    ks = sorted(days)
    return ks, [days[k] for k in ks]


def summarize_summer(archive: list[dict], marine: list[dict | None]) -> dict[str, dict]:
    """archive: one Open-Meteo response per year for ONE location; marine: same (None = no sea)."""
    acc: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for a in archive:
        d = a.get("daily") or {}
        t = d.get("time") or []
        for name, key, f in (("air_max", "temperature_2m_max", None), ("air_mean", "temperature_2m_mean", None),
                             ("sun", "sunshine_duration", None), ("rain", "precipitation_sum", None)):
            for m, vs in _by_month(t, d.get(key)).items():
                acc[m][name] += vs
    for mr in marine:
        if not mr:
            continue
        h = mr.get("hourly") or {}
        for m, vs in _by_month(h.get("time") or [], h.get("sea_surface_temperature")).items():
            acc[m]["sea"] += vs
    out = {}
    for m in SUMMER_MONTHS:
        a = acc.get(m)
        if not a:
            continue
        sea = _mean(a["sea"])
        rain = a["rain"]
        out[f"{m:02d}"] = {
            "sea_c": sea, "sea_ok": None if sea is None else sea >= SEA_OK_C,
            "air_max_c": _mean(a["air_max"]), "air_mean_c": _mean(a["air_mean"]),
            "sun_h": None if not a["sun"] else round(sum(a["sun"]) / len(a["sun"]) / 3600, 1),
            # rainy days (>= 1 mm) in a typical month of 30 days
            "rain_days": None if not rain else round(sum(r >= 1 for r in rain) / len(rain) * 30),
        }
    return out


def summarize_winter(archive: list[dict]) -> dict[str, dict]:
    acc: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for a in archive:
        d = a.get("daily") or {}
        t = d.get("time") or []
        for name, key in (("t_mean", "temperature_2m_mean"), ("t_min", "temperature_2m_min"),
                          ("t_max", "temperature_2m_max"), ("snowfall", "snowfall_sum")):
            for m, vs in _by_month(t, d.get(key)).items():
                acc[m][name] += vs
        h = a.get("hourly") or {}
        dt, dmax = _daily_max_from_hourly(h.get("time") or [], h.get("snow_depth"))
        for m, vs in _by_month(dt, dmax).items():
            acc[m]["depth"] += vs
    out = {}
    for m in WINTER_MONTHS:
        a = acc.get(m)
        if not a:
            continue
        depth_cm = [v * 100 for v in a["depth"]]
        sf = a["snowfall"]
        out[f"{m:02d}"] = {
            "air_mean_c": _mean(a["t_mean"]), "air_min_c": _mean(a["t_min"]), "air_max_c": _mean(a["t_max"]),
            # cm of new snow in a typical 30-day month
            "snowfall_cm": None if not sf else round(sum(sf) / len(sf) * 30),
            "snow_depth_cm": None if not depth_cm else round(sum(depth_cm) / len(depth_cm)),
            "snow_sure_pct": None if not depth_cm else round(sum(v >= SNOW_SURE_CM for v in depth_cm) / len(depth_cm) * 100),
        }
    return out


def _coords(areas: list[dict]) -> dict:
    return {"latitude": ",".join(f"{a['lat']:.4f}" for a in areas),
            "longitude": ",".join(f"{a['lng']:.4f}" for a in areas)}


def fetch_climate(areas: list[dict], season: str, today: date, fetch: Fetch, years: int = 3) -> dict[str, dict]:
    """All areas of one season together: one archive (+ one marine) request per past season."""
    if not areas:
        return {}
    per_area_arch: list[list[dict]] = [[] for _ in areas]
    per_area_mar: list[list[dict | None]] = [[] for _ in areas]
    for start, end in season_ranges(season, today, years):
        p = {**_coords(areas), "start_date": start, "end_date": end, "timezone": "GMT"}
        if season == "summer":
            p["daily"] = "temperature_2m_max,temperature_2m_mean,sunshine_duration,precipitation_sum"
        else:
            p["daily"] = "temperature_2m_mean,temperature_2m_min,temperature_2m_max,snowfall_sum"
            p["hourly"] = "snow_depth"
        for i, r in enumerate(_as_list(fetch(ARCHIVE_URL, p, None))):
            per_area_arch[i].append(r)
        if season == "summer":
            mp = {**_coords(areas), "start_date": start, "end_date": end, "timezone": "GMT",
                  "hourly": "sea_surface_temperature", "cell_selection": "sea"}
            for i, r in enumerate(_as_list(fetch(MARINE_URL, mp, None))):
                a = areas[i]
                far = r.get("latitude") is None or haversine_km((a["lat"], a["lng"]), (r["latitude"], r["longitude"])) > SEA_SNAP_KM
                per_area_mar[i].append(None if far else r)
    out = {}
    for i, a in enumerate(areas):
        out[a["key"]] = (summarize_summer(per_area_arch[i], per_area_mar[i]) if season == "summer"
                         else summarize_winter(per_area_arch[i]))
    return out


# ---------------------------------------------------------------------------- places ---

def overpass_query(lat: float, lng: float, season: str, places_m: int = 5000, ski_m: int = 10000,
                   hospital_m: int = 30000) -> str:
    """One query, counts in a fixed order (see PLACE_KEYS), then hospitals with their centres."""
    r, at = places_m, f"{lat:.5f},{lng:.5f}"
    parts = [
        f'nwr(around:{r},{at})["leisure"="playground"];',
        f'nwr(around:{r},{at})["leisure"="water_park"];',
        f'nwr(around:{r},{at})["amenity"~"^(doctors|clinic)$"];',
        f'nwr(around:{r},{at})["healthcare:speciality"~"paediatric"];',
        f'nwr(around:{r},{at})["amenity"="pharmacy"];',
    ]
    if season == "winter":
        parts += [f'way(around:{ski_m},{at})["piste:difficulty"="novice"];',
                  f'way(around:{ski_m},{at})["aerialway"="magic_carpet"];']
    body = "".join(f"{p}out count;" for p in parts)
    return (f"[out:json][timeout:60][maxsize:33554432];{body}"
            f'nwr(around:{hospital_m},{at})["amenity"="hospital"];out tags center 60;')


# amenity=hospital is sometimes put on defibrillators ("AED POINT") or ambulance posts: not a hospital.
_NOT_HOSPITAL = re.compile(r"\b(aed|defibrillator)\b|ambulance|брза помош|ветерин|veterin", re.I)

PLACE_KEYS = {"summer": ["playgrounds", "water_parks", "doctors_clinics", "paediatric", "pharmacies"],
              "winter": ["playgrounds", "water_parks", "doctors_clinics", "paediatric", "pharmacies",
                         "novice_pistes", "magic_carpets"]}


def summarize_places(resp: dict, lat: float, lng: float, season: str) -> dict:
    els = resp.get("elements") or []
    counts = [int((e.get("tags") or {}).get("total", 0)) for e in els if e.get("type") == "count"]
    out = dict(zip(PLACE_KEYS[season], counts))
    best = None
    for e in els:
        if e.get("type") == "count":
            continue
        c = e.get("center") or ({"lat": e["lat"], "lon": e["lon"]} if "lat" in e else None)
        if not c:
            continue
        tags = e.get("tags") or {}
        if _NOT_HOSPITAL.search(" ".join(str(tags.get(k, "")) for k in ("name", "name:en", "emergency", "healthcare"))):
            continue
        d = haversine_km((lat, lng), (c["lat"], c["lon"]))
        if best is None or d < best[0]:
            best = (d, tags.get("name:en") or tags.get("name") or "hospital")
    out["hospital_km"] = round(best[0], 1) if best else None
    out["hospital_name"] = best[1] if best else None
    return out


# ----------------------------------------------------------------------------- cache ---

def load_cache(path: Path = CACHE_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("areas"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "attribution": ATTRIBUTION, "areas": {}}


def save_cache(cache: dict, path: Path = CACHE_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _fresh(entry: dict | None, part: str, a: dict, today: date) -> bool:
    if not entry or part not in entry or not entry.get(f"{part}_fetched"):
        return False
    if haversine_km((entry["lat"], entry["lng"]), (a["lat"], a["lng"])) > 1.0:   # area point moved
        return False
    age = (today - datetime.fromisoformat(entry[f"{part}_fetched"]).date()).days
    return 0 <= age < MAX_AGE_DAYS


# ---------------------------------------------------------------------------- update ---

def update(items: list[dict], cfg: dict, today: date, offline: bool = False,
           fetch: Fetch | None = None, path: Path = CACHE_PATH) -> dict[str, dict]:
    """Fill / refresh the cache for every area in `items`; return {area_key: area_info}.
    Offline (or budget used up / API down): whatever the cache holds is returned."""
    c = {**DEFAULTS, **(cfg.get("conditions") or {})}
    cache = load_cache(path)
    areas = areas_from_items(items)
    store = cache["areas"]
    if not offline and c["enabled"]:
        fetch = fetch or Client(c["max_requests"])
        try:
            for season in ("summer", "winter"):
                todo = [a for a in areas.values() if a["season"] == season and not _fresh(store.get(a["key"]), "climate", a, today)]
                if todo:
                    try:
                        got = fetch_climate(todo, season, today, fetch, c["years"])
                    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
                        log.warning("conditions: %s climate lookup failed: %s", season, e)
                        got = {}
                    for k, months in got.items():
                        a = areas[k]
                        store[k] = {**store.get(k, {}), **{x: a[x] for x in ("name", "season", "lat", "lng")},
                                    "climate": months, "climate_fetched": today.isoformat()}
                    save_cache(cache, path)
            done: list[tuple[dict, dict]] = []      # (area, places) fetched this run, for sharing
            for a in areas.values():
                if _fresh(store.get(a["key"]), "places", a, today):
                    continue
                near = next((p for b, p in done if b["season"] == a["season"]
                             and haversine_km((a["lat"], a["lng"]), (b["lat"], b["lng"])) <= SHARE_POINT_KM), None)
                if near is None:
                    q = overpass_query(a["lat"], a["lng"], a["season"], c["places_radius_m"], c["ski_radius_m"],
                                       c["hospital_radius_m"])
                    try:
                        near = summarize_places(fetch(c["overpass_url"], None, q), a["lat"], a["lng"], a["season"])
                    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                        log.warning("conditions: Overpass failed for %s: %s", a["name"], e)
                        continue
                    done.append((a, near))
                store[a["key"]] = {**store.get(a["key"], {}), **{x: a[x] for x in ("name", "season", "lat", "lng")},
                                   "places": near, "places_fetched": today.isoformat()}
                save_cache(cache, path)
        except Budget as e:
            log.warning("conditions: request budget reached (%s); the rest next run", e)
        finally:
            save_cache(cache, path)
        log.info("conditions: %d areas, %d live requests", len(areas),
                 getattr(fetch, "made", 0))
    return {k: store[k] for k in areas if k in store}


def info_for(entry: dict | None, check_in: str | None) -> dict | None:
    """What the dashboard needs for one offer: the trip month's climate + nearby places."""
    if not entry:
        return None
    month = (check_in or "")[5:7]
    clim = (entry.get("climate") or {}).get(month)
    out = {"area": entry.get("name"), "month": month or None, **(clim or {}),
           **(entry.get("places") or {})}
    out["toddler_flags"] = flags(entry.get("season"), clim, entry.get("places"))
    return out


def flags(season: str | None, clim: dict | None, places: dict | None) -> list[str]:
    """Short plain-language badges, good and bad."""
    f, clim, places = [], clim or {}, places or {}
    if season == "summer":
        if clim.get("sea_ok") is True:
            f.append(f"sea {clim['sea_c']:.0f}°C: warm for toddlers")
        elif clim.get("sea_ok") is False:
            f.append(f"sea {clim['sea_c']:.0f}°C: cool for toddlers")
        if (clim.get("air_max_c") or 0) >= 33:
            f.append(f"hot ({clim['air_max_c']:.0f}°C afternoons)")
    else:
        # No snow-reliability flag: reanalysis snow depth at the town grid cell reads far below the
        # pistes (Kopaonik January ~13 cm), so it would wrongly flag every resort. Shown as data only.
        if clim.get("air_max_c") is not None and clim["air_max_c"] <= 0:
            f.append(f"below freezing all day ({clim['air_max_c']:.0f}°C max)")
        if places.get("magic_carpets"):
            f.append("magic carpet (kids' ski lift) nearby")
    h = places.get("hospital_km")
    if h is not None and h > 25:
        f.append(f"hospital {h:.0f} km away")
    return f


def attach(items: list[dict], info: dict[str, dict]) -> int:
    """Set item['area_info'] in place; returns how many items got one."""
    n = 0
    for it in items:
        ai = info_for(info.get(area_key(it.get("season", ""), it.get("area") or "")), it.get("check_in"))
        it["area_info"] = ai
        n += ai is not None
    return n


if __name__ == "__main__":         # python -m trips.conditions [--offline]: refresh from docs/data.json and print
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data = json.loads(Path("docs/data.json").read_text(encoding="utf-8"))
    from .run import load_config
    res = update(data["items"], load_config(), date.today(), offline="--offline" in sys.argv)
    print(json.dumps(res, ensure_ascii=False, indent=1))
