"""Hotel-only summer prices near direct-flight airports from Skopje (relaxo.bg).

Why hotel-only: the owner's summer rule (26.11.2026) accepts a hotel without a package as long as
a DIRECT flight from SKP lands nearby; the parents book that flight themselves. So every hotel
here is stored with `direct_flight_skp = True`, `border = False`, and the arrival airport from the
page config goes into the notes (trips/flights.py adds the transfer distance on its own).

The source: Relaxo.bg, a licensed Sofia tour operator (РК-01-8418). Its Turkish "Хотели в Турция"
pages sell rooms with own transport ("Собствен транспорт"), i.e. hotel only. robots.txt
(checked 26.11.2026) disallows only /locale/, /go/ (and /ai/ for Googlebot):

    User-agent: *
    Allow: /
    Disallow: /locale/
    Disallow: /go/

Three kinds of page, all plain server-rendered HTML:
1. a resort list, /oferti-za/<resort> (e.g. belek, lara, side, alaniia, kushadasa, cheshme,
   bodrum): one <article class="tour-card"> per hotel with name, stars, board, "Собствен
   транспорт", photo and a "from" price per person per night (some cards have none);
2. a hotel page, /oferta/<slug>: Google-Maps pin (!2d<lng>!3d<lat>), amenity chips
   ("Пясъчен плаж" = sandy beach, "Първа линия" = beachfront, "Миниклуб", "Детски басейн"),
   a guest rating in its JSON-LD, the bookable window ("Настаняване 15.05–30.09.2027") and the
   promotion's end ("Само до 28.11");
3. the hotel page's own GET search form, /oferta/<slug>/rezultati?date_from&date_to&rooms[0]…
   with 2 adults + 2 children and their ages: one `rx-row` per room type with data-price (the
   TOTAL for the stay and the whole party), data-room-name, data-board, data-available, and the
   price without early booking ("цената на хотела без ранни записвания (3461.54 €)").

Offers: per hotel and check-in, the cheapest available room for 2 adults + 2 children →
occupancy "2+2" (the row header must echo "2 възрастни + 2 деца", else it is stored as "2+0").
Cost per run: 1 list page per resort + 2 pages per priced hotel (detail + search), capped by
`max_hotels` per page (cheapest "from" price first, or an explicit `hotels` slug list).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from html import unescape
from urllib.parse import urlencode

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://relaxo.bg"
SOURCE = "Relaxo (hotel only)"

# Phrases (checked first, in this order) and short codes (whole words).
BOARD_PHRASES = [("ultra all inclusive", "AI"), ("all inclusive", "AI"), ("пълен пансион", "FB"),
                 ("full board", "FB"), ("полупансион", "HB"), ("закуска и вечеря", "HB"), ("half board", "HB"),
                 ("закуска", "BB"), ("bed and breakfast", "BB"), ("само нощувка", "RO"), ("room only", "RO")]
BOARD_CODES = {"uai": "AI", "hcai": "AI", "luai": "AI", "lai": "AI", "pai": "AI", "24ai": "AI", "ai": "AI",
               "fb": "FB", "hb": "HB", "bb": "BB", "ro": "RO"}
OWN_TRANSPORT = "собствен транспорт"

_ART = re.compile(r'<article class="tour-card')
_HREF = re.compile(r'href="(https://relaxo\.bg/oferta/([a-z0-9-]+))"')
_TITLE = re.compile(r'tour-card-title[^>]*>\s*<a[^>]*>(.*?)</a>', re.S)
_STARS = re.compile(r'aria-label="(\d)\s*звезд')
_FROM = re.compile(r'tour-card-price-current">.*?(\d[\d\s.,]*)\s*€', re.S)
_BASIS = re.compile(r'tour-card-price-basis">\s*([^<]+?)\s*<')
_META = re.compile(r'<span class="tour-card-meta-item[^"]*"[^>]*title="([^"]+)"[^>]*>(.*?)</span>\s*(?=<span class="tour-card-meta-item|</div>)', re.S)
_BADGE = re.compile(r'<span class="tour-badge[^"]*">\s*([^<]+?)\s*</span>')
_IMG = re.compile(r'<img[^>]*?\bsrc="([^"]+)"')

_PIN = re.compile(r"!2d(-?\d+\.\d+)!3d(-?\d+\.\d+)")
_CHIP = re.compile(r'<span class="amen-chip[^"]*">\s*(?:<i[^>]*></i>)?\s*([^<]+?)\s*<', re.S)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_WINDOW = re.compile(r"Настаняване\s*(\d{1,2})\.(\d{1,2})\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")
_MIN_NIGHTS = re.compile(r"Поне\s*(\d{1,2})\s*нощувк")
_UNTIL = re.compile(r'bf-block-until">\s*Само до\s*(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?')
_PROMO_WORD = re.compile(r'bf-block-word">\s*([^<]+?)\s*<')

_ROW = re.compile(r'<div class="rx-row"(.*?)(?=<div class="rx-row"|<div class="rx-section-header"|$)', re.S)
_ATTR = re.compile(r'data-([a-z-]+)="([^"]*)"')
_SECTION = re.compile(r'<div class="rx-section-header">(.*?)</div>', re.S)
_WAS = re.compile(r"без ранни записвания\s*\(\s*([\d.,]+)\s*€")
_OLD = re.compile(r'rx-price-old">\s*([\d.,]+)\s*€')
_PCT = re.compile(r'rx-badge-discount">[^<\d]*(\d+)\s*%')
_LOW30 = re.compile(r"Най-ниска цена за 30 дни:\s*([\d.,]+)\s*€")
_ROW_BADGE = re.compile(r'aria-label="([^":]+):\s*обща отстъпка\s*(\d+)%')
_EB = re.compile(r"отстъпка\s*(\d+)%\s*\(Early Booking\)", re.I)
_CHILD = re.compile(r'<div class="rx-child-info">(.*?)</div>', re.S)
_CHILD_RULE = re.compile(r"(\d)-(?:во|ро|то)\s*дете\s*\(\s*0\s*[–-]\s*(\d{1,2})(?:[.,]99)?\s*г\.?\s*\)\s*(БЕЗПЛАТНО|[\d.,]+\s*%)", re.I)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<svg.*?</svg>|<[^>]+>", " ", s, flags=re.S))).strip()


def _num(s: str) -> float:
    s = re.sub(r"\s", "", s).rstrip(".,")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):
        return float(re.sub(r"[.,]", "", s))
    return float(s.replace(",", "."))


def board_code(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower()).strip()
    for key, code in BOARD_PHRASES:
        if key in t:
            return code
    return next((BOARD_CODES[w] for w in re.findall(r"[a-z0-9]+", t) if w in BOARD_CODES), "?")


# ------------------------------------------------------------------ list ---

def parse_list(html: str) -> list[dict]:
    """Hotel cards on a resort page: slug, url, name, stars, from_pp_night, board, own_transport…"""
    cards, seen = [], set()
    for block in _ART.split(html)[1:]:
        block = block.split("</article>", 1)[0]
        href, title = _HREF.search(block), _TITLE.search(block)
        if not href or not title or href.group(2) in seen:
            continue
        seen.add(href.group(2))
        meta = {k: _text(v) for k, v in _META.findall(block)}
        board_txt = meta.get("Изхранване", "")
        transport = meta.get("Транспорт", "")
        price = _FROM.search(block)
        basis = _BASIS.search(block)
        stars = _STARS.search(block)
        img = _IMG.search(block)
        cards.append({
            "slug": href.group(2),
            "url": href.group(1),
            "name": _text(title.group(1)),
            "stars": int(stars.group(1)) if stars else None,
            "from_pp_night": _num(price.group(1)) if price else None,
            "basis": basis.group(1).strip() if basis else "",
            "board_text": board_txt,
            "board": board_code(board_txt),
            "own_transport": OWN_TRANSPORT in transport.lower(),
            "location": meta.get("Локация", ""),
            "badge": (_BADGE.search(block).group(1).strip() if _BADGE.search(block) else ""),
            "image": image_url(img.group(1), BASE) if img else None,
        })
    return cards


def pick(cards: list[dict], page: dict, default_max: int) -> list[dict]:
    """The hotels to price on one page: an explicit `hotels` slug list, else the `max_hotels`
    cheapest own-transport cards that show a "from" price."""
    own = [c for c in cards if c["own_transport"]]
    wanted = page.get("hotels")
    if wanted:
        by = {c["slug"]: c for c in own}
        return [by[s] for s in wanted if s in by]
    priced = sorted((c for c in own if c["from_pp_night"]), key=lambda c: c["from_pp_night"])
    return priced[: int(page.get("max_hotels", default_max))]


# ---------------------------------------------------------------- detail ---

def _ld_objects(html: str) -> list[dict]:
    out = []
    for raw in _LD.findall(html):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        out += obj if isinstance(obj, list) else [obj]
    return out


def parse_detail(html: str, today: date) -> dict:
    """Pin, beach and kids' facts, rating, bookable window and promotion end of a hotel page."""
    pin = _PIN.search(html)
    chips = {_text(c).lower() for c in _CHIP.findall(html)}
    fam: dict = {"verified": []}
    if any("пясъч" in c and ("чакъл" in c or "камен" in c) for c in chips):
        fam["beach_type"] = "mixed"
    elif any("пясъч" in c for c in chips):
        fam["sand_beach"] = True
    elif any(("чакъл" in c or "камен" in c) and "плаж" in c for c in chips):
        fam["sand_beach"] = False
    if "първа линия" in chips:
        fam["beachfront"] = True
    if "миниклуб" in chips or "мини клуб" in chips:
        fam["kids_club"] = True
    if "детски басейн" in chips:
        fam["kids_pool"] = True
    if "анимация" in chips:
        fam["animation"] = True
    image = None
    for obj in _ld_objects(html):
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        r = obj.get("aggregateRating") or {}
        if "Hotel" in types and r.get("ratingValue"):
            fam["ratings"] = [{"source": "Relaxo.bg", "score": float(r["ratingValue"]),
                               "scale": float(r.get("bestRating") or 5),
                               "count": int(r["reviewCount"]) if r.get("reviewCount") else None}]
        if "Product" in types and obj.get("image"):
            imgs = obj["image"] if isinstance(obj["image"], list) else [obj["image"]]
            image = image_url(imgs[0], BASE)
    window = _WINDOW.search(html)
    season = None
    if window:
        d1, m1, d2, m2, y = (int(x) for x in window.groups())
        season = (date(y, m1, d1).isoformat(), date(y, m2, d2).isoformat())
    until = _UNTIL.search(html)
    valid = None
    if until:
        d, m, y = until.groups()
        v = date(int(y) if y else today.year, int(m), int(d))
        if not y and v < today:
            v = v.replace(year=today.year + 1)
        valid = v.isoformat()
    word = _PROMO_WORD.search(html)
    mn = _MIN_NIGHTS.search(html)
    return {
        "lat": float(pin.group(2)) if pin else None,
        "lng": float(pin.group(1)) if pin else None,
        "family": fam,
        "image": image,
        "season": season,
        "min_nights": int(mn.group(1)) if mn else None,
        "promo": word.group(1).strip() if word and until else None,
        "promo_until": valid,
    }


