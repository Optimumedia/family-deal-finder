"""Hotel-level coordinates for auto-found hotels, from OpenStreetMap.

Agency sources only know the resort (every Bansko hotel gets the config page's Bansko point),
so the map stacks them in one pin and drive times are per resort. This module looks each such
hotel up by name, inside a box around its resort point, and moves it to the hotel's own spot.

1. Nominatim (OSMF public instance): the cleaned hotel name, `bounded` to a viewbox around the
   resort point and limited to the hotel's country, so a result can never jump to another
   country or another resort.
2. Photon (komoot) as the fallback: "name town", same box, for the spellings Nominatim misses.

A result is accepted only if it is a hotel/apartment-type OSM object (tourism=hotel, apartment,
guest_house, chalet... or building=hotel/apartments), lies within `max_km` of the resort point,
and its name really matches the hotel's name (transliterated from Cyrillic/Greek when needed).

Usage policy (https://operations.osmfoundation.org/policies/nominatim/): honest User-Agent,
at most 1 request/second (we wait `delay_seconds`, default 5, per host), every answer cached
permanently in data/geocode_cache.json, misses too (a miss is retried after `retry_miss_days`),
and at most `budget` live requests per run. A 429/403 stops that host for the run.

Optional: Overpass natural=beach within 300 m of a summer hit gives a beach distance estimate
(geo.beach_m, flagged as an estimate; copied into family.beach_m only with fill_beach_m = true).

Only hotels still sitting on a config page's resort point are looked up. Hand-curated hotels and
sources with their own per-hotel pins (Savana) are never touched.
"""
from __future__ import annotations

import difflib
import json
import logging
import math
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import requests

log = logging.getLogger(__name__)

USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner; geocodes ~40 hotels/run, cached)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

DEFAULTS = {
    "enabled": True,
    "budget": 40,               # live requests per run, all hosts together
    "delay_seconds": 5.0,       # per host; Nominatim's policy minimum is 1 s
    "max_km": 15.0,             # accepted distance from the resort point
    "area_km": {},              # wider radius for region-wide pages, e.g. {"Kassandra" = 30}
    "retry_miss_days": 30,
    "cache": "data/geocode_cache.json",
    "photon": True,
    "kinds": ["hotel", "apartment"],   # owner villas are rarely in OSM under their marketing name
    "beach": False,             # Overpass natural=beach within beach_radius_m (summer hits only)
    "beach_radius_m": 300,
    "fill_beach_m": False,      # copy the estimate into family.beach_m when that is unknown
}

OK_TYPES = {
    "tourism": {"hotel", "apartment", "apartments", "guest_house", "chalet", "motel", "hostel"},
    "building": {"hotel", "apartments"},
    "leisure": {"resort"},
}

# Words that say what a place is, not which one it is.
GENERIC = {
    "hotel", "hotels", "hotelt", "apart", "aparthotel", "aparthotels", "apartment", "apartments", "apartmani",
    "apartman", "apartament", "apartamenti", "resort", "spa", "and", "by", "the", "ex", "holiday", "boutique",
    "residence", "residences", "complex", "club", "family", "studios", "studio", "suites", "rooms", "villa",
    "vila", "vile", "villas", "house", "guest", "guesthouse", "lux", "luxury", "deluxe", "wellness", "&", "de",
    "kompleks", "hotel-", "hoteli", "xotel", "otel", "mountain", "lodge", "chalet", "inn", "kuca", "sobe",
}

_CYR = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюяђјљњћџѓќѕ",
                ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                 "u", "f", "h", "ts", "ch", "sh", "sht", "a", "", "yu", "ya", "dj", "j", "lj", "nj", "c", "dz",
                 "gj", "kj", "dz"]))
_GRK = dict(zip("αβγδεζηθικλμνξοπρσςτυφχψωάέήίόύώϊϋΐΰ",
                ["a", "v", "g", "d", "e", "z", "i", "th", "i", "k", "l", "m", "n", "x", "o", "p", "r", "s", "s",
                 "t", "i", "f", "ch", "ps", "o", "a", "e", "i", "i", "o", "i", "o", "i", "i", "i", "i"]))


