"""BulgariaSki (bulgariaski.com): a Sofia ski-holiday agency with one page per hotel in Bansko,
Borovets and Pamporovo. robots.txt only blocks /search.php, /booking.php, /cms_view.php,
/create_pdf.php, *query=* and contact pages — the resort hotel lists (/bansko/hotels/) and the
hotel pages (/bansko/regnum_apartments.html) are allowed.

A hotel page carries, in plain HTML:
- a price list table (`<table class="pricelist">`): one row per room type with its meal code
  (RO/BB/HB/FB/AI) and a rate per season column; each column header has a tooltip with its date
  ranges ("01/12/2026-23/12/2026; 14/03/2027-03/04/2027"). Rates are EUR per night per
  room/apartment (the table footnote says so), so a stay is priced night by night.
- promo boxes (early booking / last minute / best deals): "- 10 % discount until 30 Nov 2026;".
- price notes: maximum occupancy per apartment, children's reductions age, baby-cot fee.

We keep, per hotel and meal code, the cheapest row with a separate bedroom ("One-bedroom
apartment", "2-bedroom family apartment" …). A hotel with no such row falls back to its cheapest
apartment / suite / family room, with the separate bedroom left unknown. Rooms that are plain
singles/doubles/studios are never offered. A discount is applied only when a promo's deadline is
still ahead and it has no "not valid for period …" condition.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from html import unescape
from urllib.parse import urlparse

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import MONTHS, find_date, html_to_text, image_url

log = logging.getLogger(__name__)
BASE = "https://www.bulgariaski.com"
SOURCE = "BulgariaSki"
MEALS = {"RO": "RO", "BB": "BB", "HB": "HB", "FB": "FB", "AI": "AI", "SC": "SC"}

_TABLE = re.compile(r'<table class="pricelist">(.*?)</table>', re.S)
_TH_RANGE = re.compile(r'<th>\s*([A-Za-z0-9 ]+?)(?:&nbsp;|\s)*<i[^>]*title="([^"]+)"', re.S)
_ROW = re.compile(r"<tr>\s*<th[^>]*>(.*?)</th>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_RANGE = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
_H1 = re.compile(r'<h1[^>]*itemreviewed[^>]*>(.*?)</h1>', re.S)
_IMG = re.compile(r'src="(https?://www\.bulgariaski\.com/hotel-images/big/(\d+)_\d+\.jpg)"')
_PROMO = re.compile(r'list-promo (\w+)">.*?<a[^>]*>(.*?)</a>', re.S)
_PCT = re.compile(r"(\d{1,2})\s?%")
_NOTES = re.compile(r"Price notes(.*?)(?:<h\d|Facilities|</div>\s*</div>\s*</div>)", re.S)

BEDROOM = re.compile(r"\b(one|two|three|1|2|3)[\s-]*bed(?:room)?s?\b|separate bedroom|with (?:a |one |1 )?bedroom",
                     re.I)
APARTMENT_ISH = re.compile(r"apartment|apt\b|suite|family|maisonette|chalet|villa", re.I)
DEFAULT_MATCH = r"apart|residen|complex|club|chalet|holiday|family|villa|house|resort|suite"


def _d(dd: str, mm: str, yy: str) -> date:
    return date(int(yy), int(mm), int(dd))


def _price(cell: str) -> float | None:
    m = re.search(r"(\d[\d.,]*)", unescape(re.sub(r"<[^>]+>", " ", cell)))
    if not m:
        return None
    v = float(m.group(1).replace(",", "")) if re.fullmatch(r"\d{1,3}(,\d{3})+", m.group(1)) \
        else float(m.group(1).replace(",", "."))
    return v or None


def parse_pricelist(html: str) -> tuple[list[list[tuple[date, date]]], list[dict]]:
    """Season columns (each a list of [start, end) ranges) and rows {room, meal, rates[]}."""
    m = _TABLE.search(html)
    if not m:
        return [], []
    head, _, body = m.group(1).partition("<tbody>")
    seasons = []
    for _, title in _TH_RANGE.findall(head):
        seasons.append([(_d(a, b, c), _d(d, e, f)) for a, b, c, d, e, f in _RANGE.findall(title)])
    rows = []
    for room, rest in _ROW.findall(body):
        cells = _TD.findall(rest)
        if len(cells) < 2:
            continue
        meal = re.sub(r"<[^>]+>|\s", "", cells[0]).upper()
        rows.append({"room": " ".join(unescape(re.sub(r"<[^>]+>", " ", room)).split()),
                     "meal": MEALS.get(meal, "?"),
                     "rates": [_price(c) for c in cells[1:1 + len(seasons)]]})
    return seasons, rows


def _season_of(day: date, seasons: list[list[tuple[date, date]]]) -> int | None:
    for inclusive in (False, True):            # boundary days belong to the season that starts on them
        for i, ranges in enumerate(seasons):
            if any(a <= day < b or (inclusive and day == b) for a, b in ranges):
                return i
    return None


def stay_price(rates: list, seasons, check_in: date, nights: int) -> float | None:
    """Sum of the nightly rates; None if any night falls outside the price list or has no rate."""
    total = 0.0
    for n in range(nights):
        i = _season_of(check_in + timedelta(days=n), seasons)
        if i is None or i >= len(rates) or not rates[i]:
            return None
        total += rates[i]
    return total


_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d{2})\b", re.I)


def _deadline(item: str, today: date) -> str | None:
    """'until 30 Sept 2026' → 2026-09-30 (day-month-year first: the shared find_date reads 'Sept 2026' as Sep 20)."""
    m = _DMY.search(item)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return find_date(item, today)


def promos(html: str, today: date) -> list[dict]:
    """Current discounts from the promo boxes: [{pct, valid_until, kind}], best first."""
    out, seen = [], set()
    order = {"green": 0, "red": 1}
    for color, text in sorted(_PROMO.findall(html), key=lambda p: order.get(p[0], 2)):
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", text)).split())
        kind = {"green": "Early booking", "red": "Last minute"}.get(color, "Offer")
        for item in re.split(r";|\s-\s(?=\d)", text):
            pm = _PCT.search(item)
            if not pm or re.search(r"not valid|except|excluding", item, re.I):
                continue
            until = _deadline(item, today)
            if not until or until < today.isoformat():
                continue
            key = (int(pm.group(1)), until)
            if key not in seen and 3 <= key[0] <= 60:
                seen.add(key)
                out.append({"pct": key[0], "valid_until": until, "kind": kind})
    return sorted(out, key=lambda p: (-p["pct"], p["valid_until"]))


def parse_hotel(html: str, today: date) -> dict | None:
    h1 = _H1.search(html)
    seasons, rows = parse_pricelist(html)
    if not h1 or not rows:
        return None
    name = " ".join(unescape(re.sub(r"<!--.*?-->|<[^>]+>", " ", h1.group(1), flags=re.S)).split())
    img = _IMG.search(html)
    nm = _NOTES.search(html)
    notes = " ".join(html_to_text(nm.group(1)).split()) if nm else ""
    occ = re.search(r"1-bedroom apartment\s*-\s*([^;.]+)", notes, re.I) or \
        re.search(r"one[- ]bedroom apartment\s*-\s*([^;.]+)", notes, re.I)
    kids = re.search(r"children reductions[^.]*?(\d{1,2})\s*-\s*(\d{1,2})(?:\.\d+)?\s*years", notes, re.I)
    cot = re.search(r"baby cot[^\d]{0,20}([\d.,]+)\s*(?:€|euro)", notes, re.I)
    return {
        "name": name,
        "stars": h1.group(1).count("star.png") or None,
        "hotel_no": img.group(2) if img else None,
        "image": image_url(img.group(1), BASE) if img else None,
        "seasons": seasons,
        "rows": rows,
        "promos": promos(html, today),
        # "City tax: 1.4 Euro per person" is not a per-person rate: only a price/rate sentence counts.
        "per_person": bool(re.search(r"(?:prices?|rates?)\b[^.*]{0,40}per person", notes, re.I))
        and not re.search(r"per (room|apartment|studio|villa|unit)", notes, re.I),
        "max_1bed": " ".join(occ.group(1).split())[:60] if occ else None,
        "kids_from": int(kids.group(1)) if kids else None,
        "cot_eur": float(cot.group(1).replace(",", ".")) if cot else None,
    }


def hotel_links(html: str, resort: str, match: str | None = DEFAULT_MATCH) -> list[tuple[str, str]]:
    """(url, name) of the resort's hotel pages from a list page, optionally filtered by name."""
    found = re.findall(rf'<a[^>]+href="(https://www\.bulgariaski\.com/{re.escape(resort)}/[a-z0-9_]+\.s?html)"'
                       r'[^>]*>\s*([^<]+?)\s*</a>', html)
    links = dict((u, " ".join(unescape(n).split())) for u, n in found)
    pat = re.compile(match, re.I) if match else None
    return [(u, n) for u, n in links.items() if not pat or pat.search(n) or pat.search(u.rsplit("/", 1)[-1])]