# --------------------------------------------------------------- results ---

def results_url(hotel_url: str, check_in: str, nights: int, adults: int, ages: list[int]) -> str:
    out = (date.fromisoformat(check_in) + timedelta(days=nights)).isoformat()
    q = urlencode([("date_from", check_in), ("date_to", out), ("rooms_count", 1),
                   ("rooms[0][adults]", adults), ("rooms[0][children]", len(ages)),
                   ("rooms[0][child_ages]", ",".join(str(a) for a in ages))])
    return f"{hotel_url.rstrip('/')}/rezultati?{q}"


def parse_results(html: str) -> dict:
    """Rooms priced for the searched party: {party, adults, children, child_rules, rows[...]}."""
    sec = _SECTION.search(html)
    party = _text(sec.group(1)) if sec else ""
    pa = re.search(r"(\d+)\s*възрастни(?:\s*\+\s*(\d+)\s*деца)?", party)
    child = _CHILD.search(html)
    rules = []
    for n, hi, what in _CHILD_RULE.findall(_text(child.group(1)) if child else ""):
        rules.append({"child": int(n), "max_age": int(hi), "free": what.upper().startswith("БЕЗПЛАТ"),
                      "text": what.strip()})
    rows = []
    for attrs, body in ((m.group(1).split(">", 1)[0], m.group(1)) for m in _ROW.finditer(html)):
        a = dict(_ATTR.findall(attrs))
        if "price" not in a:
            continue
        was = _WAS.search(body) or _OLD.search(body)
        low, badge, eb = _LOW30.search(body), _ROW_BADGE.search(body), _EB.search(body) or _PCT.search(body)
        rows.append({
            "room": unescape(a.get("room-name", "")).strip(),
            "board_text": unescape(a.get("board", "")).strip(),
            "board": board_code(unescape(a.get("board", ""))),
            "price": _num(a["price"]),
            "available": a.get("available") == "1",
            "was": _num(was.group(1)) if was else None,
            "low30": _num(low.group(1)) if low else None,
            "badge": f"{badge.group(1).strip()} -{badge.group(2)}%" if badge else None,
            "early_booking_pct": int(eb.group(1)) if eb else None,
        })
    return {"party": party, "adults": int(pa.group(1)) if pa else None,
            "children": int(pa.group(2) or 0) if pa else None, "child_rules": rules, "rows": rows}


