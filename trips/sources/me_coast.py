"""Montenegro's coast (Ulcinj, Dobre Vode, Sutomore, Bar, Petrovac, Bečići, Rafailovići) via Plan A Travel.

Plan A Travel (planatravel.rs, Belgrade / Velika Plana, licence OTP 222/2021) sells Montenegrin hotels
"sopstveni prevoz" (own transport: you drive, you pay the hotel stay). Each hotel page carries the
hotel's 2027 price list as a plain HTML table ("Cenovnik br.1, 05.11.2026."), with the child
reductions and board supplements written out underneath. robots.txt (checked 2026-11-28) only blocks
Joomla system folders (/administrator/, /api/, /components/, /media/, /modules/ …); the area and hotel
pages we read are allowed.

How a page reads:

    HOTEL PALAS **** / Petrovac            cena po osobi i danu u €   (per person per night)
    Smeštaj | Usluga | Broj osoba | 01.04.-31.05. | 01.06.-30.06. | 01.07.-31.08. | …
    Soba 1/2; Soba 1/2+1 | PP | 2+0; 2+1; 3+0 | 52 | 72 | 90 | …
    Popusti | … Popust za decu u pratnji dve odrasle osobe: … Dvoje dece od 2 do 12 godina na
              pomoćnom ležaju (dele ležaj) u 1/2+1 sobi - 50% …
    Doplate | Doplata za polupansion 14 eura dnevno … deca od 2 do 12 godina - 50% popusta na doplatu

Some tables are priced per person for a fixed stay instead ("cena za 9 polupansiona po osobi", a
"Broj noćenja 9" row and bus-departure periods 08.06-17.06., 17.06.-26.06. …): then an offer is that
stay, at the period that contains the page's check-in.

What an offer is
* 2+2 only when the page says how two small kids are charged with two adults: a "dvoje dece …"
  rule (two kids sharing the extra bed, a coefficient like "koeficjent obračuna je 2,8", or an
  early-booking "dvoje dece … GRATIS"), or a room that takes 4+ people plus a kids' rule for the
  twins' age ("Deca od 2 do 12 godina - 50% popusta", "u sopstvenom plaća 70%"). When several rules
  fit, the dearest one is used (errs high). Rules for kids with ONE adult, and rules for the 4th / 5th
  person, are ignored. Without a 2+2 rule the cheapest room gives a "2+0" offer (2 × per person).
* Board: PP → HB, PA → FB, ND → BB, AL/ALL/UAI → AI, NA → SC. A ND (B&B) row plus a stated
  half-board supplement becomes an HB price (supplement × nights per adult, kids at the stated
  share of it, else full).
* Early booking "Rani booking - 15% popusta do 31.12.2026 (… popust uključen u cenu)" gives
  was_eur, the discount label and valid_until. An early-booking kids-free rule is used only until
  that date.

Area listing pages tag hotels whose new price list is up with a "leto 2027" sticker. With
`only_stickered = true` (default) we read only those hotel pages, so a run costs one request per
area plus one per priced hotel (about 15 on 2026-11-28). Facts kept: name, stars, og:image
(hotlinked), sandy / pebble beach and beach distance as the page states them. No text is copied.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from html import unescape
from urllib.parse import urljoin

from ..http import Blocked, PoliteSession, Unavailable
from ..score import kids_age_on
from .pagetext import image_url

log = logging.getLogger(__name__)
BASE = "https://www.planatravel.rs"
SOURCE = "Plan A Travel (Montenegro)"

BOARDS = {"PP": "HB", "PA": "FB", "ND": "BB", "AL": "AI", "ALL": "AI", "AI": "AI", "UAI": "AI", "NA": "SC"}
_KID = re.compile(r"\b(dete|deca|dece|deteta|dijete|djeca|djece)\b", re.I)
_ONE_ADULT = re.compile(r"jedne odrasle|1 odrasl|jednom odrasl|jednu odrasl|jednom punoplate|jedne punoplate"
                        r"|jedna odrasla", re.I)
_TWO_ADULTS = re.compile(r"dve odrasle|dvije odrasle|2 odrasl|dve punoplate|2 punoplate|dvoje odraslih", re.I)
_POSITION = re.compile(r"\b(treća|četvrta|peta|treca|cetvrta)\s+osoba|kao\s+(peta|četvrta|treća)", re.I)
_RANGE = re.compile(r"(\d{1,2})\.(\d{1,2})\.?\s*[-–]?\s*(\d{1,2})\.(\d{1,2})\.?")
_HINT = re.compile(r"\bu\s+(\d+\s*/\s*\d+(?:\s*\+\s*\d+)?|0?\d+(?:\+\d+)?\s*app\b|standard|superior|premium|family"
                   r"|porodičn\w*|duplex)", re.I)


def _clean(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>|</p>", " ", s)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _num(s: str) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", s.replace(" ", ""))
    return float(m.group(0).replace(",", ".")) if m else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.lower())


# ------------------------------------------------------------------ listing page
def parse_list(html: str) -> list[dict]:
    """Hotel cards on an area page: url, name, stars, '2027' sticker, beach distance."""
    cards = []
    for block in (html or "").split('<article class="hotel-card')[1:]:
        href = re.search(r'<h2 class="pt-hotel-card__title">\s*<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not href:
            continue
        sticker = re.search(r'stiker-slika">([^<]*)<', block)
        stars = re.search(r'pt-hotel-card__stars[^>]*>([★]+)<', block)
        beach = re.search(r"Plaža\s+(\d+)\s*m\b", block)
        cards.append({
            "url": urljoin(BASE, unescape(href.group(1))),
            "name": _clean(href.group(2)),
            "stars": len(stars.group(1)) if stars else None,
            "sticker": sticker.group(1).strip() if sticker else "",
            "beach_m": int(beach.group(1)) if beach else None,
        })
    return cards


# ------------------------------------------------------------------ hotel page
def _rows(table: str) -> list[list[str]]:
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        out.append([c for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, re.S)])
    return out


def _periods(cell: str, year: int) -> list[tuple[date, date]]:
    out = []
    for d1, m1, d2, m2 in _RANGE.findall(_clean(cell)):
        try:
            out.append((date(year, int(m1), int(d1)), date(year, int(m2), int(d2))))
        except ValueError:
            pass
    return out


def parse_rules(text: str) -> list[dict]:
    """Child reductions with two adults, from the 'Popusti' cell (already split into lines).
    Each rule: count (1, 2 or None = each child), lo/hi age (hi exclusive), share of the adult price
    the child pays (0 = free), coef (total persons-equivalent for 2+2, if stated) and a room hint."""
    rules, ctx = [], "two"
    for line in re.split(r"\n+", text):
        if _ONE_ADULT.search(line) and not _TWO_ADULTS.search(line):
            ctx = "one"
            continue
        if _TWO_ADULTS.search(line):
            ctx = "two"
        if ctx == "one":
            continue
        for clause in re.split(r";", line):
            if not _KID.search(clause) or _ONE_ADULT.search(clause) or _POSITION.search(clause):
                continue
            if re.search(r"doplat", clause, re.I):          # a discount on the meal supplement
                continue
            r = _rule(clause)
            if r:
                rules.append(r)
    return rules


def _rule(clause: str) -> dict | None:
    c = clause.lower()
    m = (re.search(r"od\s*(\d+)\s*(?:-|do)\s*(\d+)", c) or re.search(r"\b(\d+)\s*-\s*(\d+)\s*god", c))
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
    elif (m := re.search(r"(?:do|mla[dđ]\w*\s+od)\s*(\d+)\s*god", c)):
        lo, hi = 0.0, float(m.group(1))
    else:
        return None
    count = 2 if re.search(r"dvoje\s+de|dvoje\s+dje|dva\s+deteta|2\s+dece", c) else (
        1 if re.search(r"\b(jedno\s+)?(dete|dijete)\b", c) and not re.search(r"\bdeca\b|\bdjeca\b", c) else None)
    coef = re.search(r"koefici?jent\w*\s*(?:obračuna\s*)?(?:je\s*)?(\d[.,]\d+)|(\d[.,]\d+)\s*koefici?jent", c)
    coef_v = float((coef.group(1) or coef.group(2)).replace(",", ".")) if coef else None
    if re.search(r"gratis|besplatn", c):
        share = 0.0
    elif (pays := re.findall(r"plaća\w*\s*(\d+)\s*%", c)):
        share = max(int(p) for p in pays) / 100          # "u sopstvenom plaća 70%" — dearer bed wins
    elif "nema popust" in c:
        share = 1.0
    elif (pct := re.findall(r"(\d+)\s*%", c)):
        share = 1 - max(int(p) for p in pct) / 100 if count != 2 or not coef_v else None
    elif coef_v:
        share = None
    else:
        return None
    hint = _HINT.search(clause)
    return {"count": count, "lo": lo, "hi": hi, "share": share, "coef": coef_v,
            "hint": _norm(hint.group(1)) if hint else None, "text": " ".join(clause.split())[:120]}


def _cell_lines(cell: str) -> str:
    cell = re.sub(r"(?i)<br\s*/?>|</p>", "\n", cell)
    return "\n".join(" ".join(unescape(re.sub(r"<[^>]+>", " ", x)).split()) for x in cell.split("\n"))


def parse_supplement(text: str) -> dict | None:
    """'Doplata za polupansion 14 eura dnevno … deca od 2 do 12 godina - 50% popusta na doplatu'."""
    m = re.search(r"doplata\s+za\s+polupansion\w*\s*(?:je\s*)?(?:-\s*)?(\d+(?:[.,]\d+)?)\s*(?:€|eur)", text, re.I)
    if not m:
        return None
    kid = re.search(r"deca\s+od\s*(\d+)\s*(?:-|do)\s*(\d+)\s*godina\s*[-–]?\s*(\d+)\s*%\s*popusta\s+na\s+doplat",
                    text, re.I)
    return {"adult": float(m.group(1).replace(",", ".")),
            "kid_lo": float(kid.group(1)) if kid else None, "kid_hi": float(kid.group(2)) if kid else None,
            "kid_share": 1 - int(kid.group(3)) / 100 if kid else 1.0}


def parse_early(title: str, today: date) -> dict | None:
    """'Rani booking - 15% popusta do 31.12.2026. (… popust uključen u cenu) i dvoje dece od 2-12
    godina u sobi sa 2 odrasle osobe GRATIS smeštaj sa uslugom noćenje sa doručkom'."""
    m = re.search(r"rani\s+booking\s*[-–]?\s*(\d+)\s*%\s*popusta\s*(?:za\s+rezervacije\s*)?do\s*"
                  r"(\d{1,2})\.(\d{1,2})\.(20\d{2})", title, re.I)
    if not m:
        return None
    until = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
    if until < today:
        return None
    kids = re.search(r"(dvoje\s+dece|jedno\s+dete|dete)\s+od\s*(\d+)\s*(?:-|do)\s*(\d+)\s*godina\s+u\s+sobi\s+sa\s+"
                     r"(?:2|dve)\s+odrasle\s+osobe\s+gratis", title, re.I)
    rule = None
    if kids:
        rule = {"count": 2 if "dvoje" in kids.group(1).lower() else 1, "lo": float(kids.group(2)),
                "hi": float(kids.group(3)), "share": 0.0, "coef": None, "hint": None,
                "text": "early booking: " + " ".join(kids.group(0).split()), "board": "ND"}
    return {"pct": int(m.group(1)), "until": until.isoformat(),
            "included": bool(re.search(r"uključen\w*\s+u\s+cen", title, re.I)), "kids_rule": rule}


