"""Drive time from Skopje, cached per hotel.

1. The free public OSRM router: one "table" request for all uncached hotels, honest User-Agent.
2. If OSRM fails and an openrouteservice key is set (free plan; env ORS_API_KEY), its matrix
   service is asked instead. Both are real road routes and are cached in trips.db.
3. If both fail, a straight-line estimate (haversine km x ESTIMATE_MIN_PER_KM) is used for this
   run only. It is never cached, so the router is tried again next run, and the hotel id is put
   in `last_estimated` so the dashboard can mark the time as an estimate.

Routers ignore border queues, so the config's border buffer is added on top (in score.py).
"""
from __future__ import annotations

import logging
import math
import os

import requests

from . import db

log = logging.getLogger(__name__)
TABLE_URL = "https://router.project-osrm.org/table/v1/driving/"
ORS_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner)"
# Minutes of driving per straight-line km from Skopje. Calibrated on the cached OSRM times
# (25.11.2026): 0.96 on the Thessaloniki motorway, 1.3 to Bansko, 1.44 to Pamporovo.
ESTIMATE_MIN_PER_KM = 1.2

# Hotel ids whose time in the last drive_minutes() result is a straight-line estimate.
last_estimated: set[str] = set()


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lng1), (lat2, lng2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def estimate_minutes(home: tuple[float, float], lat: float, lng: float) -> float:
    return round(haversine_km(home, (lat, lng)) * ESTIMATE_MIN_PER_KM)


def _osrm(home, points) -> list[float | None]:
    coords = [f"{home[1]},{home[0]}"] + [f"{lng},{lat}" for lat, lng in points]
    url = TABLE_URL + ";".join(coords) + "?sources=0&annotations=duration"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.json()["durations"][0][1:]


def _ors(home, points, key: str) -> list[float | None]:
    body = {"locations": [[home[1], home[0]]] + [[lng, lat] for lat, lng in points],
            "sources": [0], "metrics": ["duration"]}
    r = requests.post(ORS_URL, json=body, timeout=30,
                      headers={"User-Agent": USER_AGENT, "Authorization": key})
    r.raise_for_status()
    return r.json()["durations"][0][1:]


def drive_minutes(con, hotels: dict[str, dict], home: tuple[float, float]) -> dict[str, float | None]:
    last_estimated.clear()
    out: dict[str, float | None] = {}
    todo = []
    for hid, h in hotels.items():
        if h.get("lat") is None or h.get("lng") is None:
            out[hid] = None
            continue
        m = db.cached_drive(con, hid, h["lat"], h["lng"])
        if m is None:
            todo.append(hid)
        out[hid] = m
    if not todo:
        return out
    points = [(hotels[h]["lat"], hotels[h]["lng"]) for h in todo]
    routers = [("OSRM", lambda: _osrm(home, points))]
    key = os.environ.get("ORS_API_KEY", "").strip()
    if key:
        routers.append(("openrouteservice", lambda: _ors(home, points, key)))
    for name, ask in routers:
        try:
            durations = ask()
        except (requests.RequestException, KeyError, ValueError, IndexError, TypeError) as e:
            log.warning("drive time lookup via %s failed: %s", name, e)
            continue
        for hid, sec in zip(todo, durations):
            if sec is not None:
                minutes = round(sec / 60)
                db.save_drive(con, hid, hotels[hid]["lat"], hotels[hid]["lng"], minutes)
                out[hid] = minutes
        break
    missing = [hid for hid in todo if out[hid] is None]
    for hid in missing:
        out[hid] = estimate_minutes(home, hotels[hid]["lat"], hotels[hid]["lng"])
        last_estimated.add(hid)
    if missing:
        log.warning("drive time estimated from straight-line distance for %d hotel(s); router retried next run",
                    len(missing))
    return out
