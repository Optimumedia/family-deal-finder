"""Family hotels in Halkidiki / Olympic Riviera / Thassos: the hotel's own price list, read per
room type and occupancy, with the half-board supplement and child policy applied.

Why not the hotels' own websites: on 2026-11-26 we checked ~25 family hotels from docs/data.json
(Porfi, Sousouras, Village Mare, Naias, Alea, Sun Beach, Poseidon Palace, Portes, Secret
Paradise, Acrotel, Anthemus, Lagomandra, Kamari Beach …) — home page, sitemap and the usual
/prices, /price-list, /cenovnik paths. None publishes a price list; they sell through WebHotelier
(excluded) or another booking engine. What the same small hotels DO publish is their owner's
price list on Grčka Info (grckainfo.com), a Serbian portal aimed at Balkan families: "These are
the official prices of property owner". So the configured pages are those hotel pages, in
English (/en/accommodation/<slug>/<id>/). robots.txt allows them (it disallows /api/, /login/,
/hotels/search/, /sr/search/ and code folders).

How a page reads (server-rendered HTML, no JavaScript needed):

    <h3 class="acc-name">Room - half board</h3> <p class="acc-guest">Adults: 2, Children: 2</p>
    <details class="detail-rate-table"> … <td>14 Apr 2027 – 31 May 2027</td> <td>150.00 €</td> …

Each room type comes in occupancy variants ("Adults: 2, Children: 2", "Adults: 3, Children: 0"),
each with its own nightly price. "Notes" (Reservation terms) says what a price is ("per room/per
night with breakfast", "per 2 persons/per night"), the half-board supplement ("Half board - 16 EUR
per day per adult, 15EUR per day per child (2-9.99 years old)"), and who counts as a child
("Children over 11.99 years are considered adults").

What an offer is
* 2+2: per room type, the smallest variant that takes 2 adults + 2 kids. Kids sit in child places
  unless the page says they count as adults at the twins' age on check-in (then 4 adult places
  are needed). Pages priced per person / per 2 persons never give a 2+2 price (how the kids are
  charged is a separate rule list) — those hotels give a 2+0 offer instead.
* Price = the sum of each night's published rate (a stay may cross two periods). A night with no
  rate drops the offer.
* Board: from the room name, else from the price note. A BB / room-only price plus a stated
  half-board supplement (or breakfast + dinner prices) becomes an HB total:
  supplement × nights × (adults + kids), each twin at the child rate whose age range covers them,
  free when a "Children 0-5,99 - free" rule covers them, else at the adult rate (errs high).
* Without a 2+2 variant the cheapest 2-adult variant is kept as a "2+0" offer.

Facts only: name, coordinates and photo (JSON-LD / og:image, hotlinked), amenity chips
(beachfront, half board, baby cot, playground), "From Beach : 100 m", free-child age limits,
tourist tax and minimum stay as notes. Text is never copied.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import date, timedelta
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from ..score import kids_age_on
from .pagetext import html_to_text, image_url, money

log = logging.getLogger(__name__)
SOURCE = "Grčka Info (hotel price list)"
BASE = "https://grckainfo.com"
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

_UNIT = re.compile(r'<div class="container[^"]*shadow-acc[^"]*" id="detail-unit-(\d+)">')
_GUESTS = re.compile(r"(?:Adults|Odrasli):\s*(\d+)\s*,\s*(?:Children|Deca):\s*(\d+)")
_PERIOD_EN = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(20\d{2})\s*[–-]\s*(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(20\d{2})")
_PERIOD_SR = re.compile(r"(\d{1,2})\.(\d{1,2})\.(20\d{2})\.?\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})")
_EUR = re.compile(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+)\s*€")
_NUM = r"(\d+(?:[.,]\d+)?)"
_MONEY = rf"{_NUM}\s*(?:EUR|€|eur)"


def _clean(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def _age_top(s: str) -> float:
    """'1,99' / '1.99' → 2 (an age limit read as 'younger than'); '12' → 12."""
    v = _f(s)
    return float(math.ceil(v)) if not v.is_integer() else v


# ------------------------------------------------------------------ page ---

def _ldjson(html: str) -> dict:
    for blob in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', html):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") in ("Hotel", "LodgingBusiness", "Accommodation", "Resort"):
            return d
    return {}


def _period(cell: str) -> tuple[date, date] | None:
    try:
        m = _PERIOD_EN.search(cell)
        if m:
            d1, b1, y1, d2, b2, y2 = m.groups()
            a, b = MONTHS.get(b1.lower()), MONTHS.get(b2.lower())
            if not a or not b:
                return None
            return date(int(y1), a, int(d1)), date(int(y2), b, int(d2))
        m = _PERIOD_SR.search(cell)
        if m:
            d1, m1, y1, d2, m2, y2 = map(int, m.groups())
            return date(y1, m1, d1), date(y2, m2, d2)
    except ValueError:
        return None
    return None


def _rates(block: str) -> list[dict]:
    out = []
    table = re.search(r'(?s)<details class="detail-rate-table">.*?<tbody>(.*?)</tbody>', block)
    for row in re.findall(r"(?s)<tr>(.*?)</tr>", table.group(1) if table else ""):
        cells = [_clean(c) for c in re.findall(r"(?s)<td[^>]*>(.*?)</td>", row)]
        if len(cells) < 2:
            continue
        per, amounts = _period(cells[0]), [money(x) for x in _EUR.findall(cells[1])]
        if not per or not amounts or per[1] < per[0]:
            continue                                   # "on request" or an unreadable period
        out.append({"from": per[0].isoformat(), "to": per[1].isoformat(), "night": amounts[-1]})
    return out


def parse_page(html: str) -> dict:
    """{'name','lat','lng','image','amenities','notes','beach_m','units':[{'id','name','adults','kids','rates'}]}"""
    ld = _ldjson(html)
    h1 = re.search(r"(?s)<h1[^>]*>(.*?)</h1>", html)
    starts = [(m.start(), m.group(1)) for m in _UNIT.finditer(html)]
    units = []
    for k, (pos, uid) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else html.find("</section>", pos)
        block = html[pos:end if end > 0 else len(html)]
        name = re.search(r'(?s)<h3 class="acc-name">(.*?)</h3>', block)
        guests = _GUESTS.search(block)
        if not name or not guests:
            continue
        units.append({"id": uid, "name": _clean(name.group(1)), "adults": int(guests.group(1)),
                      "kids": int(guests.group(2)), "rates": _rates(block)})
    i = html.find('class="detail-amenities"')
    seg = html[i:html.find("</section>", i)] if i >= 0 else ""
    amen = {_clean(s) for s in re.findall(r'(?s)loading="lazy">([^<]+)</span>', seg)}
    j = html.find('id="detail-policy"')
    notes = html_to_text(html[j:html.find("</section>", j)]) if j >= 0 else ""
    beach = re.search(r"From Beach\s*:\s*(\d+)\s*(k?m)\b", html_to_text(html))
    geo = ld.get("geo") or {}
    img = ld.get("image")
    if isinstance(img, list):
        img = img[0] if img else None
    if not img:
        og = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
        img = og.group(1) if og else None
    return {
        "name": _clean(h1.group(1)) if h1 else unescape(ld.get("name") or ""),
        "lat": float(geo["latitude"]) if geo.get("latitude") else None,
        "lng": float(geo["longitude"]) if geo.get("longitude") else None,
        "image": image_url(img, BASE) if img else None,
        "amenities": amen,
        "notes": notes,
        "beach_m": (int(beach.group(1)) * (1000 if beach.group(2) == "km" else 1)) if beach else None,
        "units": units,
    }


# ---------------------------------------------------------------- policy ---

def _bullets(notes: str) -> list[str]:
    return [" ".join(b.split()) for b in re.split(r"•|\n", notes) if b.strip()]


def _board_of(text: str) -> str | None:
    t = text.lower()
    if re.search(r"all[\s-]*inclusive|\bai\b", t):
        return "AI"
    if re.search(r"full board|\bfb\b", t):
        return "FB"
    if re.search(r"half board|\bhb\b|breakfast and dinner", t):
        return "HB"
    if re.search(r"breakfast|\bbb\b", t):
        return "BB"
    return None


def _child_rules(text: str, adult: float | None) -> list[dict]:
    """[{'lo','hi','price'}] from 'Children 6-11,99 - 15 EUR/per day', '15EUR per day per child (2-9.99
    years old)', 'Children 0-5,99 - free of charge', 'Children aged 6-11.99 have 50% discount'."""
    rules = []
    rng = rf"{_NUM}\s*(?:-|–|to)\s*{_NUM}"
    for m in re.finditer(rf"child\w*\s*(?:aged\s*)?\(?{rng}\)?\s*(?:years?\s*(?:old)?)?\s*(?:-|:)?\s*"
                         rf"(?:(free)|{_MONEY}|(?:have|has|get)?\s*(\d+)\s*%\s*discount)", text, re.I):
        lo, hi, free, eur, pct = m.groups()
        price = 0.0 if free else _f(eur) if eur else (adult * (1 - int(pct) / 100) if adult is not None else None)
        if price is not None:
            rules.append({"lo": _f(lo), "hi": _age_top(hi), "price": round(price, 2)})
    for m in re.finditer(rf"{_MONEY}\s*(?:/\s*)?(?:per\s+)?day\s*(?:/\s*)?per\s+child\s*\(\s*{rng}", text, re.I):
        eur, lo, hi = m.groups()
        rules.append({"lo": _f(lo), "hi": _age_top(hi), "price": _f(eur)})
    return rules


