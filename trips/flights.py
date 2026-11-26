"""Direct flights from Skopje (SKP): mark hotels a family can fly to and then transfer from.

Summer rule (owner, 26.11.2026): a package is not required. A hotel-only price is fine as long
as a DIRECT flight from SKP lands at an airport near the hotel; the parents book the flight
themselves. This module turns a config list of routes into `direct_flight_skp = True` plus a
`flight` note on each hotel that lies close enough to a route's airport, in a month the route
flies.

Config (config.toml):

    [flights]
    enabled = true
    max_transfer_km = 90          # default straight-line km from the airport to the hotel
    seasons = ["summer"]          # hotel seasons this applies to
    trip_months = [6, 7, 8, 9]    # used when a hotel has no offer dates

    [[flights.routes]]
    airport = "AYT"
    name = "Antalya"
    lat = 36.90
    lng = 30.80
    months = [4, 5, 6, 7, 8, 9, 10]
    frequency = "daily"
    max_transfer_km = 130         # per-airport override (Alanya is ~120 km from AYT)
    confidence = "confirmed"      # confirmed | likely | possible
    evidence = "https://..."

`apply(hotels, cfg, offers=None)`:
- `hotels` is the {id: hotel} dict from db.hotels() (a list of hotel dicts works too);
- the trip months of a hotel are the check-in months of its offers when `offers` is given
  (offer dicts with `hotel_id` or `hotel`, and `check_in`), else `trip_months`;
- a hotel is marked when at least one trip month is flown by a route whose airport is within
  that route's `max_transfer_km`. The nearest such airport is kept;
- `flight = {"airport", "name", "transfer_km", "months", "frequency", "confidence", "evidence"}`
  where `months` are the trip months that route covers;
- routes with `confidence = "possible"` are ignored unless `min_confidence = "possible"`;
- a hotel a source already marked direct (e.g. a Savana flight package) stays direct;
  `apply` never sets the flag to False.

Distances are straight-line (haversine): a road transfer is usually 1.2–1.4× longer.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

from .geo import haversine_km

log = logging.getLogger(__name__)

_CONF_RANK = {"confirmed": 3, "likely": 2, "possible": 1}


def settings(cfg: dict) -> dict:
    return cfg.get("flights", {}) or {}


def routes(cfg: dict) -> list[dict]:
    """The configured routes that pass `min_confidence` (default "likely")."""
    fl = settings(cfg)
    floor = _CONF_RANK.get(str(fl.get("min_confidence", "likely")).lower(), 2)
    default_km = float(fl.get("max_transfer_km", 90))
    out = []
    for r in fl.get("routes", []) or []:
        if _CONF_RANK.get(str(r.get("confidence", "likely")).lower(), 2) < floor:
            continue
        if r.get("lat") is None or r.get("lng") is None:
            continue
        out.append({**r, "max_transfer_km": float(r.get("max_transfer_km", default_km)),
                    "months": [int(m) for m in r.get("months", range(1, 13))]})
    return out


def _month(check_in) -> int | None:
    s = str(check_in or "")
    try:
        return int(s[5:7]) if len(s) >= 7 else None
    except ValueError:
        return None


def trip_months(offers: Iterable[dict] | None) -> dict[str, set[int]]:
    """hotel id -> the set of check-in months of its offers."""
    out: dict[str, set[int]] = defaultdict(set)
    for o in offers or []:
        hid = o.get("hotel_id") or o.get("hotel")
        m = _month(o.get("check_in"))
        if hid and m:
            out[hid].add(m)
    return out


def nearest(lat: float, lng: float, months: set[int], rts: list[dict]) -> dict | None:
    """The closest route airport within its transfer limit that flies in at least one of `months`."""
    best = None
    for r in rts:
        covered = sorted(months & set(r["months"]))
        if not covered:
            continue
        km = haversine_km((lat, lng), (float(r["lat"]), float(r["lng"])))
        if km > r["max_transfer_km"]:
            continue
        if best is None or km < best["transfer_km"]:
            best = {"airport": r.get("airport"), "name": r.get("name"), "transfer_km": round(km),
                    "months": covered, "frequency": r.get("frequency"),
                    "confidence": r.get("confidence", "likely"), "evidence": r.get("evidence")}
    return best


def apply(hotels, cfg: dict, offers: Iterable[dict] | None = None) -> int:
    """Mark hotels near a direct SKP route (in place). Returns how many hotels were marked."""
    fl = settings(cfg)
    if not fl.get("enabled"):
        return 0
    rts = routes(cfg)
    if not rts:
        return 0
    seasons = set(fl.get("seasons", ["summer"]))
    default_months = {int(m) for m in fl.get("trip_months", [6, 7, 8, 9])}
    by_hotel = trip_months(offers) if offers is not None else {}
    items = hotels.values() if isinstance(hotels, dict) else hotels
    marked = 0
    for h in items:
        if h.get("season") not in seasons or h.get("lat") is None or h.get("lng") is None:
            continue
        months = by_hotel.get(h.get("id")) or default_months
        hit = nearest(float(h["lat"]), float(h["lng"]), months, rts)
        if not hit:
            continue
        h["direct_flight_skp"] = True
        h["flight"] = hit
        marked += 1
    log.info("flights: %d hotel(s) within reach of a direct SKP route", marked)
    return marked
