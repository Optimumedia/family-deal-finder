"""Savana Travel (online.savana.travel): Skopje agency selling flight + hotel packages FROM SKOPJE.

robots.txt (www.online.savana.travel) allows `/` for every user agent; it only
disallows /admin, /catalog, /packages_explorer, /packages/explorer, *print=yes,
*get_search_rooms and *change_language*. We read only the public destination
listing pages (/vacations/<country>/<resort>/from-skopje/vacations/with-plane/
and their /2/, /3/ pages) and never the search engine (/packages/results/).

A listing card gives: hotel name, stars (icon), photo, the "from" price for
2 adults with the flight from Skopje, the old price when discounted, and the
price per stay length ("2 возрасни / 6, 7 ноќи", each with its own title price).
The page's map script gives each hotel's lat/lng. What a card does NOT give:
the board and the date the "from" price belongs to. So offers are stored as
2 adults ("2+0"), board "?", nights = the stay length the "from" price is for,
and check-in = the page's configured default (or the first departure date the
page offers, if later) with "dates on request" in the room text.

Every hotel here is reached by a flight from Skopje (that's what the package
is), so `direct_flight_skp` is True and `border` False.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from html import unescape
from urllib.parse import urljoin

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://www.online.savana.travel"
SOURCE = "Savana Travel"

_CARD_SPLIT = 'class="flex-col-md-3 flex-col-sm-6"'
_HREF = re.compile(r'<a href="(?P<href>/vacations/(?P<slug>[^/"]+)/from-skopje/[^"]*)"')
_NAME = re.compile(r'class="destination" title="([^"]*)"')
_STARS = re.compile(r'icon-star-(\d)\.png')
_IMG = re.compile(r'<img src="([^"]+)" alt=')
_OLD = re.compile(r'price-discount">\s*<span class="value">.*?</span>\s*([\d.,]+)<sup>(\d+)</sup>', re.S)
_NEW = re.compile(r'<div class="price">\s*<span class="value">.*?</span>\s*([\d.,]+)<sup>(\d+)</sup>', re.S)
_DETAILS = re.compile(r'price-details">(.*?)</div>', re.S)
_STAY = re.compile(r'<span title="([\d.,]+) EUR">(\d+)</span>')
_ADULTS = re.compile(r'(\d+)\s*возрасн', re.I)
_PIN = re.compile(r"new google\.maps\.LatLng\('(-?[\d.]+)','(-?[\d.]+)'\);\s*var marker.*?data-code=\"([^\"]+)\"", re.S)
_DEPART = re.compile(r'<option value="(\d{2})\.(\d{2})\.(\d{4})"\s+nights="')
_NEXT = re.compile(r'href="(/vacations/[^"]+/with-plane/(\d+)/)"')
_SLUG_TOWN = re.compile(r'-(\d)-stars-(?P<town>[a-z-]+?)-(?P<country>turkey|egypt|greece|tunisia|cyprus|montenegro)$')


def _money(whole: str, cents: str = "0") -> float:
    return float(re.sub(r"\D", "", whole) or 0) + int(cents) / 100


def _photo(src: str) -> str | None:
    """Hotlinkable https photo, or None (some cards point at a bare IP:port file server)."""
    url = image_url(src, BASE)
    if not url or re.match(r"https://[\d.]+(:\d+)?/", url) or "/assets/img/" in url:
        return None
    return url


def pins(html: str) -> dict[str, tuple[float, float]]:
    """Hotel slug → (lat, lng) from the listing's map script."""
    out = {}
    for lat, lng, slug in _PIN.findall(html):
        try:
            out[slug] = (float(lat), float(lng))
        except ValueError:
            continue
    return out


def departures(html: str) -> list[str]:
    """Departure dates the page offers (ISO), sorted."""
    return sorted({f"{y}-{m}-{d}" for d, m, y in _DEPART.findall(html)})


def next_pages(html: str) -> list[str]:
    return sorted({urljoin(BASE, h) for h, _ in _NEXT.findall(html)}, key=lambda u: int(u.rstrip("/").rsplit("/", 1)[1]))