def _hb_supplement(bullets: list[str]) -> dict | None:
    """{'adult': €/day, 'rules': [...], 'text': short label} for a half-board supplement, or from
    separate breakfast + dinner prices; None when the page states neither."""
    for k, b in enumerate(bullets):
        if not re.search(r"half board|\bHB\b", b, re.I) or re.search(r"above prices|prices are", b, re.I):
            continue
        seg = b
        if not re.search(_MONEY, b, re.I):             # "Supplement Half Board" heading + bullets
            more = []
            for nxt in bullets[k + 1:k + 6]:
                if not re.search(r"child|adult|person", nxt, re.I):
                    break
                more.append(nxt)
            seg = " • ".join([b] + more)
        adult = (re.search(rf"adults?\s*(?:-|:)\s*{_MONEY}", seg, re.I)
                 or re.search(rf"{_MONEY}\s*(?:/\s*)?(?:per\s+)?(?:day\s*(?:/\s*)?)?(?:per\s+)?(?:person|adult)", seg, re.I)
                 or re.search(rf"{_MONEY}\s*(?:/\s*)?(?:per\s+)?(?:day\s*(?:/\s*)?)?per\s+(?:person|adult)", seg, re.I))
        if not adult:
            continue
        a = _f(adult.group(1))
        used = set(range(k, k + 1 + (seg.count(" • "))))
        return {"adult": a, "rules": _child_rules(seg, a), "text": f"half board {a:g} €/adult/day", "used": used}
    text = " ".join(bullets)
    bf = re.search(rf"breakfast\s*(?:-|:)\s*{_MONEY}", text, re.I)
    dn = re.search(rf"dinner\s*(?:-|:)\s*{_MONEY}", text, re.I)
    if bf and dn:
        a = _f(bf.group(1)) + _f(dn.group(1))
        meal = next((b for b in bullets if re.search(r"meal|breakfast|dinner", b, re.I) and re.search(r"child", b, re.I)), "")
        return {"adult": a, "rules": _child_rules(meal, a), "used": set(),
                "text": f"breakfast {_f(bf.group(1)):g} + dinner {_f(dn.group(1)):g} €/adult/day"}
    return None


