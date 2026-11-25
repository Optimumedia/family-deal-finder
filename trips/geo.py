"""Drive time from Skopje with the free public OSRM router, cached per hotel.

One request for all uncached hotels (OSRM "table" service), honest User-Agent,
results stored in trips.db so each hotel is looked up once. Routers ignore
border queues, so the config's border buffer is added on top.
"""
from __future__ import annotations

import logging

import requests

from . import db

log = logging.getLogger(__name__)
TABLE_URL = "https://router.project-osrm.org/table/v1/driving/"
USER_AGENT = "family-deal-finder/0.1 (personal, low-volume trip planner)"


def drive_minutes(con, hotels: dict[str, dict], home: tuple[float, float]) -> dict[str, float | None]:
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
    if todo:
        coords = [f"{home[1]},{home[0]}"] + [f"{hotels[h]['lng']},{hotels[h]['lat']}" for h in todo]
        url = TABLE_URL + ";".join(coords) + "?sources=0&annotations=duration"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            r.raise_for_status()
            durations = r.json()["durations"][0][1:]
            for hid, sec in zip(todo, durations):
                if sec is not None:
                    minutes = round(sec / 60)
                    db.save_drive(con, hid, hotels[hid]["lat"], hotels[hid]["lng"], minutes)
                    out[hid] = minutes
        except (requests.RequestException, KeyError, ValueError) as e:
            log.warning("drive time lookup failed, will retry next run: %s", e)
    return out