# ----------------------------------------------------------------- build ---

def kid_ages(cfg: dict, check_in: str, src: dict) -> list[int]:
    if src.get("child_ages"):
        return [int(a) for a in src["child_ages"]]
    from ..score import kids_age_on                # local import: score is heavy and imports nothing from here
    n = int(cfg["family"].get("kids", 2))
    return [int(kids_age_on(cfg, check_in))] * n


def to_hotel(card: dict, detail: dict | None, page: dict) -> dict:
    d = detail or {}
    airport = page.get("airport")
    fam = dict(d.get("family") or {"verified": []})
    notes = [f"Auto-added from Relaxo.bg (Sofia), hotel only: book the direct flight SKP→"
             f"{airport or 'the nearby airport'} yourself."]
    if d.get("season"):
        notes.append(f"Bookable {d['season'][0]} to {d['season'][1]}"
                     + (f", at least {d['min_nights']} nights." if d.get("min_nights") else "."))
    notes.append("Family facts (sand, beachfront, kids' club) are the agency's amenity list — confirm with the hotel.")
    return {
        "id": f"rx-{card['slug']}",
        "name": card["name"],
        "stars": card.get("stars"),
        "season": page.get("season", "summer"),
        "area": page["area"],
        "country": page.get("country", "TR"),
        "lat": d.get("lat") if d.get("lat") is not None else page["lat"],
        "lng": d.get("lng") if d.get("lng") is not None else page["lng"],
        "direct_flight_skp": True,
        "border": False,
        "kind": "hotel",
        "family": fam,
        "image": d.get("image") or card.get("image"),
        "notes": " ".join(notes),
    }