def parse_policy(notes: str) -> dict:
    """What the 'Notes' box says about the prices (all fields None when not stated)."""
    bullets = _bullets(notes)
    hb = _hb_supplement(bullets)
    # the half-board rule list ("Children 0-5,99 - free of charge") is about meals, not the stay
    text = " ".join(b for i, b in enumerate(bullets) if not hb or i not in hb["used"])
    head = next((b for b in bullets if re.search(r"above prices|prices are", b, re.I)), "")
    basis = ("pair" if re.search(r"per\s+2\s+persons", head, re.I)
             else "person" if re.search(r"per\s+person", head, re.I) else "unit")
    child_max = None
    m = (re.search(rf"(?:children|child)\s+over\s+{_NUM}\s*years?[^.•]*?considered\s+adults?", text, re.I)
         or re.search(rf"all\s+persons\s+over\s+{_NUM}\s*years?[^.•]*?considered\s+adults?", text, re.I))
    if m:
        child_max = _age_top(m.group(1))
    free = (re.search(rf"children\s*:?\s*(?:aged\s*)?0\s*(?:-|–|to)\s*{_NUM}\s*(?:years?)?\s*(?:-|:)?\s*free", text, re.I)
            or re.search(rf"(?:children|baby|babies)\s*(?:aged\s*)?(?:up\s+to|until|0\s*(?:-|–))\s*{_NUM}\s*(?:years?)?[^.•]{{0,40}}?free", text, re.I))
    first = (re.search(rf"first\s+child\s+(?:until|up\s+to)\s+{_NUM}[^.•]{{0,40}}?free", text, re.I)
             or re.search(rf"1st\s+child\s+0\s*(?:-|–)\s*{_NUM}\s*years?\s*-\s*free", text, re.I))
    tax = re.search(rf"tourist\s+tax\s*\(\s*{_NUM}\s*€\s*per\s+day\s*/?\s*(?:per\s+)?room", text, re.I)
    min_stay = re.search(r"minimum\s+stay\s*(?:is\s*)?(\d{1,2})\s*nights", text, re.I)
    return {
        "basis": basis,
        "board": _board_of(head),
        "child_max": child_max,
        "kids_free_max_age": _age_top(free.group(1)) if free else None,
        "first_child_free_max_age": _age_top(first.group(1)) if first else None,
        "hb": hb,
        "meals_extra": bool(re.search(rf"breakfast\s*(?:-|:)\s*{_MONEY}", notes, re.I)),
        "tax_room_day": _f(tax.group(1)) if tax else None,
        "min_stay": int(min_stay.group(1)) if min_stay else None,
        "dynamic": bool(re.search(r"prices are dynamic", text, re.I)),
    }


