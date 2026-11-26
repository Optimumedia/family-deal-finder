"""Oliver's Travels (oliverstravels.com): whole-villa rentals. robots.txt disallows /search and
sort/tracking parameters only — the region pages we read are allowed.

A region page (e.g. /greece/halkidiki/) lists villa cards in its HTML:
"Villa Brosia · Halkidiki, Greece · 8 guests · 4 bedrooms · 4 bathrooms · [15% Off!] · £2,768 – £10,379 per week".
The whole villa is rented, so the price is the real family price (2+2 fits when guests ≥ 4).
We use the LOW end of the weekly range (off-peak) as the "from" price and say so; GBP is
converted to EUR with the rate in config. Villas are self-catering (no half board).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url, money

log = logging.getLogger(__name__)
BASE = "https://oliverstravels.com"
SOURCE = "Oliver's Travels"
_CARD = re.compile(r"See more (?P<name>(?:(?!See more).){1,90}?) (?P<region>[A-Z][\w-]+) , (?P<country>[A-Z][\w ]+?) (?:\d+\s*-\s*)?(?P<guests>\d+) guests · "
                   r"(?P<bedrooms>\d+) bedrooms? · (?P<baths>\d+) bathrooms? (?P<tags>.*?)£(?P<low>[\d,]+)"
                   r"(?: - £(?P<high>[\d,]+))? per week")
# Each card's photo slider: <a … href="/greece/halkidiki/villa-x/"><img src="https://pms-images…jpg?profile=sm" …>
_PHOTO = re.compile(r'href="(/[a-z-]+/[a-z-]+/villa-[a-z0-9-]+/?)"[^>]*>\s*<img[^>]*?\bsrc="([^"]+)"')


def parse_region(html: str) -> list[dict]:
    text = " ".join(html_to_text(html).split())
    slugs = dict.fromkeys(re.findall(r'href="(/[a-z-]+/[a-z-]+/villa-[a-z0-9-]+/?)"', html))
    by_name = {s.rstrip("/").split("/")[-1]: s for s in slugs}
    photos: dict[str, str] = {}
    for href, src in _PHOTO.findall(html):
        photos.setdefault(href.rstrip("/").split("/")[-1], src)
    out = []
    for m in _CARD.finditer(text):
        name = m.group("name").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        tags = m.group("tags")
        pct = max((int(p) for p in re.findall(r"(\d{1,2})% Off", tags)), default=None)
        out.append({
            "name": name, "slug": slug, "url": urljoin(BASE, by_name.get(slug, "")) if slug in by_name else None,
            "guests": int(m.group("guests")), "bedrooms": int(m.group("bedrooms")),
            "low_gbp": money(m.group("low")), "high_gbp": money(m.group("high")) if m.group("high") else None,
            "pct": pct, "tags": " ".join(tags.split()),
            "image": image_url(photos.get(slug), BASE),
        })
    return out


def to_hotel_and_offer(v: dict, page: dict, cfg: dict, today: date) -> tuple[dict, dict] | None:
    if v["guests"] < cfg["family"]["adults"] + cfg["family"]["kids"]:
        return None
    rate = cfg["sources"]["oliverstravels"].get("gbp_to_eur", 1.17)
    nights = int(page.get("nights", 7))
    weekly_eur = v["low_gbp"] * rate
    hotel = {
        "id": f"ot-{v['slug']}",
        "kind": "villa",
        "name": v["name"],
        "stars": None,
        "season": page["season"],
        "area": page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": True,
        "family": {"separate_bedroom": v["bedrooms"] >= 2, "family_room": True, "verified": []},
        "image": v.get("image"),
        "notes": f"Whole villa: {v['guests']} guests, {v['bedrooms']} bedrooms. Self-catering. "
                 f"Weekly price range £{v['low_gbp']:,.0f}–£{(v['high_gbp'] or v['low_gbp']):,.0f} (low = off-peak).",
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": v["url"] or page["url"],
        "seen": today.isoformat(),
        "check_in": max(str(page.get("check_in", today.isoformat())), today.isoformat()),
        "nights": nights,
        "board": "SC",
        "room": f"whole villa ({v['bedrooms']} bedrooms), lowest weekly rate",
        "occupancy": "2+2",
        "price_eur": round(weekly_eur * nights / 7, 2),
        "was_eur": round(weekly_eur * nights / 7 / (1 - v["pct"] / 100), 2) if v.get("pct") else None,
        "discount_label": f"Oliver's -{v['pct']}%" if v.get("pct") else None,
        "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    ot = cfg["sources"].get("oliverstravels", {})
    if not ot.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in ot.get("pages", []):
        try:
            villas = parse_region(s.get(page["url"]))
        except Blocked as e:
            log.warning("Oliver's Travels stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("Oliver's Travels %s skipped: %s", page["area"], e)
            continue
        for v in villas:
            pair = to_hotel_and_offer(v, page, cfg, today)
            if pair:
                hotels.append(pair[0])
                offers.append(pair[1])
        log.info("Oliver's Travels %s: %d villas", page["area"], len(villas))
    return hotels, offers