def parse_page(html: str, today: date, year: int = 2027) -> dict:
    """Name, facts and the price table of one hotel page."""
    name = re.search(r'class="naslov-kategorije">\s*([^<]+?)\s*<', html or "")
    og = re.search(r'<meta property="og:image" content="([^"#]+)', html or "")
    body = re.search(r'<div itemprop="articleBody">(.*)', html or "", re.S)
    body_html = body.group(1) if body else (html or "")
    tpos = body_html.find("<table")
    intro = _clean(body_html[:tpos] if tpos >= 0 else body_html[:20000])
    out = {"name": _clean(name.group(1)) if name else "", "image": image_url(og.group(1), BASE) if og else None,
           "intro": intro, "table": None}
    low = intro.lower()
    # A sandy beach named as "udaljena je 500 metara" is another beach down the road, not the hotel's.
    near = " ".join(x for x in re.split(r"(?<=[.!?])\s+", low)
                    if not (re.search(r"udaljen", x) and any(int(d) >= 300 for d in re.findall(r"(\d+)\s*(?:m\b|metar)", x))))
    sandy, pebble = re.search(r"peščan|pješčan|pjeskovit|peskovit", near), re.search(r"šljun", near)
    out["sand_beach"] = True if sandy and not pebble else (False if pebble and not sandy else None)
    bm = re.search(r"(\d+)\s*(?:m|metara)\s+od\s+(?:sopstvene\s+|hotelske\s+)?(?:peščane\s+)?plaž", low) \
        or re.search(r"udaljenosti\s+od\s+(?:oko\s+)?(\d+)\s*m\s+od\s+plaž", low)
    out["beach_m"] = int(bm.group(1)) if bm else None
    out["beachfront"] = bool(re.search(r"na samoj obali|neposredno uz\s+\w*\s*plaž|sopstvenu plažu|pored (?:poznate )?\w+ plaže",
                                       low))
    out["cots"] = "krevetac" in (html or "").lower()
    if tpos < 0:
        return out
    table = body_html[tpos:body_html.find("</table>", tpos)]
    rows = _rows(table)
    if len(rows) < 3:
        return out
    title = _clean(rows[0][0]) if rows[0] else ""
    stars = re.search(r"(\*{2,5})\s*/", title)
    out["stars"] = len(stars.group(1)) if stars else None
    tl = title.lower()
    unit = "unit" if re.search(r"po\s+(apartmanu|studiju|smeštajnoj|objektu|sobi)\b", tl) else "person"
    header_i = next((i for i, r in enumerate(rows) if r and _clean(r[0]).lower().startswith("smeštaj")), None)
    if header_i is None:
        return out
    header = rows[header_i]
    lead = next((i for i, c in enumerate(header) if re.search(r"broj\s+osoba", _clean(c), re.I)), 2) + 1
    periods = [_periods(c, year) for c in header[lead:]]
    nights_row = next((r for r in rows if r and re.search(r"broj\s+noćenja", _clean(r[0]), re.I)), None)
    stay_n = [int(_num(_clean(c)) or 1) for c in nights_row[1:]] if nights_row else [1] * len(periods)
    min_row = next((r for r in rows if r and re.search(r"minimaln", _clean(r[0]), re.I)), None)
    min_stay = [int(_num(_clean(c)) or 0) for c in min_row[1:]] if min_row else []
    rooms, popusti, doplate = [], "", ""
    for r in rows[header_i + 1:]:
        if not r:
            continue
        first = _clean(r[0])
        if re.match(r"popusti", first, re.I):
            popusti = _cell_lines(" ".join(r[1:]))
            continue
        if re.match(r"doplate|napomena", first, re.I):
            doplate += " " + _clean(" ".join(r[1:]))
            continue
        cells = [_clean(c) for c in r]
        board_i = next((i for i, c in enumerate(cells[:3]) if c.upper().strip() in BOARDS), None)
        if board_i is None or len(cells) < board_i + 2 + len(periods):
            continue
        occ = cells[board_i + 1]
        caps = [int(a) + int(b) for a, b in re.findall(r"(\d+)\s*\+\s*(\d+)", occ)]
        prices = [_num(c) for c in cells[board_i + 2: board_i + 2 + len(periods)]]
        rooms.append({"name": " ".join(cells[:board_i]), "board": cells[board_i].upper().strip(), "occ": occ,
                      "cap": max(caps) if caps else None, "prices": prices})
    early = parse_early(title, today)
    rules = parse_rules(popusti)
    if early and early["kids_rule"]:
        rules.append(early["kids_rule"])
    cen = re.search(r"Cenovnik\s+br\.?\s*\d+\s*,?\s*(\d{1,2}\.\d{1,2}\.20\d{2})", body_html)
    out.update({"stars": out.get("stars"), "table": {
        "title": title, "unit": unit, "periods": periods, "stay_nights": stay_n, "min_stay": min_stay,
        "rooms": rooms, "rules": rules, "supplement": parse_supplement(doplate), "early": early,
        "price_list_date": cen.group(1) if cen else None}})
    return out


