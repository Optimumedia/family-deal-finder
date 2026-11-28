"""Hotel-only Turkish Aegean prices from Bee Travel's own 2027 price lists (beetravel.bg).

Why hotel-only: in summer the family books the direct SKP flight themselves (Izmir ADB for
Kusadasi / Pamucak / Ozdere, Bodrum BJV for Didim), so hotels are stored with
`direct_flight_skp = True` and the arrival airport from the page config goes into the notes.

The source: Bee Travel, a Bulgarian agency on WordPress/WooCommerce. Its Turkey "tours" are
hotel stays with no transport (the price includes the room, board and parking only).
robots.txt (beetravel.bg/robots.txt, checked 28.11.2026) is EMPTY: an HTTP 200 with no rules,
so every path is allowed. We read two kinds of plain server-rendered page:

1. a category page, /produkt-kategoriya/turciya/<resort>/: one `<li class="item-tour …">` per
   hotel inside `<ul class="products …">` (link, title "Hotel – Town", photo, "from" price).
   The sidebar's Bulgarian offers sit outside that list and are ignored;
2. a hotel page, /tours/<slug>/: the price tab holds the hotel's 2027 PRICE TABLE: one column
   per date period ("03.07.2027<br>09.07.2027"), one row per room type with a price PER PERSON
   PER NIGHT, then the basis line ("Посочените цени са на човек и включват: нощувка, Ultra All
   Inclusive, аквапарк") and the child rules ("Дете до 6.99 г се настанява безплатно." = a
   child up to 6.99 stays free; "Едно дете до 12.99 г се настанява безплатно." = ONE child up
   to 12.99 free). The location tab gives the hotel's own pin (data-lat / data-long).

So a real 2+2 total can be worked out without any search request: for each night of the stay,
2 × the adult price of the period that night falls in, plus each child at the share its rule
states (0 % when free). We price the cheapest FAMILY-type room ("Фамилна стая", "Фамилен
апартамент", "стая с двуетажно легло" = bunk-bed room …), because a standard double rarely
takes 2 adults + 2 children. If a hotel lists no such room, or a child matches no rule, the
offer is stored as "2+0" (2 adults, cheapest room) and says so.

Cross-check (28.11.2026): Palm Wings Ephesus, bunk-bed room, 7 nights from 03.07.2027:
2 × 249.50 × 7 = €3,493 here; Relaxo.bg's own 2+2 search (ages 3, 3) gave €3,461.54 before
its Black-Friday discount, i.e. the kids really are free and the two price lists agree within 1 %.

Cost per run: 1 category page per configured resort + 1 page per hotel (≤ 9 Turkey hotels in all).
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://beetravel.bg"
SOURCE = "Bee Travel (hotel only)"

BOARDS = [("ultra all inclusive", "AI"), ("ultra all", "AI"), ("all inclusive", "AI"), ("uall", "AI"),
          ("пълен пансион", "FB"), ("full board", "FB"), ("полупансион", "HB"), ("закуска и вечеря", "HB"),
          ("half board", "HB"), ("закуска", "BB"), ("само нощувка", "RO")]
FAMILY_ROOM = re.compile(r"фамил|family|двуетажно|bunk|апартамент|suite|суит|свързан|connect|две спални|2 спални", re.I)
# Town names as the page titles spell them -> English (area shown as "<town>, <region>").
TOWNS = {"кушадасъ": "Kusadasi", "йоздере": "Ozdere", "дидим": "Didim", "памуджак": "Pamucak",
         "бодрум": "Bodrum", "чешме": "Cesme", "гюзелчамлъ": "Guzelcamli"}
STARS = {"петзвезд": 5, "четиризвезд": 4, "тризвезд": 3}

_PRODUCTS = re.compile(r'<ul class="products[^"]*"(.*?)</ul>', re.S)
_ITEM = re.compile(r'<li class="item-tour[^"]*"(.*?)</li>', re.S)
_ITEM_LINK = re.compile(r'<h4><a href="(https://beetravel\.bg/tours/([a-z0-9-]+)/)"[^>]*>(.*?)</a>', re.S)
_ITEM_IMG = re.compile(r'<img[^>]*\bsrc="([^"]+)"')
_ITEM_PRICE = re.compile(r'woocommerce-Price-amount amount"><bdi>\s*([\d.,]+)')
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_PIN = re.compile(r'data-lat="(-?\d+\.\d+)"\s+data-long="(-?\d+\.\d+)"')
_MAIN_IMG = re.compile(r'<img[^>]*\bsrc="([^"]+)"[^>]*class="[^"]*wp-post-image')
_PRICE_TAB = re.compile(r'id="tab-price_tab"(.*?)(?:id="tab-location_tab"|$)', re.S)
_DESC_TAB = re.compile(r'id="tab-description"(.*?)id="tab-price_tab"', re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_EUR = re.compile(r"(\d{1,4}(?:\s*[.,]\s*\d{1,2})?)\s*€")
_CHILD = re.compile(r"(?:(?P<ord>едно|първо|1-во|второ|2-ро)\s+)?дете\s+(?:от\s+(?P<lo>\d+(?:[.,]\d+)?)\s*(?:г\.?\s*)?)?"
                    r"до\s+(?P<hi>\d+(?:[.,]\d+)?)\s*г.*?(?:(?P<free>безплатно)|(?P<pct>\d{1,3})\s*%)", re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _num(s: str) -> float:
    return float(re.sub(r"\s", "", s).replace(",", "."))


def board_code(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower())
    return next((code for key, code in BOARDS if key in t), "?")


def split_title(title: str) -> tuple[str, str | None]:
    """'Palm Wings Ephesus Beach Resort – Кушадасъ' -> (name, 'Kusadasi'); also 'Name- Town', 'Name -Town'."""
    t = _text(title)
    m = re.match(r"(.*?)\s*[–-]\s*([А-Яа-яЁё][А-Яа-яЁё .]*)$", t)
    if not m:
        return t, None
    town = m.group(2).strip()
    return m.group(1).strip(), TOWNS.get(town.lower(), town)


# ------------------------------------------------------------------ list ---

def parse_list(html: str) -> list[dict]:
    """Hotel cards in a category's product list: slug, url, name, town, from_pp_night, image."""
    block = _PRODUCTS.search(html or "")
    cards, seen = [], set()
    for item in _ITEM.findall(block.group(1) if block else ""):
        link = _ITEM_LINK.search(item)
        if not link or link.group(2) in seen:
            continue
        seen.add(link.group(2))
        name, town = split_title(link.group(3))
        price, img = _ITEM_PRICE.search(item), _ITEM_IMG.search(item)
        cards.append({"slug": link.group(2), "url": link.group(1), "name": name, "town": town,
                      "from_pp_night": _num(price.group(1)) if price else None,
                      "image": image_url(img.group(1), BASE) if img else None})
    return cards


