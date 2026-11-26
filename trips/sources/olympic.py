"""Olympic Travel (olympic.rs): Serbian agency, robots.txt allows all paths.

Same booking platform as Travelland (destination code on the page, offer cards
from the site's own /services/list/ endpoint, paged with `_page`), but a
different card layout. A card gives: hotel, stars, town, a "from" price
(per day, or per person per day) with the old price, the board when shown
("Noćenje i doručak" = BB, "Polupansion" = HB …), a badge ("RANI BUKING",
"LAST MINUTE") and "VAŽI DO" (valid until). Cards that say "Dostupno na upit"
(on request) have no price and are skipped. There's no date window on the card,
so the check-in is the page's configured default (or today if later).

Board markup varies: `<div class="text-uppercase">` under "Najbolja cena" on
Bansko cards, `<div class="text-uppercase small">` on Ohrid/Ulcinj cards, and
cards with no board line at all (left "?"). As a fallback a clear board phrase
anywhere on the card ("Polupansion", "All inclusive" …) is used.

Paging: `_page=N` (checked live 2026-11-26 on Ohrid: pages 1–3 give 12 + 12 + 2
distinct hotels of total 26, then stop). We stop when we've seen `total` hotels,
when a page is empty, or when a page brings no new hotel (so a site that ever
ignores `_page` can't make us loop or double-count).
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
from .travelland import _IMG, _num, _title_case, destination_code

log = logging.getLogger(__name__)
BASE = "https://www.olympic.rs"
SOURCE = "Olympic"

BOARDS = [("all inclusive", "AI"), ("ultra all", "AI"), ("pun pansion", "FB"), ("polupansion", "HB"),
          ("noćenje i doručak", "BB"), ("nocenje i dorucak", "BB"), ("noćenje", "RO"), ("najam", "RO")]
_HREF = re.compile(r'<a href="(?P<href>/[^"]+/(?P<oid>\d+)/)"[^>]*card-package')
_TITLE = re.compile(r'<h4 class="h5[^"]*">\s*(.*?)\s*</h4>', re.S)
_LOC = re.compile(r'<h5 class="fw-normal text-muted[^"]*">\s*(.*?)\s*</h5>', re.S)
_NEW = re.compile(r'text-primary mb-0">\s*€\s*([\d.,]+)')
_OLD = re.compile(r'<del[^>]*>\s*€\s*([\d.,]+)')
_VALID = re.compile(r'VA[ŽZ][IE] DO\s*(\d{1,2})\.(\d{1,2})\.(\d{4})', re.I)
_UNIT = re.compile(r'<div class="small text-end">\s*([^<]+?)\s*</div>')
_BADGE = re.compile(r'bg-danger[^"]*">\s*([^<]+?)\s*</div>')
_BOARD_TXT = re.compile(r'Najbolja cena\s*</h5>\s*<(?:div|span|p)[^>]*class="[^"]*text-uppercase[^"]*"[^>]*>\s*([^<]+?)\s*<',
                        re.I)
_BOARD_ANY = re.compile(r"all inclusive|pun pansion|polupansion|no[cć]enje (?:sa |i )?doru[cč]k", re.I)
_LISTED = re.compile(r'<a href="/[^"]+/(\d+)/"[^>]*card-package')


def _text(block: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)))


def listed_ids(payload: str) -> list[str]:
    """Every hotel id on one list answer, priced or not."""
    return list(dict.fromkeys(_LISTED.findall(json.loads(payload or "{}").get("html") or "")))


def board_code(text: str) -> str:
    t = (text or "").lower()
    return next((code for k, code in BOARDS if k in t), "?")


def parse_list(payload: str) -> tuple[list[dict], int]:
    data = json.loads(payload)
    html = data.get("html") or ""
    cards = []
    for block in html.split('class="col-md-6')[1:]:
        m = _HREF.search(block)
        new = _NEW.search(block)
        t = _TITLE.search(block)
        if not m or not new or not t or _num(new.group(1)) <= 0:
            continue                              # "Dostupno na upit" cards have no price
        title = unescape(re.sub(r"\s+", " ", t.group(1)))
        old, valid, unit = _OLD.search(block), _VALID.search(block), _UNIT.search(block)
        badge, board = _BADGE.search(block), _BOARD_TXT.search(block) or _BOARD_ANY.search(_text(block))
        loc = _LOC.search(block)
        img = _IMG.search(block)
        stars = block.count("la-star text-warning")
        cards.append({
            "object_id": m.group("oid"),
            "url": urljoin(BASE, m.group("href")),
            "title": title,
            "name": re.sub(r"^(Hotel|Apartmani|Vila|Aparthotel)\s+", "", title, flags=re.I).strip(),
            "stars": stars or None,
            "location": unescape(loc.group(1)) if loc else "",
            "price": _num(new.group(1)),
            "old": _num(old.group(1)) if old else None,
            "unit": unit.group(1).strip() if unit else "",
            "board": board_code(board.group(board.lastindex or 0)) if board else "?",
            "board_text": board.group(board.lastindex or 0).strip() if board else "",
            "badge": badge.group(1).strip() if badge else "",
            "valid_until": date(int(valid.group(3)), int(valid.group(2)), int(valid.group(1))).isoformat()
            if valid else None,
            "image": image_url(img.group(1), BASE) if img else None,
        })
    return cards, int(data.get("total") or 0)


def to_hotel_and_offer(card: dict, page: dict, cfg: dict, today: date) -> tuple[dict, dict]:
    nights = int(page.get("nights", 7 if page["season"] == "summer" else 5))
    adults = cfg["family"]["adults"]
    unit = card["unit"].lower()
    per_person = "osob" in unit
    per_stay = "boravk" in unit                  # "po boravku" = price for the whole stay
    mult = (adults if per_person else 1) * (1 if per_stay else nights)
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    pct = round((card["old"] - card["price"]) / card["old"] * 100) if card.get("old") else None
    label = " ".join(x for x in (card.get("badge", "").title(), f"-{pct}%" if pct else "") if x) or None
    hotel = {
        "id": f"ol-{card['object_id']}",
        "name": _title_case(card["name"]),
        "stars": card["stars"],
        "season": page["season"],
        "area": page["area"],
        "country": page.get("country", ""),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": page.get("border", True),
        "family": {"verified": []},
        "image": card.get("image"),
        "notes": "Auto-added from Olympic. Family facts unknown — use 'Ask the hotel'.",
    }
    offer = {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": card["board"],
        "room": f"cheapest unit, dates on request ({card['unit'] or 'price per day'})",
        "occupancy": "2+0",
        "price_eur": round(card["price"] * mult, 2),
        "was_eur": round(card["old"] * mult, 2) if card.get("old") else None,
        "discount_label": label,
        "valid_until": card.get("valid_until"),
    }
    return hotel, offer


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    ol = cfg["sources"].get("olympic", {})
    if not ol.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in ol.get("pages", []):
        try:
            code = page.get("destination") or destination_code(s.get(page["url"]))
            if not code:
                log.warning("Olympic: no destination code on %s", page["url"])
                continue
            seen: set[str] = set()
            priced, total = 0, 0
            for n in range(1, int(ol.get("max_list_pages", 6)) + 1):
                q = urlencode({"_page": n, "perPage": 12, "language": "sr", "template": "featured",
                               "destination": code})
                payload = s.get(f"{BASE}/services/list/?{q}") or '{"html": "", "total": 0}'
                cards, total = parse_list(payload)
                fresh = [i for i in listed_ids(payload) if i not in seen]
                seen.update(fresh)
                for c in cards:
                    if c["object_id"] in fresh:
                        h, o = to_hotel_and_offer(c, page, cfg, today)
                        hotels.append(h)
                        offers.append(o)
                        priced += 1
                if not fresh or len(seen) >= total:
                    break
            log.info("Olympic %s: %d hotels listed (of %d), %d with a price", page["area"], len(seen), total,
                     priced)
        except Blocked as e:
            log.warning("Olympic stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Olympic %s skipped: %s", page["area"], e)
    return hotels, offers