# ------------------------------------------------------------------ pricing
def _column_for(periods: list, d: date) -> int | None:
    for i, ps in enumerate(periods):
        if any(a <= d <= b for a, b in ps):
            return i
    return None


def stay_price(table: dict, room: dict, check_in: date, nights: int):
    """(per-person or per-unit price for the stay, actual check-in, nights) or None."""
    if any(n > 1 for n in table["stay_nights"]):            # fixed stays (bus departures)
        for i, ps in enumerate(table["periods"]):
            for a, b in ps:
                if a <= check_in < b and i < len(room["prices"]) and room["prices"][i]:
                    return room["prices"][i], a, table["stay_nights"][i]
        return None
    total = 0.0
    for k in range(nights):
        i = _column_for(table["periods"], check_in + timedelta(days=k))
        if i is None or i >= len(room["prices"]) or not room["prices"][i]:
            return None
        if table["min_stay"] and i < len(table["min_stay"]) and nights < table["min_stay"][i]:
            return None
        total += room["prices"][i]
    return total, check_in, nights


def kids_factor(rules: list[dict], room: dict, age: float, board: str) -> tuple[float | None, str]:
    """Persons-equivalent the two kids add to 2 adults in this room (None = no 2+2 here)."""
    rn = _norm(room["name"] + " " + room["occ"])

    def fits(r):
        return (r["lo"] <= age < r["hi"] and (not r["hint"] or r["hint"] in rn)
                and (r.get("board") in (None, board)))
    ok = [r for r in rules if fits(r)]
    two = [r for r in ok if r["count"] == 2]
    if two:
        best = max(two, key=lambda r: (r["coef"] - 2) if r["coef"] else 2 * (r["share"] or 0))
        return ((best["coef"] - 2) if best["coef"] else 2 * best["share"]), best["text"]
    if (room["cap"] or 0) >= 4:
        each = [r for r in ok if r["count"] in (1, None) and r["share"] is not None]
        if each:
            best = max(each, key=lambda r: r["share"])
            return 2 * best["share"], best["text"]
        return 2.0, "no child rate for this age: kids at the adult price"
    return None, ""