# ---------------------------------------------------------------- detail ---

def _cells(row: str) -> list[str]:
    return [c for c in (_text(re.sub(r"<br\s*/?>", " ", x)) for x in _TD.findall(row)) if c]


def parse_prices(html: str) -> dict:
    """The price tab: periods [(start, end)], rooms [{room, board, prices[]}], basis, board, child rules."""
    tab = _PRICE_TAB.search(html or "")
    periods: list[tuple[str, str]] = []
    rooms, notes = [], []
    for row in _TR.findall(tab.group(1) if tab else ""):
        cells = _cells(row)
        if not cells:
            continue
        if not periods and len(cells) > 1 and all(len(_DATE.findall(c)) == 2 for c in cells[1:]):
            for c in cells[1:]:
                (d1, m1, y1), (d2, m2, y2) = _DATE.findall(c)
                periods.append((date(int(y1), int(m1), int(d1)).isoformat(), date(int(y2), int(m2), int(d2)).isoformat()))
            continue
        prices = [_EUR.fullmatch(c.replace(" €", "€")) or _EUR.fullmatch(c) for c in cells[1:]]
        if periods and len(cells) == len(periods) + 1 and all(prices):
            rooms.append({"room": cells[0], "board": board_code(cells[0]),
                          "prices": [_num(p.group(1)) for p in prices]})
        elif len(cells) == 1:
            notes.append(cells[0])
    joined = " ".join(notes)
    basis = "person" if re.search(r"на\s+чов", joined, re.I) else ("room" if re.search(r"на\s+стая|за\s+стая", joined, re.I) else None)
    board_line = next((n for n in notes if re.search(r"изхранване", n, re.I)), "")
    board = board_code(board_line) if board_line else "?"
    if board == "?":
        board = next((board_code(n) for n in notes if board_code(n) != "?"), "?")
    rules = []
    for n in notes:
        for m in _CHILD.finditer(n):
            o = (m.group("ord") or "").lower()
            slot = "one" if o in ("едно",) else 1 if o in ("първо", "1-во") else 2 if o in ("второ", "2-ро") else "any"
            rules.append({"slot": slot, "min_age": _num(m.group("lo")) if m.group("lo") else 0.0,
                          "max_age": _num(m.group("hi")), "pct": 0.0 if m.group("free") else float(m.group("pct")),
                          "text": n})
    return {"periods": periods, "rooms": rooms, "basis": basis, "board": board, "child_rules": rules}


