"""Guest ratings per hotel, for the family's rule: never show a hotel rated below 4.3 / 5 on Google
(or any 5-point site) or 8.2 / 10 on Booking (or any 10-point site).

Ratings come from:
1. what a source itself states (a hotel dict may already carry family["ratings"]);
2. the official Google Places API (Text Search, "New"), which returns a place's rating and review count
   and allows showing them. It needs an API key: put `google_api_key = "..."` under [ratings] in the
   git-ignored config.local.toml, or set GOOGLE_PLACES_API_KEY. Without a key this step is skipped.

Results are cached in data/ratings_cache.json (misses too) and refreshed every `refresh_days`; each run
looks up at most `budget` hotels. A Google answer counts only when its name matches the hotel and it
lies within `max_km` of the hotel's pin.

Each rating is {"source": "Google", "score": 4.6, "scale": 5, "count": 812}.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = "places.displayName,places.rating,places.userRatingCount,places.location,places.id"
USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner)"
DEFAULTS = {"min_5": 4.3, "min_10": 8.2, "min_reviews": 10, "budget": 50, "refresh_days": 60,
            "max_km": 15, "cache": "data/ratings_cache.json", "enabled": True}
_STOP = {"hotel", "hotels", "apart", "aparthotel", "apartments", "apartment", "apartmani", "resort", "spa",
         "and", "the", "by", "villa", "villas", "suites", "suite", "beach", "boutique", "club", "studios"}


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("ratings") or {})}


def threshold(scale: float, st: dict) -> float:
    """Minimum score on a given scale: 4.3 on 5-point sites, 8.2 on 10-point sites, the same share otherwise."""
    if abs(scale - 5) < 1e-9:
        return st["min_5"]
    if abs(scale - 10) < 1e-9:
        return st["min_10"]
    return scale * st["min_10"] / 10


def verdict(ratings: list[dict], st: dict) -> tuple[bool | None, str]:
    """(passes, reason). None = no credible rating known yet. A hotel fails when ANY credible rating
    (enough reviews) is below its site's threshold."""
    good = [r for r in ratings or [] if r.get("score") is not None and r.get("scale")
            and (r.get("count") is None or r["count"] >= st["min_reviews"])]
    if not good:
        return None, "Guest rating not known yet"
    low = [r for r in good if r["score"] < threshold(r["scale"], st)]
    if low:
        r = low[0]
        return False, f"Rated {r['score']:g}/{r['scale']:g} on {r['source']} (our rule: {threshold(r['scale'], st):g}+)"
    best = max(good, key=lambda r: r["score"] / r["scale"])
    n = f" from {best['count']:,} reviews" if best.get("count") else ""
    return True, f"Rated {best['score']:g}/{best['scale']:g} on {best['source']}{n}"


def _norm(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return {w for w in re.findall(r"[a-z0-9]+", s) if w not in _STOP and len(w) > 1}


def _km(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(x))


def match(hotel: dict, place: dict, st: dict) -> bool:
    a, b = _norm(hotel.get("name", "")), _norm((place.get("displayName") or {}).get("text", ""))
    if not a or not b or len(a & b) / min(len(a), len(b)) < 0.67:
        return False
    loc = place.get("location") or {}
    if hotel.get("lat") is None or "latitude" not in loc:
        return True
    return _km((hotel["lat"], hotel["lng"]), (loc["latitude"], loc["longitude"])) <= st["max_km"]


def _key(cfg: dict) -> str:
    return (os.environ.get("GOOGLE_PLACES_API_KEY") or (cfg.get("ratings") or {}).get("google_api_key") or "").strip()


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def lookup_google(hotel: dict, key: str, st: dict, post=None) -> dict | None:
    post = post or requests.post
    body = {"textQuery": f"{hotel['name']}, {hotel.get('area', '')}", "maxResultCount": 5}
    if hotel.get("lat") is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": hotel["lat"], "longitude": hotel["lng"]},
                                           "radius": st["max_km"] * 1000.0}}
    r = post(PLACES_URL, json=body, timeout=30,
             headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELDS, "User-Agent": USER_AGENT})
    r.raise_for_status()
    for p in r.json().get("places", []):
        if match(hotel, p, st) and p.get("rating") is not None:
            return {"source": "Google", "score": float(p["rating"]), "scale": 5, "count": p.get("userRatingCount"),
                    "place_id": p.get("id")}
    return None


def apply(hotels: dict[str, dict], cfg: dict, today: date, offline: bool = False, post=None) -> dict:
    """Attach cached / looked-up Google ratings to hotel["family"]["ratings"]. Returns run stats."""
    st = settings(cfg)
    stats = {"looked_up": 0, "found": 0, "from_cache": 0, "skipped_no_key": False}
    if not st["enabled"]:
        return stats
    path = Path(st["cache"])
    cache = _load(path)
    key = _key(cfg)
    stats["skipped_no_key"] = not key
    fresh_after = (today - timedelta(days=st["refresh_days"])).isoformat()
    todo = []
    for hid, h in hotels.items():
        c = cache.get(hid)
        if c and c.get("rating"):
            _attach(h, c["rating"])
            stats["from_cache"] += 1
        if not c or c.get("checked", "") < fresh_after:
            todo.append(hid)
    if key and not offline:
        for hid in todo[: st["budget"]]:
            h = hotels[hid]
            try:
                rating = lookup_google(h, key, st, post)
            except (requests.RequestException, ValueError, KeyError) as e:
                log.warning("ratings: Google lookup failed for %s: %s", h.get("name"), e)
                break                                  # quota / key problem: stop for this run
            stats["looked_up"] += 1
            cache[hid] = {"checked": today.isoformat(), "rating": rating}
            if rating:
                stats["found"] += 1
                _attach(h, rating)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("ratings: %d looked up (%d found), %d from cache%s", stats["looked_up"], stats["found"],
             stats["from_cache"], " — no Google key, lookups skipped" if not key else "")
    return stats


def _attach(hotel: dict, rating: dict) -> None:
    fam = hotel.setdefault("family", {"verified": []})
    rs = [r for r in fam.get("ratings", []) if r.get("source") != rating["source"]]
    fam["ratings"] = rs + [rating]