def _kind(name: str) -> str:
    n = name.lower()
    return "apartment" if n.startswith("apartman") else ("villa" if n.startswith(("vila", "villa", "vile")) else "hotel")


def hotel_offers(parsed: dict, page: dict, cfg: dict, today: date, url: str, card: dict | None = None):
    table = parsed.get("table")
    slug = re.sub(r"\.html$", "", url.rstrip("/").split("/")[-1])
    card = card or {}
    fam: dict = {"verified": []}
    sand = parsed.get("sand_beach")
    if sand is None and page.get("sand_beach") is not None:
        sand = bool(page["sand_beach"])
    if sand is not None:
        fam["sand_beach"] = sand
    beach_m = parsed.get("beach_m") if parsed.get("beach_m") is not None else card.get("beach_m")
    if beach_m is not None:
        fam["beach_m"] = beach_m
    if parsed.get("beachfront"):
        fam["beachfront"] = True
    if parsed.get("cots"):
        fam["cots_mentioned"] = True
    name = parsed.get("name") or card.get("name") or slug
    hotel = {
        "id": f"pa-{slug}",
        "name": name,
        "stars": (table or {}).get("stars") or parsed.get("stars") or card.get("stars"),
        "season": page.get("season", "summer"),
        "area": page["area"],
        "country": page.get("country", "ME"),
        "lat": page["lat"],
        "lng": page["lng"],
        "direct_flight_skp": False,
        "border": page.get("border", True),
        "kind": _kind(name),
        "family": fam,
        "image": parsed.get("image"),
        "notes": "",
    }
    if not table or not table["rooms"]:
        return None, []
    if any(r["board"] in ("PP", "PA", "AL", "ALL", "AI", "UAI") for r in table["rooms"]) or table["supplement"]:
        fam["half_board"] = True
    notes = ["Hotel's 2027 price list via Plan A Travel (own transport)"
             + (f", list of {table['price_list_date']}" if table["price_list_date"] else "") + "."]
    if sand is None:
        notes.append("Beach type not stated on the page.")
    hotel["notes"] = " ".join(notes) + " Ask about cots and the twins' beds."
    nights = int(page.get("nights", 7))
    check_ins = [date.fromisoformat(str(c)) for c in (page.get("check_ins") or [page.get("check_in")]) if c]
    early, supp = table["early"], table["supplement"]
    offers = []
    for ci in check_ins:
        if ci < today:
            continue
        age = kids_age_on(cfg, ci)
        best: dict | None = None
        for room in table["rooms"]:
            sp = stay_price(table, room, ci, nights)
            if not sp:
                continue
            base, start, n = sp
            board = BOARDS.get(room["board"], "?")
            kf, why = kids_factor(table["rules"], room, age, room["board"]) if table["unit"] == "person" else (
                (0.0, "price per unit") if (room["cap"] or 0) >= 4 else (None, ""))
            occupancy = "2+2" if kf is not None else "2+0"
            persons = 2 + (kf or 0) if table["unit"] == "person" else 1
            room_part = base * persons
            extra, label = 0.0, ""
            if room["board"] == "ND" and supp:
                kid_s = supp["kid_share"] if supp["kid_lo"] is not None and supp["kid_lo"] <= age < supp["kid_hi"] else 1.0
                extra = supp["adult"] * n * (2 + (2 * kid_s if occupancy == "2+2" else 0))
                board, label = "HB", f" + half board {supp['adult']:g} €/day"
            if early and not early["included"]:
                was = room_part + extra
                room_part *= 1 - early["pct"] / 100
            else:
                was = room_part / (1 - early["pct"] / 100) + extra if early else None
            price = round(room_part + extra, 2)
            cand = {"price": price, "was": round(was, 2) if was else None, "room": room, "occ": occupancy,
                    "board": board, "start": start, "n": n, "why": why, "label": label}
            key = (cand["occ"] != "2+2", price)
            if best is None or key < (best["occ"] != "2+2", best["price"]):
                best = cand
        if not best:
            continue
        kids_txt = f"; kids: {best['why']}" if best["occ"] == "2+2" else ""
        offers.append({
            "hotel": hotel["id"],
            "source": SOURCE,
            "url": url,
            "seen": today.isoformat(),
            "check_in": best["start"].isoformat(),
            "nights": best["n"],
            "board": best["board"],
            "room": f"{best['room']['name']} ({best['room']['board']}, {best['room']['occ']}){best['label']}{kids_txt}",
            "occupancy": best["occ"],
            "price_eur": best["price"],
            "was_eur": best["was"],
            "discount_label": f"Early booking -{early['pct']}%" if early else None,
            "valid_until": early["until"] if early else None,
        })
    return hotel, offers