def parse_list(html: str) -> list[dict]:
    cards = []
    for block in html.split(_CARD_SPLIT)[1:]:
        href, name, new = _HREF.search(block), _NAME.search(block), _NEW.search(block)
        if not href or not name or not new:
            continue
        price = _money(*new.groups())
        if price <= 0:
            continue
        old = _OLD.search(block)
        det = _DETAILS.search(block)
        det_html = det.group(1) if det else ""
        stays = [(int(n), _money(p)) for p, n in _STAY.findall(det_html)]
        adults = _ADULTS.search(det_html)
        # the stay length the "from" price belongs to (the one whose title equals it)
        nights = next((n for n, p in stays if abs(p - round(price)) < 1), stays[0][0] if stays else None)
        stars = _STARS.search(block)
        img = _IMG.search(block)
        slug = href.group("slug")
        town = _SLUG_TOWN.search(slug)
        cards.append({
            "slug": slug,
            "url": urljoin(BASE, href.group("href")),
            "name": unescape(name.group(1)).strip(),
            "stars": int(stars.group(1)) if stars else None,
            "town": town.group("town").replace("-", " ").title() if town else "",
            "price": price,
            "old": _money(*old.groups()) if old else None,
            "nights": nights,
            "stays": stays,
            "adults": int(adults.group(1)) if adults else None,
            "image": _photo(img.group(1)) if img else None,
        })
    return cards


def _clean_name(name: str) -> str:
    name = re.sub(r"\s*\(\s*ex\.?[^)]*\)\s*", " ", name, flags=re.I)
    name = re.sub(r"^(Hotel|Otel)\s+|\s+(Hotel|Otel)$", "", name.strip(), flags=re.I)
    return " ".join(w if any(c.islower() for c in w) else w.capitalize() for w in name.split())


def to_hotel_and_offer(card: dict, page: dict, cfg: dict, today: date, pin=None, first_departure=None):
    if card.get("adults") not in (None, cfg["family"]["adults"]):
        return None                                   # priced for another party size
    nights = card.get("nights") or int(page.get("nights", 7))
    check_in = max(str(page.get("check_in", today.isoformat())), first_departure or "", today.isoformat())
    pct = round((card["old"] - card["price"]) / card["old"] * 100) if card.get("old") else None
    lat, lng = pin or (page["lat"], page["lng"])
    area = f"{card['town']}, {page.get('region', page['area'])}" if card.get("town") else page["area"]
    hotel = {
        "id": f"sv-{card['slug']}",
        "name": _clean_name(card["name"]),
        "stars": card["stars"],
        "season": page.get("season", "summer"),
        "area": area,
        "country": page.get("country", ""),
        "lat": lat,
        "lng": lng,
        "direct_flight_skp": bool(page.get("direct_flight_skp", True)),
        "border": False,
        "kind": "hotel",
        "family": {"verified": []},
        "image": card.get("image"),
        "notes": "Auto-added from Savana Travel (package with flight from Skopje). "
                 "Board not shown on the listing — ask; family facts unknown.",
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": "?",
        "room": f"cheapest room, flight from Skopje included, 2 adults, {nights} nights, dates on request",
        "occupancy": "2+0",
        "price_eur": round(card["price"], 2),
        "was_eur": round(card["old"], 2) if card.get("old") else None,
        "discount_label": f"Savana -{pct}%" if pct else None,
        "valid_until": None,
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    sc = cfg["sources"].get("charters", {})
    if not sc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers, seen = [], [], set()
    for page in sc.get("pages", []):
        try:
            html = s.get(page["url"])
            if not html:
                continue
            where, first = pins(html), next((d for d in departures(html) if d >= today.isoformat()), None)
            todo = next_pages(html)[: max(0, int(sc.get("max_list_pages", 3)) - 1)]
            n_cards = 0
            while True:
                for c in parse_list(html):
                    n_cards += 1
                    if c["slug"] in seen:
                        continue
                    pair = to_hotel_and_offer(c, page, cfg, today, where.get(c["slug"]), first)
                    if pair:
                        seen.add(c["slug"])
                        hotels.append(pair[0])
                        offers.append(pair[1])
                if not todo:
                    break
                html = s.get(todo.pop(0))
            log.info("Savana %s: %d cards, %d offers so far", page["area"], n_cards, len(offers))
        except Blocked as e:
            log.warning("Savana stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Savana %s skipped: %s", page["area"], e)
    return hotels, offers