# ---------------------------------------------------------------- offers ---

def unit_board(name: str, policy: dict) -> str:
    return _board_of(name) or policy["board"] or ("RO" if policy["meals_extra"] else "?")


def fits_family(u: dict, adults: int, kids: int, kids_are_adults: bool) -> bool:
    if kids_are_adults:
        return u["adults"] >= adults + kids
    return u["adults"] >= adults and u["adults"] + u["kids"] >= adults + kids


def _room_type(name: str) -> str:
    return " ".join(re.sub(r"\s*-\s*\d+\s*adults?\s*(?:\+\s*\d+\s*child\w*)?", "", name, flags=re.I).split())


def stay_price(rates: list[dict], check_in: date, nights: int) -> float | None:
    total = 0.0
    for i in range(nights):
        d = (check_in + timedelta(days=i)).isoformat()
        r = next((r for r in rates if r["from"] <= d <= r["to"]), None)
        if r is None:
            return None
        total += r["night"]
    return round(total, 2)


def kid_meal_price(hb: dict, age: float) -> tuple[float, str]:
    for r in hb["rules"]:
        if r["lo"] <= age < r["hi"]:
            return r["price"], ("free" if r["price"] == 0 else f"{r['price']:g} €")
    return hb["adult"], "adult rate (no child rate for this age)"