def to_hotel_and_offers(h: dict, url: str, page: dict, cfg: dict, today: date) -> tuple[dict | None, list[dict]]:
    nights = int(page.get("nights", 5))
    check_in = max(str(page.get("check_in", today.isoformat())), today.isoformat())
    ci = datetime.strptime(check_in, "%Y-%m-%d").date()
    mult = cfg["family"]["adults"] if h["per_person"] else 1
    priced = []
    for r in h["rows"]:
        stay = stay_price(r["rates"], h["seasons"], ci, nights)
        if stay is not None:
            priced.append({**r, "stay": stay * mult})
    bedroom = [r for r in priced if BEDROOM.search(r["room"])]
    pool = bedroom or [r for r in priced if APARTMENT_ISH.search(r["room"])]
    if not pool:
        return None, []
    best: dict[str, dict] = {}
    for r in pool:
        if r["meal"] not in best or r["stay"] < best[r["meal"]]["stay"]:
            best[r["meal"]] = r
    is_apt = any(re.search(r"apartment|apt\b|maisonette", r["room"], re.I) for r in best.values())
    slug = re.sub(r"\.s?html$", "", url.rstrip("/").rsplit("/", 1)[-1])
    fam = {"verified": []}
    if bedroom:
        fam["separate_bedroom"] = True
    bits = []
    if h["max_1bed"]:
        bits.append(f"Page: 1-bedroom apartment sleeps {h['max_1bed']}.")
    if h["kids_from"] is not None:
        bits.append(f"Children's reductions from age {h['kids_from']} — ask the price for two 3-year-olds.")
    if h["cot_eur"]:
        bits.append(f"Baby cot €{h['cot_eur']:g}/night (how many not stated).")
    hotel = {
        "id": f"bs-{h['hotel_no'] or slug}",
        "name": h["name"],
        "stars": h["stars"],
        "season": page.get("season", "winter"),
        "area": page["area"],
        "country": page.get("country", "BG"),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": page.get("border", True),
        "kind": "apartment" if is_apt else "hotel",
        "family": fam,
        "image": h["image"],
        "notes": " ".join(["Auto-added from BulgariaSki (price-list rates per room/apartment)."] + bits),
    }
    promo = h["promos"][0] if h["promos"] else None
    offers = []
    for meal, r in sorted(best.items()):
        price, was = r["stay"], None
        if promo:
            was, price = price, price * (100 - promo["pct"]) / 100
        offers.append({
            "hotel": hotel["id"],
            "source": SOURCE,
            "url": url,
            "seen": today.isoformat(),
            "check_in": check_in,
            "nights": nights,
            "board": meal,
            "room": r["room"],
            "occupancy": "2+0",          # per-unit rate; children's supplement for 3-year-olds not on the page
            "price_eur": round(price, 2),
            "was_eur": round(was, 2) if was else None,
            "discount_label": f"{promo['kind']} -{promo['pct']}%" if promo else None,
            "valid_until": promo["valid_until"] if promo else None,
        })
    return hotel, offers


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    bs = cfg["sources"].get("bgski", {})
    if not bs.get("enabled"):
        return [], []
    s = session or PoliteSession(max(cfg["sources"]["delay_seconds"], 5), cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers = [], []
    for page in bs.get("pages", []):
        try:
            resort = urlparse(page["url"]).path.strip("/").split("/")[0]
            links = [(u, "") for u in page.get("hotels", [])] or \
                hotel_links(s.get(page["url"]), resort, page.get("match", bs.get("match", DEFAULT_MATCH)))
            links = links[: int(page.get("max_hotels", bs.get("max_hotels", 40)))]
            kept = 0
            for url, _ in links:
                try:
                    h = parse_hotel(s.get(url), today)
                except Unavailable as e:
                    log.warning("BulgariaSki %s skipped: %s", url, e)
                    continue
                if not h:
                    continue
                hotel, offs = to_hotel_and_offers(h, url, page, cfg, today)
                if hotel and offs:
                    hotels.append(hotel)
                    offers.extend(offs)
                    kept += 1
            log.info("BulgariaSki %s: %d hotel pages, %d with an apartment/bedroom price for the dates",
                     page["area"], len(links), kept)
        except Blocked as e:
            log.warning("BulgariaSki stopped (respecting the block): %s", e)
            break
        except Unavailable as e:
            log.warning("BulgariaSki %s skipped: %s", page["area"], e)
    return hotels, offers