# ----------------------------------------------------------------- names ---

def latin(s: str) -> str:
    """Lower-case ASCII: Cyrillic and Greek transliterated, accents dropped."""
    s = "".join(_CYR.get(c, _GRK.get(c, c)) for c in (s or "").lower())
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def clean_name(name: str) -> str:
    """The searchable part of an agency's hotel name: no unit after a dash, no stars, no brackets."""
    n = re.split(r"\s[–—-]\s|\s\|\s", name or "", maxsplit=1)[0]
    n = re.sub(r"\(.*?\)|\d\s*\*+|\*+|\b\d\s*(stars?|zvezdice)\b", " ", n, flags=re.I)
    return " ".join(n.split()).strip(" ,.-")


def town_of(area: str) -> str:
    """First part of "Nea Skioni, Kassandra, Halkidiki" → "Nea Skioni" (brackets dropped)."""
    first = (area or "").split(",")[0]
    return " ".join(re.sub(r"\(.*?\)|\(.*$", " ", first).split()).split(" / ")[0].strip()


def tokens(s: str, drop: set[str] = frozenset()) -> list[str]:
    words = re.findall(r"[a-z0-9]+", latin(s))
    return [w for w in words if w not in GENERIC and w not in drop and len(w) >= 2]


def _same(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.8)


def name_matches(hotel_name: str, osm_names: list[str], place_words: set[str] = frozenset()) -> bool:
    """Distinctive words (generic and place words dropped) overlap both ways: at least half of the
    hotel's words are in the OSM name and more than half of the OSM name's words are in the
    hotel's. So "Bansko" alone never matches, and "Grand (Hotel Bansko)" is not "Grand Royale"."""
    name = clean_name(hotel_name)
    for on in osm_names:
        want, have = tokens(name, place_words), tokens(on, place_words)
        if not want or not have:                       # e.g. "Hotel Bansko": compare with place words kept
            want, have = tokens(name), tokens(on)
        if not want or not have:
            continue
        a = sum(any(_same(w, h) for h in have) for w in want)
        b = sum(any(_same(h, w) for w in want) for h in have)
        if a >= 1 and a / len(want) >= 0.5 and b / len(have) > 0.5:
            return True
    return False


# --------------------------------------------------------------- geometry ---

