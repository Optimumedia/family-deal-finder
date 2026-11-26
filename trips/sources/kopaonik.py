"""Serbian ski resorts (Kopaonik, Stara Planina): published winter price lists, read as tables.

Two kinds of page, picked per page with `parser`:

* "jat" — JAT Apartmani's own price list (jatapartmani.com/en/price-list; robots.txt allows
  everything but /api/). A server-rendered table: one row per period, one column per unit type
  ("Standard D · base rate for 4 guests"), per-unit price per night in EUR plus a "7 nights"
  total, 10% lower in the rows marked "7 nights −10%". The unit pages
  (/en/accommodation/apartman-d …) say how many rooms a unit has ("one room", "two rooms").
* "supernova" — Supernova Travel's per-property price pages
  (supernovatravel.rs/cenovnici/…-cenovnik.html; robots.txt blocks only Joomla system folders).
  Hand-made Joomla tables in RSD: a header row of periods ("29.NOV 13.DEC"), a minimum-nights
  row, one row per unit ("2+1 APARTMAN | 4 | 93,600 …"), and a note row under each block that
  says what the numbers are ("PO NOĆI" = per night, "ZA NAVEDENI BROJ NOĆI" = for the nights in
  the minimum-nights row, "PO OSOBI" = per person — skipped). A "CENA | Dnevna | Nedeljna" row
  sets the basis per column instead (daily vs 7-night price).

Prices are per unit, so units for 4+ guests are stored as "2+2". Studios (one room) are marked
`separate_bedroom: False`; an apartment only gets True when the page says two rooms or a
bedroom — otherwise it stays unknown ("ask"). Nothing is guessed: a column we can't read
(merged periods, "/" cells) is skipped.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from html import unescape

from ..http import Blocked, PoliteSession, Unavailable
from .pagetext import html_to_text, image_url, money

log = logging.getLogger(__name__)
SOURCE = "Kopaonik apartments"
JAT_BASE = "https://jatapartmani.com"
SOURCES = {"jat": "JAT Apartmani (own site)", "supernova": "Supernova Travel"}
SR_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAJ": 5, "JUN": 6, "JUL": 7, "AVG": 8,
             "SEP": 9, "OKT": 10, "NOV": 11, "DEC": 12}


def _cells(row_html: str) -> list[str]:
    return [" ".join(unescape(re.sub(r"<[^>]+>", " ", c)).split())
            for c in re.findall(r"(?s)<t[dh][^>]*>(.*?)</t[dh]>", row_html)]


def _slug(s: str) -> str:
    s = s.lower().translate(str.maketrans("čćšžđ", "ccszd"))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _title(s: str) -> str:
    return " ".join(w if any(c.islower() for c in w) else w.capitalize() for w in s.split())


def _bedroom(text: str, label: str = "") -> bool | None:
    """Separate bedroom only when the page says so. Studio / one room = no."""
    t = f"{label} {text}".lower()
    one = bool(re.search(r"\bstudio\b|\bstd\b|one room|jednu prostoriju|jednosoban studio", t))
    two = bool(re.search(r"two rooms|separate bedroom|\b(?:one|\d)[ -]bedroom|spava[cć][ae] sob|dvosob", t))
    if two and not one:
        return True
    if one and not two:
        return False
    return None


# ---------------------------------------------------------------- JAT ---

def parse_jat_price_list(html: str) -> dict:
    """{'units': [{'letter','pax'}], 'periods': [{'from','to','promo','rates':[{'night','week'}]}],
    'half_board_eur': float|None}. Only the server-rendered Standard table (the Lux tab is
    drawn by JavaScript)."""
    table = re.search(r'(?s)<table class="pl-table">(.*?)</table>', html)
    if not table:
        return {"units": [], "periods": [], "half_board_eur": None}
    t = table.group(1)
    units = []
    for th in re.findall(r"(?s)<th>(.*?)</th>", re.search(r"(?s)<thead>(.*?)</thead>", t).group(1))[1:]:
        m = re.search(r"Standard\s+([A-Z](?:/[A-Z])?)", th)
        pax = re.search(r"for (\d+) guests", th)
        units.append({"letter": m.group(1) if m else None, "pax": int(pax.group(1)) if pax else 0})
    periods = []
    for row in re.findall(r"(?s)<tr[^>]*>(.*?)</tr>", re.search(r"(?s)<tbody>(.*?)</tbody>", t).group(1)):
        head = re.search(r'(?s)<th scope="row">(.*?)</th>', row)
        d = re.search(r"(\d{1,2})\.(\d{1,2})\.\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(20\d{2})", head.group(1)) if head else None
        if not d:
            continue
        d1, m1, d2, m2, y2 = map(int, d.groups())
        y1 = y2 if m1 <= m2 else y2 - 1
        rates = []
        for td in re.findall(r"(?s)<td>(.*?)</td>", row):
            night = re.search(r"<b>([\d,]+\.\d{2}) EUR</b>", td)
            week = re.search(r"7 nights.*?([\d,]+\.\d{2}) EUR", td, re.S)
            rates.append({"night": float(night.group(1).replace(",", "")) if night else None,
                          "week": float(week.group(1).replace(",", "")) if week else None})
        periods.append({"from": date(y1, m1, d1).isoformat(), "to": date(y2, m2, d2).isoformat(),
                        "promo": "−10%" in head.group(1) or "-10%" in head.group(1), "rates": rates})
    hb = re.search(r"Half board\s*([\d.]+)\s*EUR per person", html_to_text(html))
    return {"units": units, "periods": periods, "half_board_eur": float(hb.group(1)) if hb else None}


def parse_jat_unit(html: str) -> dict:
    name = re.search(r'<h1[^>]*>([^<]+)', html)
    lead = re.search(r'<p class="lead" style="color:#3B4A50[^"]*">([^<]+)</p>', html)
    size = re.search(r"(\d+(?:–\d+)?) m²", html)
    og = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    text = unescape(lead.group(1)) if lead else ""
    return {
        "name": unescape(name.group(1)).strip() if name else None,
        "separate_bedroom": _bedroom(text),
        "two_room_variant": bool(re.search(r"two rooms", text, re.I)) and bool(re.search(r"one room", text, re.I)),
        "size_m2": size.group(1) if size else None,
        "kitchen": "</svg>Kitchen</span>" in html,
        "image": image_url(og.group(1), JAT_BASE) if og else None,
    }


def jat_offers(pl: dict, units: dict, page: dict, cfg: dict, today: date):
    """units: letter → parse_jat_unit() result (missing = unknown layout)."""
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    nights = int(page.get("nights", 7))
    hotels, offers = {}, []
    for i, u in enumerate(pl["units"]):
        if not u["letter"] or "/" in u["letter"] or u["pax"] < need:
            continue
        info = units.get(u["letter"], {})
        hid = f"kop-jat-{u['letter'].lower()}"
        notes = [f"JAT Apartmani's own price list: Standard {u['letter']}, per unit, base rate for {u['pax']} guests, "
                 "self-catering (kitchenette). Tourist tax and insurance extra."]
        if info.get("size_m2"):
            notes.append(f"{info['size_m2']} m².")
        if info.get("two_room_variant"):
            notes.append("This type comes in a one-room and a two-room version — ask for the two-room one.")
        if pl.get("half_board_eur"):
            notes.append(f"Half board {pl['half_board_eur']:.2f} EUR/person/day extra (site: under 3 free, 3–10 −50%).")
        hotels[hid] = {
            "id": hid, "name": f"JAT Apartmani — {info.get('name') or 'Standard ' + u['letter']}", "stars": None,
            "season": page["season"], "area": page["area"], "country": page.get("country", "RS"),
            "lat": page["lat"], "lng": page["lng"], "direct_flight_skp": False, "border": True,
            "kind": "apartment",
            "family": {"separate_bedroom": info.get("separate_bedroom"), "verified": []},
            "image": info.get("image"), "notes": " ".join(notes),
        }
        for p in pl["periods"]:
            r = p["rates"][i] if i < len(p["rates"]) else {}
            if not r.get("night"):
                continue
            check_in = max(p["from"], today.isoformat())
            if date.fromisoformat(check_in) + timedelta(days=nights) > date.fromisoformat(p["to"]):
                continue                                  # stay would run into the next price period
            full = round(r["night"] * nights, 2)
            promo = p["promo"] and nights == 7 and r.get("week")
            offers.append({
                "hotel": hid, "source": SOURCES["jat"], "url": page["url"], "seen": today.isoformat(),
                "check_in": check_in, "nights": nights, "board": "SC",
                "room": f"Standard {u['letter']} (whole unit, up to {u['pax']} guests)", "occupancy": "2+2",
                "price_eur": r["week"] if promo else full, "was_eur": full if promo else None,
                "discount_label": "JAT: 7 nights −10%" if promo else None, "valid_until": None,
            })
    return list(hotels.values()), offers


# ----------------------------------------------------------- Supernova ---

_PERIOD = re.compile(r"^(\d{1,2})\.\s*([A-ZČŠ]{3})[A-Z]*\.?\s*[-–]?\s*(\d{1,2})\.\s*([A-ZČŠ]{3})[A-Z]*\.?$", re.I)


def _period(cell: str, y1: int):
    m = _PERIOD.match(cell.strip())
    if not m:
        return None
    a, b = SR_MONTHS.get(m.group(2).upper()), SR_MONTHS.get(m.group(4).upper())
    if not a or not b:
        return None
    try:
        start = date(y1 if a >= 7 else y1 + 1, a, int(m.group(1)))
        end = date(y1 if b >= 7 else y1 + 1, b, int(m.group(3)))
    except ValueError:
        return None
    return (start.isoformat(), end.isoformat()) if end > start else None


def _amount(cell: str) -> float | None:
    c = cell.strip()
    if not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+|\d{3,6}", c):
        return None
    return money(c)


def _basis(note: str) -> str | None:
    n = note.upper()
    if "PO OSOBI" in n:
        return "person"
    if "DNEVNE ILI NEDELJNE" in n:
        return "columns"
    if re.search(r"ZA NAVEDENI BROJ NO[ĆC]I|ZA 7 NO[ĆC]I", n):
        return "stay"
    if re.search(r"PO NO[ĆC]I", n):
        return "night"
    return None


def parse_supernova(html: str, today: date) -> dict:
    """{'name', 'board', 'units': [{'label','pax','prices':[{'from','to','nights','basis','rsd'}]}]}
    from the first table on the page that yields priced units."""
    body = html[html.find("com-content-article__body"):] if "com-content-article__body" in html else html
    yrs = re.search(r"(20\d{2})\s*/\s*(20\d{2})", html_to_text(body[:3000]))
    y1 = int(yrs.group(1)) if yrs else (today.year if today.month >= 7 else today.year - 1)
    for table in re.findall(r"(?s)<table.*?</table>", body):
        rows = [c for c in (_cells(r) for r in re.findall(r"(?s)<tr.*?</tr>", table)) if any(c)]
        name, stars = None, 0
        periods, nights, col_basis = [], [], []
        pending, units, board = [], [], "?"
        for cells in rows:
            filled = [c for c in cells if c]
            if name is None and len(filled) == 1 and re.search(r"zima|20\d{2}", filled[0], re.I):
                name = re.split(r"\s+-\s+|,", filled[0])[0].strip()
                st = re.search(r"\s*(\d)?\s*(\*+)", name)
                stars = (int(st.group(1)) if st.group(1) else len(st.group(2))) if st else 0
                name = re.sub(r"\s*\d?\s*\*+", "", name).strip()
                continue
            parsed = [_period(c, y1) for c in cells]
            if sum(1 for p in parsed if p) >= 2:            # header row with periods
                first = next(i for i, c in enumerate(cells) if _PERIOD.match(c.strip()) or re.search(r"\d\.\s*[A-Z]{3}", c))
                periods = parsed[first:]
                continue
            if not periods:
                continue
            n = len(periods)
            if re.search(r"NO[ĆC]I", cells[0], re.I) and len(cells) >= n:
                nights = [int(re.search(r"\d+", c).group()) if re.search(r"\d+", c) else None for c in cells[-n:]]
                continue
            if len(filled) > 1 and cells[0].upper().startswith("CENA") and any(re.search(r"dnevn|nedeljn", c, re.I) for c in cells):
                col_basis = ["night" if re.search(r"dnevn", c, re.I) else "week" for c in cells[-n:]]
                continue
            if len(filled) == 1:                             # a note under a block of units
                b = _basis(filled[0])
                if b:
                    if re.search(r"POLUPANSION", filled[0], re.I):
                        board = "HB"
                    elif re.search(r"NAJAM", filled[0], re.I) and board == "?":
                        board = "SC"
                    if b != "person":
                        for u in pending:
                            u["basis"] = b
                        units.extend(pending)
                    pending = []
                continue
            if len(cells) > n and sum(1 for c in cells[-n:] if _amount(c)) >= max(2, n // 2):
                head = [c for c in cells[:-n] if c]
                if not head:
                    continue
                pax_cell = head[-1] if len(head) > 1 else ""
                label = " ".join(c for c in (head[:-1] if len(head) > 1 else head) if not re.fullmatch(r"\d+", c))
                ints = [int(x) for x in re.findall(r"\d+", pax_cell)]
                ints += [int(a) + int(k) for a, k in re.findall(r"(\d+)\s*adl\s*i\s*(\d+)\s*chd", pax_cell, re.I)]
                pending.append({"label": label, "pax": max(ints) if ints else None,
                                "raw": [_amount(c) for c in cells[-n:]]})
        if not units:
            continue
        if board == "?" and re.search(r"\bnajam\b", html_to_text(body[body.find(table):body.find(table) + len(table) + 4000]), re.I):
            board = "SC"
        out = []
        for u in units:
            prices = []
            for j, (per, rsd) in enumerate(zip(periods, u["raw"])):
                if not per or not rsd:
                    continue
                k = nights[j] if j < len(nights) and nights[j] else 1
                basis = u["basis"]
                if basis == "columns":
                    basis = "night" if (col_basis[j] if j < len(col_basis) else "night") == "night" else "stay"
                    k = 1 if basis == "night" else 7
                if basis == "stay" and k == 1:
                    basis = "night"
                prices.append({"from": per[0], "to": per[1], "nights": k, "basis": basis, "rsd": rsd})
            out.append({"label": u["label"], "pax": u["pax"], "prices": prices})
        return {"name": name, "stars": stars or None, "board": board, "units": out}
    return {"name": None, "stars": None, "board": "?", "units": []}


def supernova_offers(parsed: dict, page: dict, cfg: dict, today: date):
    need = cfg["family"]["adults"] + cfg["family"]["kids"]
    rate = float(cfg["sources"].get("kopaonik", {}).get("rsd_per_eur", 117.2))
    want = int(page.get("nights", 7))
    prop = page.get("name") or _title(parsed["name"] or "Supernova property")
    hotels, offers = {}, []
    for u in parsed["units"]:
        if not u["pax"] or u["pax"] < need or not u["prices"]:
            continue
        hid = f"kop-sn-{_slug(page.get('slug') or prop)}-{_slug(u['label'])}"
        sep = _bedroom("", u["label"])
        hotels[hid] = {
            "id": hid, "name": f"{prop} — {_title(u['label'])}", "stars": page.get("stars") or parsed.get("stars"),
            "season": page["season"], "area": page["area"], "country": page.get("country", "RS"),
            "lat": page["lat"], "lng": page["lng"], "direct_flight_skp": False, "border": True,
            "kind": page.get("kind", "apartment"),
            "family": {"separate_bedroom": sep, "verified": []},
            "image": None,
            "notes": f"From Supernova Travel's price list (RSD, per unit, up to {u['pax']} guests; "
                     f"converted at {rate} RSD/EUR). Tourist tax extra."
                     + ("" if sep is not None else " Listed as an apartment — ask whether the bedroom is separate."),
        }
        for p in u["prices"]:
            if p["from"] < today.isoformat() or int(p["from"][5:7]) in range(5, 11):
                continue                                  # past, or not a winter period
            if p["basis"] == "night":
                n = max(want, p["nights"])
                rsd = p["rsd"] * n
            else:
                n, rsd = p["nights"], p["rsd"]
            if date.fromisoformat(p["from"]) + timedelta(days=n) > date.fromisoformat(p["to"]):
                continue
            offers.append({
                "hotel": hid, "source": SOURCES["supernova"], "url": page["url"], "seen": today.isoformat(),
                "check_in": p["from"], "nights": n, "board": page.get("board") or parsed["board"],
                "room": f"{_title(u['label'])} (whole unit, up to {u['pax']} guests)", "occupancy": "2+2",
                "price_eur": round(rsd / rate, 2), "was_eur": None, "discount_label": None, "valid_until": None,
            })
    return list(hotels.values()), offers


# --------------------------------------------------------------- fetch ---

def fetch(cfg: dict, today: date, session: PoliteSession | None = None) -> tuple[list[dict], list[dict]]:
    kc = cfg["sources"].get("kopaonik", {})
    if not kc.get("enabled"):
        return [], []
    s = session or PoliteSession(cfg["sources"]["delay_seconds"], cfg["sources"]["jitter_seconds"],
                                 cfg["sources"]["timeout_seconds"])
    hotels, offers, blocked = {}, [], set()
    for page in kc.get("pages", []):
        kind = page.get("parser", "supernova")
        if kind in blocked:
            continue
        try:
            if kind == "jat":
                pl = parse_jat_price_list(s.get(page["url"]))
                need = cfg["family"]["adults"] + cfg["family"]["kids"]
                units = {u["letter"]: parse_jat_unit(s.get(f"{JAT_BASE}/en/accommodation/apartman-{u['letter'].lower()}"))
                         for u in pl["units"] if u["letter"] and "/" not in u["letter"] and u["pax"] >= need}
                hs, os_ = jat_offers(pl, units, page, cfg, today)
            else:
                hs, os_ = supernova_offers(parse_supernova(s.get(page["url"]), today), page, cfg, today)
            hotels.update({h["id"]: h for h in hs})
            offers.extend(os_)
            log.info("Kopaonik/%s %s: %d units, %d offers", kind, page["url"], len(hs), len(os_))
        except Blocked as e:
            log.warning("Kopaonik/%s stopped (respecting the block): %s", kind, e)
            blocked.add(kind)
        except (Unavailable, ValueError, AttributeError) as e:
            log.warning("Kopaonik/%s %s skipped: %s", kind, page["url"], e)
    return list(hotels.values()), offers