def to_offer(hotel: dict, card: dict, res: dict, detail: dict | None, check_in: str, nights: int,
             search_url: str, cfg: dict, today: date) -> dict | None:
    rows = [r for r in res["rows"] if r["available"] and r["price"] > 0]
    if not rows:
        return None
    r = min(rows, key=lambda x: x["price"])
    kids = int(cfg["family"].get("kids", 2))
    family = res.get("adults") == cfg["family"]["adults"] and res.get("children") == kids
    for rule in res.get("child_rules", []):                       # facts for scoring kids' cost
        key = "first_child_free_max_age" if rule["child"] == 1 else "kids_free_max_age"
        if rule["free"]:
            hotel["family"].setdefault(key, float(rule["max_age"]))
    label = r.get("badge")
    if not label and r.get("early_booking_pct"):
        label = f"Early booking -{r['early_booking_pct']}%"
    room = f"{r['room'].title()} ({r['board_text'].lower()}), hotel only — flight not included"
    if r.get("low30"):
        room += f"; lowest in the last 30 days €{r['low30']:,.2f}"
    return {
        "hotel": hotel["id"],
        "source": SOURCE,
        "url": search_url if family else card["url"],
        "seen": today.isoformat(),
        "check_in": check_in,
        "nights": nights,
        "board": r["board"] if r["board"] != "?" else card.get("board", "?"),
        "room": room,
        "occupancy": "2+2" if family else "2+0",
        "price_eur": round(r["price"], 2),
        "was_eur": round(r["was"], 2) if r.get("was") and r["was"] > r["price"] else None,
        "discount_label": label,
        "valid_until": (detail or {}).get("promo_until") if label and not label.startswith("Early") else None,
    }


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("flight_hotels", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    adults = cfg["family"]["adults"]
    hotels: dict[str, dict] = {}
    offers: list[dict] = []
    for page in src.get("pages", []):
        try:
            cards = parse_list(s.get(page["url"]) or "")
            chosen = pick(cards, page, int(src.get("max_hotels", 5)))
            nights = int(page.get("nights", src.get("nights", 7)))
            dates = page.get("check_ins") or src.get("check_ins") or [page.get("check_in", src.get("check_in"))]
            priced = 0
            for card in chosen:
                detail = parse_detail(s.get(card["url"]) or "", today) if src.get("detail", True) else None
                h = to_hotel(card, detail, page)
                for check_in in dates:
                    if not check_in or check_in < today.isoformat():
                        continue
                    if detail and detail.get("season") and not (detail["season"][0] <= check_in <= detail["season"][1]):
                        continue                      # outside the hotel's bookable window
                    url = results_url(card["url"], check_in, nights, adults, kid_ages(cfg, check_in, src))
                    o = to_offer(h, card, parse_results(s.get(url) or ""), detail, check_in, nights, url, cfg, today)
                    if o:
                        offers.append(o)
                        priced += 1
                        hotels.setdefault(h["id"], h)
            log.info("Relaxo %s: %d hotel cards, %d chosen, %d offers", page["area"], len(cards), len(chosen), priced)
        except Blocked as e:
            log.warning("Relaxo stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Relaxo %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