def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lng1), (lat2, lng2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lng, min_lat, max_lng, max_lat) around a point."""
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return lng - dlng, lat - dlat, lng + dlng, lat + dlat


def _seg_m(p, a, b) -> float:
    """Metres from point p to segment a-b (equirectangular, fine at 300 m)."""
    k = math.cos(math.radians(p[0]))
    ax, ay = (a[1] - p[1]) * k * 111320, (a[0] - p[0]) * 110540
    bx, by = (b[1] - p[1]) * k * 111320, (b[0] - p[0]) * 110540
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


def beach_distance(point: tuple[float, float], overpass: dict) -> tuple[int | None, str | None]:
    """Nearest natural=beach (metres, rounded to 10) and its surface tag, from an Overpass
    `out geom` answer. Polygons and lines use their outline, nodes their point."""
    best, surface = None, None
    for el in overpass.get("elements", []):
        geoms = []
        if el.get("geometry"):
            geoms.append([(g["lat"], g["lon"]) for g in el["geometry"]])
        for m in el.get("members", []) or []:
            if m.get("geometry"):
                geoms.append([(g["lat"], g["lon"]) for g in m["geometry"]])
        if el.get("type") == "node" and "lat" in el:
            geoms.append([(el["lat"], el["lon"])])
        for line in geoms:
            pairs = list(zip(line, line[1:])) or [(line[0], line[0])]
            d = min(_seg_m(point, a, b) for a, b in pairs)
            if best is None or d < best:
                best, surface = d, (el.get("tags") or {}).get("surface")
    return (None if best is None else int(round(best / 10.0) * 10)), surface


# ------------------------------------------------------------- providers ---

def _candidates_nominatim(data) -> list[dict]:
    out = []
    for r in data if isinstance(data, list) else []:
        nd = r.get("namedetails") or {}
        names = [r.get("name") or ""] + [v for k, v in nd.items() if k.startswith(("name", "alt_name", "old_name",
                                                                                  "official_name", "brand"))]
        out.append({"lat": float(r["lat"]), "lng": float(r["lon"]), "cls": r.get("category") or r.get("class"),
                    "type": r.get("type"), "names": [n for n in names if n],
                    "osm": f"{r.get('osm_type')}/{r.get('osm_id')}", "label": r.get("display_name", "")[:120]})
    return out


def _candidates_photon(data) -> list[dict]:
    out = []
    for f in (data or {}).get("features", []):
        p, g = f.get("properties", {}), f.get("geometry", {}).get("coordinates") or [None, None]
        if g[0] is None:
            continue
        t = {"N": "node", "W": "way", "R": "relation"}.get(p.get("osm_type"), p.get("osm_type"))
        out.append({"lat": float(g[1]), "lng": float(g[0]), "cls": p.get("osm_key"), "type": p.get("osm_value"),
                    "names": [p.get("name") or ""], "osm": f"{t}/{p.get('osm_id')}",
                    "label": ", ".join(x for x in (p.get("name"), p.get("city") or p.get("locality"),
                                                   p.get("country")) if x)[:120]})
    return out


def pick(cands: list[dict], hotel: dict, center: tuple[float, float], max_km: float) -> dict | None:
    """First candidate (provider rank order) that is a hotel-type object, near the resort, same name."""
    place = set(tokens(hotel.get("area", ""))) | set(tokens(hotel.get("country", "")))
    for c in cands:
        if c["type"] not in OK_TYPES.get(c["cls"], ()):
            continue
        d = km(center, (c["lat"], c["lng"]))
        if d > max_km:
            continue
        if not name_matches(hotel["name"], c["names"], place):
            continue
        return {**c, "dist_km": round(d, 2)}
    return None


# --------------------------------------------------------------- geocoder ---

class Geocoder:
    """Cache + budget + per-host politeness. `session` needs requests-like get/post (tests pass a fake)."""

    def __init__(self, cfg: dict | None = None, session=None, today: date | None = None, offline: bool = False):
        self.c = {**DEFAULTS, **(cfg or {})}
        self.today = today or date.today()
        self.offline = offline
        self.s = session
        self.path = Path(self.c["cache"])
        self.cache = self._load()
        self.requests_made = 0
        self.stopped: set[str] = set()       # hosts that answered 429/403: left alone for this run
        self._last: dict[str, float] = {}
        self.stats = {"looked_up": 0, "hit": 0, "miss": 0, "cached_hit": 0, "cached_miss": 0, "moved": 0,
                      "skipped_budget": 0, "beach": 0, "errors": 0}

    # cache -------------------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data.get("entries", {}) if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "entries": self.cache}, ensure_ascii=False, indent=1, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def key(hotel: dict, center: tuple[float, float]) -> str:
        return f"{hotel['id']}@{center[0]:.4f},{center[1]:.4f}"

    def _fresh_miss(self, e: dict) -> bool:
        try:
            return (self.today - date.fromisoformat(e["checked"])).days < int(self.c["retry_miss_days"])
        except (KeyError, ValueError):
            return False

    # http --------------------------------------------------------------
    def _can(self, host: str) -> bool:
        return not self.offline and self.s is not None and host not in self.stopped \
            and self.requests_made < int(self.c["budget"])

    def _call(self, host: str, method: str, url: str, **kw):
        last = self._last.get(host)
        if last is not None:
            pause = float(self.c["delay_seconds"]) - (time.monotonic() - last)
            if pause > 0:
                time.sleep(pause)
        self._last[host] = time.monotonic()
        self.requests_made += 1
        try:
            r = getattr(self.s, method)(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
                                        timeout=30, **kw)
        except requests.RequestException as e:
            log.warning("geocode: %s failed: %s", host, e)
            self.stats["errors"] += 1
            return None
        if r.status_code in (403, 429):
            log.warning("geocode: %s answered %s, leaving it alone for this run", host, r.status_code)
            self.stopped.add(host)
            self.stats["errors"] += 1
            return None
        if r.status_code != 200:
            self.stats["errors"] += 1
            return None
        try:
            return r.json()
        except ValueError:
            self.stats["errors"] += 1
            return None

    def _nominatim(self, hotel, center, radius):
        if not self._can("nominatim"):
            return None
        b = box(*center, radius)
        params = {"q": clean_name(hotel["name"]), "format": "jsonv2", "limit": 6, "bounded": 1,
                  "viewbox": ",".join(f"{x:.5f}" for x in b), "namedetails": 1, "accept-language": "en"}
        if hotel.get("country"):
            params["countrycodes"] = hotel["country"].lower()
        data = self._call("nominatim", "get", NOMINATIM_URL, params=params)
        return None if data is None else _candidates_nominatim(data)

    def _photon(self, hotel, center, radius):
        if not self.c["photon"] or not self._can("photon"):
            return None
        b = box(*center, radius)
        q = " ".join(x for x in (clean_name(hotel["name"]), town_of(hotel.get("area", ""))) if x)
        params = {"q": q, "lat": center[0], "lon": center[1], "limit": 8, "lang": "en",
                  "bbox": ",".join(f"{x:.5f}" for x in b)}
        data = self._call("photon", "get", PHOTON_URL, params=params)
        return None if data is None else _candidates_photon(data)

    def _beach(self, lat, lng):
        if not self._can("overpass"):
            return None
        r = int(self.c["beach_radius_m"])
        q = (f'[out:json][timeout:25];(way["natural"="beach"](around:{r},{lat},{lng});'
             f'relation["natural"="beach"](around:{r},{lat},{lng});'
             f'node["natural"="beach"](around:{r},{lat},{lng}););out geom;')
        return self._call("overpass", "post", OVERPASS_URL, data={"data": q})

    # lookup ------------------------------------------------------------
    def radius(self, hotel: dict) -> float:
        area = hotel.get("area", "")
        wide = [float(v) for k, v in (self.c.get("area_km") or {}).items() if k.lower() in area.lower()]
        return max([float(self.c["max_km"])] + wide)

    def lookup(self, hotel: dict, center: tuple[float, float]) -> dict | None:
        """Cache entry for this hotel at this resort point, fetching it if needed and allowed.
        None = not known yet (offline, budget spent or a host failed): try again next run."""
        k = self.key(hotel, center)
        e = self.cache.get(k)
        if e and (e["status"] == "hit" or self._fresh_miss(e)):
            self.stats["cached_hit" if e["status"] == "hit" else "cached_miss"] += 1
            return e
        if not (self._can("nominatim") or (self.c["photon"] and self._can("photon"))):
            self.stats["skipped_budget"] += 1
            return None
        radius = self.radius(hotel)
        self.stats["looked_up"] += 1
        got, tried_ok, near = None, False, []
        for via, ask in (("nominatim", self._nominatim), ("photon", self._photon)):
            cands = ask(hotel, center, radius)
            if cands is None:
                continue
            tried_ok = True
            got = pick(cands, hotel, center, radius)
            if got:
                got["via"] = via
                break
            near += [{"via": via, "name": (c["names"] or [""])[0], "osm_type": f"{c['cls']}={c['type']}",
                      "km": round(km(center, (c["lat"], c["lng"])), 1)} for c in cands[:3]]
        if not tried_ok:
            return None                     # nothing answered: no cache entry, retried next run
        today = self.today.isoformat()
        if got:
            e = {"status": "hit", "lat": round(got["lat"], 6), "lng": round(got["lng"], 6), "via": got["via"],
                 "osm": got["osm"], "osm_type": f"{got['cls']}={got['type']}", "osm_name": got["names"][0],
                 "label": got["label"], "dist_km": got["dist_km"], "checked": today, "name": hotel["name"]}
            self.stats["hit"] += 1
        else:
            e = {"status": "miss", "checked": today, "name": hotel["name"]}
            if near:
                e["rejected"] = near            # what the providers offered instead, for debugging
            self.stats["miss"] += 1
        self.cache[k] = e
        return e

    def beach(self, e: dict) -> dict | None:
        """Overpass beach estimate for a hit, cached inside the entry."""
        if "beach" in e:
            return e["beach"]
        data = self._beach(e["lat"], e["lng"])
        if data is None:
            return None
        m, surface = beach_distance((e["lat"], e["lng"]), data)
        e["beach"] = {"m": m, "surface": surface, "radius_m": int(self.c["beach_radius_m"]),
                      "checked": self.today.isoformat()}
        self.stats["beach"] += 1
        return e["beach"]


def resort_points(cfg: dict) -> set[tuple[float, float]]:
    """Every lat/lng a source page in config.toml gives its hotels (rounded to 4 decimals)."""
    pts: set[tuple[float, float]] = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("lat"), (int, float)) and isinstance(x.get("lng"), (int, float)):
                pts.add((round(float(x["lat"]), 4), round(float(x["lng"]), 4)))
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(cfg.get("sources", {}))
    return pts


def apply(hotels: dict[str, dict], cfg: dict, today: date | None = None, offline: bool = False,
          session=None, skip: set[str] = frozenset()) -> dict:
    """Move hotels that sit on a resort point to their own OSM spot (in place). Sets
    hotel["geo"] = {"via", "osm", "resort_km", "resort": [lat, lng], ...} on moved hotels.
    offline=True uses the cache only. Returns stats for the run log / health report."""
    if not isinstance(cfg.get("geocode"), dict):          # no [geocode] block: off (tests, old configs)
        return {"enabled": False}
    gc_cfg = {**DEFAULTS, **cfg["geocode"]}
    if not gc_cfg["enabled"]:
        return {"enabled": False}
    if session is None and not offline:
        session = requests.Session()
    g = Geocoder(gc_cfg, session=session, today=today, offline=offline)
    pts = resort_points(cfg)
    kinds = set(gc_cfg["kinds"])
    try:
        for hid, h in hotels.items():
            if hid in skip or h.get("lat") is None or h.get("lng") is None:
                continue
            center = (round(float(h["lat"]), 4), round(float(h["lng"]), 4))
            if center not in pts or h.get("kind", "hotel") not in kinds:
                continue
            e = g.lookup(h, center)
            if not e or e["status"] != "hit":
                continue
            h["lat"], h["lng"] = e["lat"], e["lng"]
            h["geo"] = {"via": e["via"], "osm": e["osm"], "resort_km": e["dist_km"], "resort": list(center)}
            g.stats["moved"] += 1
            if gc_cfg["beach"] and h.get("season") == "summer":
                b = g.beach(e)
                if b and b["m"] is not None:
                    h["geo"]["beach_m"] = b["m"]          # an estimate from OSM, not a stated fact
                    h["geo"]["beach_surface"] = b["surface"]
                    fam = h.setdefault("family", {"verified": []})
                    if gc_cfg["fill_beach_m"] and fam.get("beach_m") is None:
                        fam["beach_m"] = b["m"]
                        fam["beach_m_estimate"] = True
    finally:
        if not offline:
            g.save()
    g.stats["requests"] = g.requests_made
    if g.stats["looked_up"] or g.stats["skipped_budget"]:
        log.info("geocode: %(moved)d hotels on their own pin; %(hit)d new hits, %(miss)d misses, "
                 "%(requests)d requests, %(skipped_budget)d left for next run", g.stats)
    return g.stats
