"""Travelland (travelland.rs): Serbian agency, robots.txt allows all paths.

How the site works: each destination page carries a `data-destination` code, and
the offer cards come from the site's own list endpoint
(/services/list/?destination=<code>&paginate=N), returned as an HTML fragment
inside JSON. Each card gives the hotel, a "from" price PER PERSON PER NIGHT
(old and new), the discount %, the "valid until" date and the date window
that price applies to.

What we can't get from a card: board (BB/HB …), room type, the kids' price.
So offers are stored as 2 adults × N nights ("2+0"), board unknown ("?"), and
the dashboard says so. Polite: one destination page + a few list pages per run,
6–10 s apart, through PoliteSession (robots.txt + bot-wall stop).

Tag-category pages (Thassos, Olympic Riviera) have an empty `data-destination`
and list by tag instead: /services/list/?destination=&tagCategoryId=564&…
Configure them with `tag_category = 564` (or let the page's own
`data-tagCategoryId` be read). Summer cards carry no date window, so give
those pages a `check_in`.

Paging: on 2026-11-26 the endpoint answered paginate=1, 2 and 3 with the same
12 cards (Thassos). Bansko's 36 "offers" from 30 hotels on 25.11 were the same
thing. So we send `_page` too (the parameter Olympic's copy of the platform
honours) and stop as soon as a page brings no hotel we haven't seen.
"Ponuda stiže uskoro!" (offer coming soon) answers have total 0: Travelland
Kassandra and Sithonia were like that on 2026-11-26, which is why they gave 0.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from html import unescape
from urllib.parse import urlencode, urljoin

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://www.travelland.rs"
SOURCE = "Travelland"

_CARD = re.compile(r'<a href="(?P<href>/smestaj/[^"]+/(?P<oid>\d+)/)"[^>]*class="card[^"]*"[^>]*>(?P<body>.*?)</a>\s*</div>',
                   re.S)
_TITLE = re.compile(r'<h4 class="title">\s*(.*?)\s*</h4>', re.S)
_HIDDEN = re.compile(r'<div style="display: none">\s*\d+\s*-\s*(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})')
_VALID = re.compile(r'VA[ŽZ][IE] DO\s*(\d{1,2})\.(\d{1,2})\.(\d{4})', re.I)
_OLD = re.compile(r'unit-price-old">\s*€\s*([\d.,]+)')
_NEW = re.compile(r'unit-price-total">\s*€\s*([\d.,]+)')
_PCT = re.compile(r'percent-content-percent">\s*(\d+)\s*%')
_LABEL = re.compile(r'unit-price-label">\s*([^<]+?)\s*<')
_STARS = re.compile(r'(\d)\s*\*')
_IMG = re.compile(r'<img[^>]*?\b(?:data-src|src)="([^"]+)"')


def _num(s: str) -> float:
    """'35' → 35, '1.205' → 1205 (Serbian thousands dot), '35,50' → 35.5."""
    s = s.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s.replace(".", "").replace(",", ".") if "," in s else s)


def destination_code(page_html: str) -> str | None:
    """The code the page's own offer list uses (`list-featured`), else the first one on the page."""
    m = (re.search(r'class="list-featured"[^>]*data-destination="([\d:]+)"', page_html)
         or re.search(r'data-destination="([\d:]+)"', page_html))
    return m.group(1) if m else None


def tag_category(page_html: str) -> str | None:
    m = re.search(r'data-tagCategoryId="(\d+)"', page_html, re.I)
    return m.group(1) if m else None


def list_query(page: dict, page_html: str | None = None) -> dict | None:
    """The /services/list/ filter for a configured page: a destination code or a tag category.
    Config keys win; the page HTML (fetched only when the config has neither) fills the gap."""
    if page.get("destination"):
        return {"destination": page["destination"]}
    if page.get("tag_category"):
        return {"destination": "", "tagCategoryId": str(page["tag_category"])}
    if page_html is None:
        return None
    code = destination_code(page_html)
    if code:
        return {"destination": code}
    tag = tag_category(page_html)
    return {"destination": "", "tagCategoryId": tag} if tag else None