def parse_detail(html: str) -> dict:
    """Name, town, stars, pin, photo, family facts and the price table of a hotel page."""
    h1 = _H1.search(html or "")
    name, town = split_title(h1.group(1)) if h1 else (None, None)
    pin, img = _PIN.search(html or ""), _MAIN_IMG.search(html or "")
    desc = _DESC_TAB.search(html or "")
    text = _text(desc.group(1) if desc else "").lower()
    stars = next((n for k, n in STARS.items() if k in text), None)
    fam: dict = {"verified": []}
    if "пясъчно-чакъл" in text or "пясък и чакъл" in text:
        fam["beach_type"] = "mixed"
    elif "пясъчен плаж" in text or "пясъчния плаж" in text:
        fam["sand_beach"] = True
    if "аквапарк" in text or "водни пързалки" in text:
        fam["aquapark"] = True
    if re.search(r"детски клуб|мини ?клуб|kids club", text):
        fam["kids_club"] = True
    if "детски басейн" in text or "зони за деца" in text:
        fam["kids_pool"] = True
    prices = parse_prices(html)
    for r in prices["child_rules"]:                        # facts the scorer already knows
        if r["pct"] == 0 and r["min_age"] == 0:
            key = "kids_free_max_age" if r["slot"] == "any" else "first_child_free_max_age"
            fam[key] = max(fam.get(key, 0.0), r["max_age"])
    return {"name": name, "town": town, "stars": stars,
            "lat": float(pin.group(1)) if pin else None, "lng": float(pin.group(2)) if pin else None,
            "image": image_url(img.group(1), BASE) if img else None, "family": fam, **prices}


# ----------------------------------------------------------------- price ---

def kids_share(rules: list[dict], ages: list[float]) -> list[float] | None:
    """Each child's price as a share of an adult's (0.0 = free), or None if a child fits no rule.
    'any' rules cover every child of that age; 'one' rules cover a single child; 1/2 = 1st/2nd child.
    Children are matched youngest first, each to the cheapest rule still open."""
    used: set[int] = set()
    out = []
    for i, age in enumerate(sorted(ages), 1):
        best = None
        for k, r in enumerate(rules):
            if not (r["min_age"] <= age <= r["max_age"]):
                continue
            if r["slot"] == "one" and k in used or isinstance(r["slot"], int) and r["slot"] != i:
                continue
            if best is None or r["pct"] < rules[best]["pct"]:
                best = k
        if best is None:
            return None
        if rules[best]["slot"] == "one":
            used.add(best)
        out.append(rules[best]["pct"] / 100)
    return out


def stay_price(room: dict, periods: list[tuple[str, str]], check_in: str, nights: int,
               adults: int, shares: list[float] | None, basis: str | None) -> float | None:
    """Total for the stay, night by night (a stay may cross periods). None if a night is unpriced."""
    total, d = 0.0, date.fromisoformat(check_in)
    for _ in range(nights):
        iso = d.isoformat()
        k = next((i for i, (a, b) in enumerate(periods) if a <= iso <= b), None)
        if k is None:
            return None
        p = room["prices"][k]
        total += p if basis == "room" else p * (adults + sum(shares or []))
        d += timedelta(days=1)
    return round(total, 2)


# ----------------------------------------------------------------- build ---

def kid_ages(cfg: dict, check_in: str, src: dict) -> list[float]:
    if src.get("child_ages"):
        return [float(a) for a in src["child_ages"]]
    from ..score import kids_age_on                # local import, as in flight_hotels
    return [float(kids_age_on(cfg, check_in))] * int(cfg["family"].get("kids", 2))