def hotel_offers(parsed: dict, page: dict, cfg: dict, today: date) -> tuple[dict | None, list[dict]]:
    policy = parse_policy(parsed["notes"])
    fam = cfg["family"]
    adults, kids = fam["adults"], fam["kids"]
    nights = int(page.get("nights", 7))
    check_ins = [date.fromisoformat(str(c)) for c in (page.get("check_ins") or [page.get("check_in")]) if c]
    max_rooms = int(page.get("max_rooms", 3))
    hid = f"gih-{page.get('id') or re.search(r'/(\d+)/?$', page['url']).group(1)}"
    am = parsed["amenities"]
    family: dict = {"verified": []}
    if "Accommodation on the beach" in am:
        family["beachfront"] = True
    if parsed["beach_m"] is not None:
        family["beach_m"] = parsed["beach_m"]
    if "Half board" in am or policy["board"] == "HB" or policy["hb"]:
        family["half_board"] = True
    if any("baby cot" in a.lower() for a in am) or re.search(r"baby\s+cot", parsed["notes"], re.I):
        family["cots_mentioned"] = True
    if "Playground" in am:
        family["playground"] = True
    for k in ("kids_free_max_age", "first_child_free_max_age"):
        if policy[k] is not None:
            family[k] = policy[k]
    notes = ["Owner's price list published on Grčka Info"
             + {"unit": " (per room per night)", "pair": " (per 2 persons per night)",
                "person": " (per person per night)"}[policy["basis"]] + "."]
    if policy["tax_room_day"]:
        notes.append(f"Tourist tax {policy['tax_room_day']:g} €/room/night extra.")
    if policy["min_stay"]:
        notes.append(f"Minimum stay {policy['min_stay']} nights (some periods).")
    if policy["child_max"] is not None:
        notes.append(f"Children count as adults from {policy['child_max']:g}.")
    if policy["dynamic"]:
        notes.append("The page says its prices are dynamic: confirm before booking.")
    hotel = {
        "id": hid, "name": page.get("name") or parsed["name"], "stars": page.get("stars"),
        "season": page.get("season", "summer"), "area": page["area"], "country": page.get("country", "GR"),
        "lat": parsed["lat"] or page["lat"], "lng": parsed["lng"] or page["lng"],
        "direct_flight_skp": bool(page.get("direct_flight_skp", False)), "border": page.get("border", True),
        "kind": page.get("kind", "hotel"), "family": family, "image": parsed["image"], "notes": " ".join(notes),
    }
    offers = []
    for ci in check_ins:
        if ci < today:
            continue
        age = kids_age_on(cfg, ci)
        kids_adult = policy["child_max"] is not None and age >= policy["child_max"]
        priced = [u for u in parsed["units"] if u["rates"]]
        family_units: list[dict] = []
        if policy["basis"] == "unit":
            groups: dict[str, list[dict]] = {}
            for u in priced:
                if fits_family(u, adults, kids, kids_adult):
                    groups.setdefault(_room_type(u["name"]), []).append(u)
            for vs in groups.values():
                vs.sort(key=lambda v: (v["adults"] + v["kids"], min(r["night"] for r in v["rates"])))
                family_units.append(vs[0])
        rows = []
        for u in family_units:
            p = stay_price(u["rates"], ci, nights)
            if p is not None:
                rows.append((u, p, "2+2"))
        if not rows:                                   # no family price: cheapest room for 2 adults
            mult = 2 if policy["basis"] == "person" else 1
            pairs = [(u, stay_price(u["rates"], ci, nights)) for u in priced
                     if (u["adults"] >= adults if policy["basis"] != "unit" else u["adults"] == adults and u["kids"] == 0)]
            pairs = [(u, p * mult) for u, p in pairs if p is not None]
            rows = [(u, p, "2+0") for u, p in sorted(pairs, key=lambda x: x[1])[:1]]
        made = []
        for u, room_total, occ in rows:
            board = unit_board(u["name"], policy)
            price, label = room_total, u["name"]
            hb = policy["hb"]
            if board in ("BB", "RO") and hb:
                eaters = adults + (kids if occ == "2+2" else 0)
                kid_p, kid_txt = kid_meal_price(hb, age) if occ == "2+2" else (0.0, "")
                supp = (hb["adult"] * adults + (kid_p * kids if occ == "2+2" else 0)) * nights
                price = round(room_total + supp, 2)
                board = "HB"
                label = (f"{u['name']} + {hb['text']}" + (f", kids {kid_txt}" if occ == "2+2" else "")
                         + f" ({eaters} people)")
            made.append({
                "hotel": hid, "source": SOURCE, "url": page["url"], "seen": today.isoformat(),
                "check_in": ci.isoformat(), "nights": nights, "board": board,
                "room": f"{label} [{u['adults']} adults + {u['kids']} children places]",
                "occupancy": occ, "price_eur": price, "was_eur": None, "discount_label": None,
                "valid_until": None,
            })
        offers.extend(sorted(made, key=lambda o: o["price_eur"])[:max_rooms])
    return (hotel if offers else None), offers


def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("gr_hotel_prices", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    defaults = {k: src[k] for k in ("nights", "check_in", "check_ins", "season", "country", "max_rooms") if k in src}
    hotels, offers = [], []
    for page in src.get("pages", []):
        page = {**defaults, **page}
        try:
            html = s.get(page["url"])
            if not html:
                log.warning("Grčka Info hotel page gone: %s", page["url"])
                continue
            h, o = hotel_offers(parse_page(html), page, cfg, today)
            if h:
                hotels.append(h)
                offers.extend(o)
            log.info("Grčka Info %s: %d offers", page.get("name") or page["url"], len(o))
        except Blocked as e:
            log.warning("Grčka Info stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError, KeyError) as e:
            log.warning("Grčka Info %s skipped: %s", page["url"], e)
    return hotels, offers
