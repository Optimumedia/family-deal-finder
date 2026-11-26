"""Clickstay (clickstay.com): whole villas and apartments rented from owners and agents.
robots.txt is `User-Agent: *` with no Disallow lines, so the region pages we read are allowed.

A region page (e.g. /greece/chalkidiki) is server-rendered. Besides the visible cards it carries
the cards' data as a JS state object per property:
  {title:"Villa Levrecchio",url:"/p/439052",image:$R[36]={url:"…",alt:"Villa in Greece, Sithonia: …"},
   propertyType:"2 bedroom villa",sleeps:4,summary:"…",price:1522,…}
`price` is the "From £… per week" figure (the lowest weekly rate, GBP). We keep villas and
apartments that sleep 4+ (the whole place is rented, so 2+2 is the real family price), convert
GBP with the rate in config, and pro-rate the week to the page's nights. Self-catering ("SC").
The card photo is hotlinked from Clickstay's own CDN (the <img src> on the page).
Only a beach distance the summary states in metres is kept as a fact; the text itself is not stored.

Clickstay is part of the Oliver's Travels group, so a few Halkidiki villas also appear on
oliverstravels.com under the same name; ids differ (cs- vs ot-).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date

from ..http import Blocked, PoliteSession, Unavailable

log = logging.getLogger(__name__)
BASE = "https://www.clickstay.com"
SOURCE = "Clickstay"
_STR = r'"((?:[^"\\]|\\.)*)"'
_CARD = re.compile(r'\{title:' + _STR + r',url:"/p/(\d+)",image:\$R\[\d+\]=\{url:"[^"]*",alt:' + _STR +
                   r'\},propertyType:' + _STR + r',sleeps:(\d+),summary:' + _STR + r',price:([\d.]+|null)')
_CDN = re.compile(r'<img src="(https://[a-z0-9]+\.cloudfront\.net/([A-Za-z0-9_=-]+))"')
_BEACH = re.compile(r"(\d{2,4})\s?(?:m|meters|metres)\b[^.]{0,60}?\bbeach|\bbeach[^.]{0,30}?\b(\d{2,4})\s?(?:m|meters|metres)\b",
                    re.I)


def _unjs(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: {"n": " ", "r": " ", "t": " "}.get(m.group(1), m.group(1)), s)


def _photos(html: str) -> dict[str, str]:
    """Property id → the card's CDN photo URL (its path is a base64 JSON with the S3 key)."""
    out: dict[str, str] = {}
    for url, blob in _CDN.findall(html):
        try:
            key = json.loads(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4)))["key"]
        except (ValueError, KeyError, TypeError):
            continue
        m = re.match(r"images/property/(\d+)/", key)
        if m:
            out.setdefault(m.group(1), url)
    return out


def parse_region(html: str) -> list[dict]:
    photos = _photos(html)
    out, seen = [], set()
    for title, pid, alt, ptype, sleeps, summary, price in _CARD.findall(html):
        if pid in seen:
            continue
        seen.add(pid)
        ptype = _unjs(ptype)
        bedrooms = re.search(r"(\d+)\s+bedroom", ptype)
        town = re.search(r"in [A-Z][\w ]+?, ([^:]+)", _unjs(alt))
        beach = _BEACH.search(_unjs(summary))
        lowered = ptype.lower()
        out.append({
            "id": pid,
            "name": " ".join(_unjs(title).split()),
            "url": f"{BASE}/p/{pid}",
            "type": ptype,
            "kind": "apartment" if ("apartment" in lowered or "studio" in lowered) else "villa",
            "bedrooms": int(bedrooms.group(1)) if bedrooms else (0 if "studio" in lowered else None),
            "sleeps": int(sleeps),
            "town": town.group(1).strip() if town else None,
            "week_gbp": float(price) if price != "null" else None,
            "beach_m": int(beach.group(1) or beach.group(3)) if beach else None,
            "image": photos.get(pid),
        })
    return out


def to_hotel_and_offer(v: dict, page: dict, cfg: dict, today: date) -> tuple[dict, dict] | None:
    if v["sleeps"] < cfg["family"]["adults"] + cfg["family"]["kids"] or not v["week_gbp"]:
        return None
    rate = cfg["sources"].get("rentals", {}).get("gbp_to_eur", 1.17)
    nights = int(page.get("nights", 7))
    weekly_eur = v["week_gbp"] * rate
    generic = {"chalkidiki", "halkidiki", "greece", "bulgaria"}
    town = v["town"] if v["town"] and v["town"].lower() not in generic and v["town"].lower() not in page["area"].lower() \
        else None
    family = {"separate_bedroom": (v["bedrooms"] or 0) >= 1 if page["season"] == "winter" else (v["bedrooms"] or 0) >= 2,
              "family_room": True, "verified": []}
    if v["beach_m"] is not None:
        family["beach_m"] = v["beach_m"]
    hotel = {
        "id": f"cs-{v['id']}",
        "kind": v["kind"],
        "name": v["name"],
        "stars": None,
        "season": page["season"],
        "area": f"{town}, {page['area']}" if town else page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": True,
        "family": family,
        "image": v.get("image"),
        "notes": f"Whole {v['type']}, sleeps {v['sleeps']}. Self-catering. "
                 f"Lowest weekly rate £{v['week_gbp']:,.0f} (\"from\" price, dates not stated)."
                 + (f" Beach about {v['beach_m']} m (owner's text)." if v["beach_m"] is not None else ""),
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": v["url"],
        "seen": today.isoformat(),
        "check_in": max(str(page.get("check_in", today.isoformat())), today.isoformat()),
        "nights": nights,
        "board": "SC",
        "room": f"whole {v['type']}, lowest weekly rate",
        "occupancy": "2+2",
        "price_eur": round(weekly_eur * nights / 7, 2),
        "was_eur": None,
        "discount_label": None,
        "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    rc = cfg["sources"].get("rentals", {})
    if not rc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers, seen = [], [], set()
    for page in rc.get("pages", []):
        try:
            places = parse_region(s.get(page["url"]))
        except Blocked as e:
            log.warning("Clickstay stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("Clickstay %s skipped: %s", page["area"], e)
            continue
        kept = 0
        for v in places:
            if v["id"] in seen:
                continue
            pair = to_hotel_and_offer(v, page, cfg, today)
            if pair:
                seen.add(v["id"])
                hotels.append(pair[0])
                offers.append(pair[1])
                kept += 1
        log.info("Clickstay %s: %d places, %d priced for 4+", page["area"], len(places), kept)
    return hotels, offers