def parse_list(payload: str) -> tuple[list[dict], int]:
    """Parse one /services/list/ JSON answer into card dicts. Returns (cards, total)."""
    data = json.loads(payload)
    html = data.get("html") or ""
    cards = []
    for m in _CARD.finditer(html):
        body = m.group("body")
        title = unescape(re.sub(r"\s+", " ", _TITLE.search(body).group(1))) if _TITLE.search(body) else ""
        new = _NEW.search(body)
        if not title or not new:
            continue
        hidden, valid, old, pct = _HIDDEN.search(body), _VALID.search(body), _OLD.search(body), _PCT.search(body)
        label = _LABEL.search(body)
        stars = _STARS.search(title)
        img = _IMG.search(body)
        cards.append({
            "object_id": m.group("oid"),
            "url": urljoin(BASE, m.group("href")),
            "title": title,
            "name": re.sub(r"^(Hotel|Apartmani|Vila|Aparthotel)\s+", "", re.sub(r"\s*\d\s*\*\s*$", "", title), flags=re.I).strip(),
            "stars": int(stars.group(1)) if stars else None,
            "price_pp": _num(new.group(1)),
            "old_pp": _num(old.group(1)) if old else None,
            "pct": int(pct.group(1)) if pct else None,
            "unit": label.group(1).strip() if label else "",
            "date_from": hidden.group(1) if hidden else None,
            "date_to": hidden.group(2) if hidden else None,
            "valid_until": date(int(valid.group(3)), int(valid.group(2)), int(valid.group(1))).isoformat() if valid else None,
            "image": image_url(img.group(1), BASE) if img else None,
        })
    return cards, int(data.get("total") or 0)


def listed_ids(payload: str) -> list[str]:
    """Every hotel id on one list answer, priced or not (for paging; parse_list keeps priced cards only)."""
    html = (json.loads(payload or "{}").get("html") or "")
    return list(dict.fromkeys(re.findall(r'<a href="/smestaj/[^"]+/(\d+)/"', html)))


def _title_case(name: str) -> str:
    return " ".join(w if any(c.islower() for c in w) else w.capitalize() for w in name.split())


def to_hotel_and_offer(card: dict, page: dict, cfg: dict, today: date) -> tuple[dict, dict] | None:
    if not card.get("date_from"):
        # summer cards carry no hidden date window: use the page's default check-in
        card = {**card, "date_from": str(page.get("check_in", today.isoformat()))}
    if card.get("date_to") and card["date_to"] < today.isoformat():
        return None                          # price window already over
    check_in = max(card["date_from"], today.isoformat())
    nights = int(page.get("nights", 7 if page["season"] == "summer" else 5))
    adults = cfg["family"]["adults"]
    per_night_unit = "po osobi" in card["unit"].lower() or not card["unit"]
    mult = adults * nights if per_night_unit else nights
    hotel = {
        "id": f"tl-{card['object_id']}",
        "name": _title_case(card["name"]),
        "stars": card["stars"],
        "season": page["season"],
        "area": page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": True,
        "family": {"verified": []},
        "image": card.get("image"),
        "notes": "Auto-added from Travelland. Family facts unknown — use 'Ask the hotel'.",
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": "?",
        "room": f"cheapest unit ({card['unit'] or 'price per person per night'})",
        "occupancy": "2+0",
        "price_eur": round(card["price_pp"] * mult, 2),
        "was_eur": round(card["old_pp"] * mult, 2) if card.get("old_pp") else None,
        "discount_label": f"Travelland -{card['pct']}%" if card.get("pct") else None,
        "valid_until": card.get("valid_until"),
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    tl = cfg["sources"].get("travelland", {})
    if not tl.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in tl.get("pages", []):
        try:
            query = list_query(page) or list_query(page, s.get(page["url"]))
            if not query:
                log.warning("Travelland: no destination code or tag category on %s", page["url"])
                continue
            seen: set[str] = set()
            n_offers, total = 0, 0
            for n in range(1, int(tl.get("max_list_pages", 5)) + 1):
                q = urlencode({**query, "transportationType": "", "template": "featured",
                               "perPage": 12, "sortBy": "", "_page": n, "paginate": n})
                payload = s.get(f"{BASE}/services/list/?{q}") or '{"html": "", "total": 0}'
                cards, total = parse_list(payload)
                fresh = [i for i in listed_ids(payload) if i not in seen]
                seen.update(fresh)
                for c in (c for c in cards if c["object_id"] in fresh):
                    pair = to_hotel_and_offer(c, page, cfg, today)
                    if pair:
                        hotels.append(pair[0])
                        offers.append(pair[1])
                        n_offers += 1
                if not fresh or len(seen) >= total:
                    break                      # a page that only repeats cards means paging is ignored
            log.info("Travelland %s: %d hotels of %d listed, %d offers", page["area"], len(seen), total, n_offers)
        except Blocked as e:
            log.warning("Travelland stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Travelland %s skipped: %s", page["area"], e)
    return hotels, offers