def to_hotel(card: dict, d: dict, page: dict) -> dict:
    town = d.get("town") or card.get("town")
    area = f"{town}, {page['region']}" if town and page.get("region") else page["area"]
    airport = page.get("airport")
    notes = [f"Auto-added from Bee Travel (beetravel.bg, Bulgaria), hotel only: book the direct flight "
             f"SKP→{airport or 'the nearby airport'} yourself.",
             "Price worked out from the hotel's 2027 price list (per person per night) and its child rules.",
             "Family facts (sand, aquapark, kids' club) are from the agency's description — confirm with the hotel."]
    return {
        "id": f"bee-{card['slug']}",
        "name": d.get("name") or card["name"],
        "stars": d.get("stars"),
        "season": page.get("season", "summer"),
        "area": area,
        "country": page.get("country", "TR"),
        "lat": d["lat"] if d.get("lat") is not None else page["lat"],
        "lng": d["lng"] if d.get("lng") is not None else page["lng"],
        "direct_flight_skp": True,
        "border": False,
        "kind": "hotel",
        "family": d.get("family") or {"verified": []},
        "image": d.get("image") or card.get("image"),
        "notes": " ".join(notes),
    }


def to_offer(hotel: dict, card: dict, d: dict, check_in: str, nights: int, cfg: dict, src: dict,
             today: date) -> dict | None:
    """Cheapest family room priced for 2 adults + the twins ("2+2"); else cheapest room for 2 ("2+0")."""
    if not d["rooms"] or not d["periods"]:
        return None
    adults = int(cfg["family"]["adults"])
    shares = kids_share(d["child_rules"], kid_ages(cfg, check_in, src))
    fam_rooms = [r for r in d["rooms"] if FAMILY_ROOM.search(r["room"])]
    priced = []
    if shares is not None and fam_rooms:
        priced = [(p, r, "2+2") for r in fam_rooms
                  if (p := stay_price(r, d["periods"], check_in, nights, adults, shares, d["basis"]))]
    if not priced:
        priced = [(p, r, "2+0") for r in d["rooms"]
                  if (p := stay_price(r, d["periods"], check_in, nights, adults, [], d["basis"]))]
    if not priced:
        return None                                  # check-in outside the price list's periods
    price, room, occ = min(priced, key=lambda x: x[0])
    board = room["board"] if room["board"] != "?" else d["board"]
    label = re.sub(r"\s*-\s*(ultra\s+)?all\s+inclusive.*$", "", room["room"], flags=re.I)
    if occ == "2+2":
        kids = "kids free" if not any(shares) else "kids at " + "/".join(f"{s:.0%}" for s in shares)
        room_txt = f"{label}, hotel only — flight not included; {kids} per the hotel's child rules"
    else:
        why = "no family room listed" if not fam_rooms else "child rules don't cover the twins' age"
        room_txt = f"{label}, hotel only — price for 2 adults ({why}; ask for the kids)"
    return {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": board,
        "room": room_txt,
        "occupancy": occ,
        "price_eur": price,
        "was_eur": None,                             # the 2027 lists carry no old price
        "discount_label": None,
        "valid_until": None,
    }


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("tr_more", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels: dict[str, dict] = {}
    offers: list[dict] = []
    for page in src.get("pages", []):
        try:
            cards = parse_list(s.get(page["url"]) or "")
            wanted = page.get("hotels")
            chosen = [c for c in cards if not wanted or c["slug"] in wanted][: int(page.get("max_hotels", src.get("max_hotels", 12)))]
            nights = int(page.get("nights", src.get("nights", 7)))
            dates = page.get("check_ins") or src.get("check_ins") or [page.get("check_in", src.get("check_in"))]
            priced = 0
            for card in chosen:
                d = parse_detail(s.get(card["url"]) or "")
                h = to_hotel(card, d, page)
                for check_in in dates:
                    if not check_in or check_in < today.isoformat():
                        continue
                    o = to_offer(h, card, d, check_in, nights, cfg, src, today)
                    if o:
                        offers.append(o)
                        priced += 1
                        hotels.setdefault(h["id"], h)
            log.info("Bee Travel %s: %d hotels, %d offers", page["area"], len(chosen), priced)
        except Blocked as e:
            log.warning("Bee Travel stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Bee Travel %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