# ------------------------------------------------------------------ fetch
def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    src = cfg["sources"].get("me_coast", {})
    if not src.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    only_stickered = src.get("only_stickered", True)
    sticker = str(src.get("sticker", "2027"))
    hotels: dict[str, dict] = {}
    offers: list[dict] = []
    done: set[str] = set()
    for page in src.get("pages", []):
        try:
            if page.get("hotel"):                      # a single hotel page
                cards = [{"url": page["url"]}]
            else:
                cards = parse_list(s.get(page["url"]))
                exclude = set(page.get("exclude", []))
                cards = [c for c in cards if not any(x in c["url"] for x in exclude)]
                if only_stickered:
                    cards = [c for c in cards if sticker in c["sticker"]]
                cards = cards[: int(page.get("max_hotels", 15))]
            year = int(str(page.get("check_in", f"{today.year + 1}-01-01"))[:4])
            n = 0
            for c in cards:
                if c["url"] in done:
                    continue
                done.add(c["url"])
                hotel, offs = hotel_offers(parse_page(s.get(c["url"]), today, year), page, cfg, today, c["url"], c)
                if hotel and offs:
                    hotels.setdefault(hotel["id"], hotel)
                    offers.extend(offs)
                    n += len(offs)
            log.info("Plan A %s: %d hotel pages read, %d offers", page["area"], len(cards), n)
        except Blocked as e:
            log.warning("Plan A stopped (respecting the block): %s", e)
            break
        except (Unavailable, ValueError) as e:
            log.warning("Plan A %s skipped: %s", page["area"], e)
    return list(hotels.values()), offers
