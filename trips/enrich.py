"""Detail-page enrichment for Olympic (olympic.rs) and Travelland (travelland.rs) offers.

The agencies' LIST cards give a "from" price but rarely the board, the kids' price or any
family fact. Each offer links to the hotel's DETAIL page, which usually states:

* the board options (per-room price tabs "BB – bed and breakfast" / "HB – half board",
  a `data-pricelistsService` map, or a "Usluga: …" line),
* the child policy ("Popust za 1 dete (0 - 2)" = 100 % → first child aged 0–2 stays free),
* distances ("Udaljenosti → Plaža 80 m") and the beach type (pesak / peščana = sand,
  šljunak = pebble),
* kids' pool, kids' club, playground, playroom, animation, "adults only",
* room types (1-bedroom apartments, family rooms, max persons) and a price table.

`extract(html, url)` turns one page into a dict of facts. It never guesses: a fact the
page doesn't state stays out of the dict (unknown), and nothing is ever set to False
just because a word is missing. Only short matched terms are kept as evidence, no
descriptions are copied.

`enrich(offers, hotels, cfg, today, budget=N, session=None)` reads the detail pages
politely (PoliteSession: robots.txt, delay, stop at a bot wall), at most `budget` live
pages per run, and caches the extracted facts in data/enrich_cache.json so a page is
re-read at most once every `max_age_days` (7). It fills hotel["family"] facts that are
still unknown (curated facts and "verified" are never touched) and sets an offer's board
only when it is "?" and the page states exactly one board.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .http import Blocked, PoliteSession, Unavailable

log = logging.getLogger(__name__)

PARSER_VERSION = 1
HOSTS = {"olympic.rs": "olympic", "travelland.rs": "travelland"}
DEFAULT_CACHE = Path("data/enrich_cache.json")

# Facts that enrich() may copy into hotel["family"] (only when still unknown there).
FAMILY_KEYS = (
    # read by trips/score.py
    "sand_beach", "beach_m", "kids_pool", "kids_club", "kids_club_min_age", "family_room", "separate_bedroom",
    # extra facts, shown/used later (score.py ignores them today)
    "half_board", "beach_type", "beachfront", "playground", "playroom", "kids_animation", "kids_welcome",
    "adults_only", "adults_only_min_age", "cots_mentioned", "kids_free_max_age", "first_child_free_max_age",
    "price_2plus2_listed",
)

# ------------------------------------------------------------------ text helpers ---

_DROP_BLOCKS = re.compile(r"<(script|style|svg|iframe|noscript)\b.*?</\1>", re.S | re.I)
_BREAKS = re.compile(r"<br\s*/?>|</?(p|div|li|ul|h\d|tr|td|th|section|button|span|a|del|strong|small|label)\b[^>]*>",
                     re.I)
_TAG = re.compile(r"<[^>]+>")
_END = re.compile(r"Moglo bi vam se svi[dđ]ati|<footer\b", re.I)


def lines_of(fragment: str) -> list[str]:
    """HTML fragment → non-empty, whitespace-collapsed text lines."""
    t = _DROP_BLOCKS.sub(" ", fragment)
    t = _BREAKS.sub("\n", t)
    t = htmllib.unescape(_TAG.sub(" ", t))
    out = []
    for ln in t.split("\n"):
        ln = " ".join(ln.split())
        if ln:
            out.append(ln)
    return out


def scope(page: str) -> str:
    """The part of the page about THIS hotel: from its <h1> to the "you might also like"
    block / footer (which lists other hotels with their own boards)."""
    start = page.find("<h1")
    start = 0 if start < 0 else start
    m = _END.search(page, start)
    return page[start:m.start() if m else len(page)]


def _num(s: str) -> float:
    s = s.strip().rstrip(".,")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s.replace(".", "").replace(",", ".") if "," in s else s)


def _short(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# ----------------------------------------------------------------------- boards ---

_BOARD_PATTERNS = [
    ("AI", re.compile(r"ultra\s*all|all[\s-]*inclusive", re.I)),
    ("FB", re.compile(r"\bpun\w*\s+pansion\w*|full\s*board", re.I)),
    ("HB", re.compile(r"polupansion\w*|half\s*board|doru[cč]\w*\s+i\s+ve[cč]er\w*", re.I)),
    ("BB", re.compile(r"no[cć]enj\w*\s+(?:sa|i|uz)\s+doru[cč]\w*|bed\s*(?:and|&)\s*breakfast", re.I)),
    ("RO", re.compile(r"samo\s+(?:no[cć]enj\w*|sme[sš]taj\w*)|room\s*only|bez\s+ishrane|\bnajam\b|"
                      r"no[cć]enj\w*(?!\s+(?:sa|i|uz)\s+doru)", re.I)),
]


def board_codes(text: str) -> list[str]:
    """All board codes a short text names ("Noćenje sa doručkom ili polupansion" → [BB, HB])."""
    found = []
    rest = text or ""
    for code, rx in _BOARD_PATTERNS:
        if rx.search(rest):
            found.append(code)
            rest = rx.sub(" ", rest)            # "polupansion (doručak i večera)" counts once
    return found


# ------------------------------------------------------------------ price lists ---

_DATE_RANGE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})\.?\s*-\s*(\d{2})\.(\d{2})\.(\d{4})\.?$")
_EUR = re.compile(r"€\s*([\d.,]+\d)")
_PCT = re.compile(r"^(\d{1,3})\s*%$")
_VALID = re.compile(r"VAŽI DO\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.I)
_MIN_STAY = re.compile(r"^Min\.?\s*boravak:\s*(\d+)", re.I)
_OCC = re.compile(r"^Broj osoba:\s*(\d+)\s*\(Deca:\s*(\d+)(?:,\s*Uzrast:\s*([^)]+))?\)", re.I)
_PER = re.compile(r"^po\s+(osobi|jedinici|danu|boravku|nedelji|no[cć]i)\b", re.I)
_VREDI = re.compile(r"^Vredi od", re.I)
_CHILD = re.compile(r"(?:(\d)\.?\s*)?(?:dete|deteta|dijete|djeteta|deca|djeca|child\w*)\s*"
                    r"\(\s*(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*\)", re.I)


def _iso(d, m, y) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def parse_pricelist(lines: list[str], room: str | None = None, board: str | None = None) -> dict:
    """One price-list pane (as text lines) → price rows, discounts and supplements.

    Rows look like: "23.04.2027. - 28.04.2027." [Broj osoba …] [Min. boravak …] [label]
    [VAŽI DO …] [25%] € old € new "po osobi po danu". After "POPUSTI" / "DOPLATE" come
    discount / supplement rows that start with their label instead of a date."""
    rows, extras = [], []
    mode, cur = "price", None

    def close():
        nonlocal cur
        if cur and cur.get("prices") is not None:
            p = cur.pop("prices")
            if mode == "price" and p:
                cur["price"], cur["was"] = p[-1], (p[0] if len(p) > 1 else None)
                rows.append(cur)
            elif mode != "price" and (p or cur.get("pct") is not None):
                cur["eur"] = p[-1] if p else None
                extras.append(cur)
        cur = None

    for ln in lines:
        up = ln.upper()
        if up in ("POPUSTI", "DOPLATE"):
            close()
            mode = "discount" if up == "POPUSTI" else "supplement"
            continue
        dr = _DATE_RANGE.match(ln)
        if mode == "price":
            if dr:
                close()
                cur = {"room": room, "board": board, "from": _iso(*dr.groups()[:3]), "to": _iso(*dr.groups()[3:]),
                       "prices": [], "label": None, "min_nights": None, "occupancy": None, "valid_until": None}
                continue
            if cur is None:
                continue
        else:
            if dr:
                if cur is not None:
                    cur.setdefault("periods", []).append((_iso(*dr.groups()[:3]), _iso(*dr.groups()[3:])))
                continue
            if cur is None or (cur.get("unit") and not (_PCT.match(ln) or _EUR.search(ln))):
                if _PER.match(ln) or _PCT.match(ln) or _EUR.search(ln) or _VREDI.match(ln):
                    continue
                close()
                cur = {"kind": mode, "label": ln, "room": room, "board": board, "pct": None, "prices": [],
                       "unit": None}
                continue
        # fields of the open row
        if (m := _OCC.match(ln)):
            cur["occupancy"] = {"persons": int(m.group(1)), "kids": int(m.group(2)),
                                "kid_ages": m.group(3).strip() if m.group(3) else None}
        elif (m := _MIN_STAY.match(ln)):
            cur["min_nights"] = int(m.group(1))
        elif (m := _VALID.search(ln)):
            cur["valid_until"] = _iso(*m.groups())
        elif (m := _PCT.match(ln.strip())):
            cur["pct"] = int(m.group(1))
        elif _EUR.search(ln):
            cur["prices"].extend(_num(x) for x in _EUR.findall(ln))
        elif _PER.match(ln):
            cur["unit"] = ln
            if mode == "price":
                close()
        elif _VREDI.match(ln):
            pass
        elif mode == "price" and cur.get("label") is None:
            cur["label"] = ln
    close()
    for r in rows:
        r.pop("pct", None)
    return {"rows": rows, "extras": extras}


def child_rules(extras: list[dict]) -> list[dict]:
    """Discount / supplement rows about children, de-duplicated across periods."""
    seen: dict[tuple, dict] = {}
    for e in extras:
        m = _CHILD.search(e.get("label") or "")
        if not m:
            continue
        key = (e["kind"], int(m.group(1)) if m.group(1) else None, _num(m.group(2)), _num(m.group(3)), e.get("pct"))
        r = seen.get(key)
        eur = e.get("eur")
        if r is None:
            seen[key] = {"kind": key[0], "child": key[1], "age_from": key[2], "age_to": key[3], "pct": key[4],
                         "eur_min": eur, "eur_max": eur, "unit": e.get("unit"), "label": _short(e["label"])}
        elif eur is not None:
            r["eur_min"] = eur if r["eur_min"] is None else min(r["eur_min"], eur)
            r["eur_max"] = eur if r["eur_max"] is None else max(r["eur_max"], eur)
    return list(seen.values())


# ------------------------------------------------------------------------ rooms ---

_UNIT_ID = re.compile(r'data-unitId="(\d+)"', re.I)
_UNIT_NAME = re.compile(r"<h4[^>]*data-unitName[^>]*>\s*(.*?)\s*</h4>", re.S | re.I)
_BEDS = re.compile(r"Broj le[žz]aja:\s*(?:<[^>]+>\s*)*(\d+)", re.I)
_MAXP = re.compile(r"Maksimalan broj osoba:\s*(?:<[^>]+>\s*)*(\d+)", re.I)
_SERVICES = re.compile(r'data-pricelistsService="([^"]+)"', re.I)
_MODAL_END = re.compile(r'<h5 class="modal-title[^"]*"[^>]*>\s*(?:CENOVNIK|PROGRAM PUTOVANJA|USLOVI PUTOVANJA)\s*</h5>',
                        re.I)
_PANE = re.compile(r'class="tab-pane[^"]*"\s+id="(pricelist|amenities)-(\d+)(?:-(\d+))?"', re.I)
_TAB_LABEL = re.compile(r'id="pricelist-tab-(\d+)-(\d+)"[^>]*>\s*([^<]+?)\s*<', re.I)
_FROM_PRICE = re.compile(r"Cena (?:po danu |po osobi )?od", re.I)

_SEP_NAME = re.compile(r"\b(?:[1-4]|one|two|three)[\s-]*bed[\s-]*rooms?\b|\b(?:jedno|dvo|tro)sob\w*\s+apartm|"
                       r"apartm\w*\s+sa\s+(?:jednom\s+|dve\s+|dvije\s+)?spava[cć]", re.I)
_SEP_TEXT = re.compile(
    r"(?:zasebn|odvojen)\w*\s+spava[cć]\w*\s+sob\w*|"
    r"spava[cć]\w*\s+sob\w*[^.;]{0,60}?\bi\s+(?:prostran\w*\s+|velik\w*\s+)?dnevn\w*\s+(?:sob|boravk)\w*|"
    r"spava[cć]\w*\s+i\s+dnevn\w*\s+sob\w*|"
    r"separate\s+bedroom|apartm\w*\s+sa\s+(?:jednom\s+|dve\s+)?spava[cć]\w*\s+sob\w*", re.I)
_FAMILY_NAME = re.compile(r"\bfamily\b|porodi[cč]n|obiteljsk", re.I)
_TWO_PLUS_TWO = re.compile(r"2\s*odrasl\w*(?:\s+osob\w*)?\s*\+\s*2\s*(?:dec|djec|dete|child)", re.I)


def parse_rooms(page: str) -> tuple[list[dict], list[dict], set[str]]:
    """Room units with name, capacity, separate-bedroom/family flags, their boards and price rows.
    Returns (rooms, price_rows_and_extras_per_room, board codes from structured tabs)."""
    body = scope(page)
    order: list[tuple[str, int]] = []
    for m in _UNIT_ID.finditer(body):
        if m.group(1) not in {u for u, _ in order}:
            order.append((m.group(1), m.start()))
    rooms, lists, structured = [], [], set()
    for i, (uid, start) in enumerate(order):
        if i + 1 < len(order):
            end = order[i + 1][1]
        else:
            me = _MODAL_END.search(body, start)
            end = me.start() if me else len(body)
        block = body[start:end]
        nm = _UNIT_NAME.search(block)
        if not nm:
            continue                    # an id repeated in the page-wide price list, not a room card
        name = re.sub(r"^Soba\s+", "", " ".join(htmllib.unescape(_TAG.sub(" ", nm.group(1))).split()))
        services: dict[str, str] = {}
        sm = _SERVICES.search(block)
        if sm:
            try:
                raw = json.loads(htmllib.unescape(sm.group(1)))
                services = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
            except ValueError:
                services = {}
        for _, svc, label in _TAB_LABEL.findall(block):
            services.setdefault(svc, htmllib.unescape(label))
        boards = sorted({c for v in services.values() for c in board_codes(v)})
        structured.update(boards)
        panes = list(_PANE.finditer(block))
        desc_lines, room_lists = [], []
        for j, p in enumerate(panes):
            seg = block[p.start():panes[j + 1].start() if j + 1 < len(panes) else len(block)]
            if p.group(1).lower() == "amenities":
                desc_lines += lines_of(seg)
            else:
                svc = p.group(3)
                codes = board_codes(services.get(svc, "")) if svc else []
                room_lists.append(parse_pricelist(lines_of(seg), name, codes[0] if len(codes) == 1 else None))
        desc = " ".join(desc_lines)
        beds, maxp = _BEDS.search(block), _MAXP.search(block)
        cap = int(maxp.group(1)) if maxp else int(beds.group(1)) if beds else None
        lines = lines_of(block)
        from_eur = was_eur = None
        for k, ln in enumerate(lines):
            if _FROM_PRICE.match(ln):
                nums: list[float] = []
                for nxt in lines[k + 1:k + 6]:          # "VAŽI DO …", "€ 81", "€ 73" (old, new)
                    found = [_num(x) for x in _EUR.findall(nxt)]
                    if found:
                        nums += found
                    elif nums or not _VALID.search(nxt):
                        break
                if nums:
                    from_eur, was_eur = nums[-1], (nums[0] if len(nums) > 1 else None)
                break
        sep_hit = _SEP_NAME.search(name) or _SEP_TEXT.search(desc)
        fam_hit = _FAMILY_NAME.search(name) or _TWO_PLUS_TWO.search(desc)
        rooms.append({
            "id": uid, "name": name, "max_persons": cap,
            "separate_bedroom": True if sep_hit else None,
            "family": True if (fam_hit or (cap or 0) >= 4) else None,
            "boards": boards, "from_eur": from_eur, "was_eur": was_eur,
            "evidence": _short(sep_hit.group(0)) if sep_hit else None,
        })
        lists += room_lists
    return rooms, lists, structured


# --------------------------------------------------------------- family facts ---

_SAND = re.compile(r"\b(?:pe[sš][cč]an\w*|pje[sš][cč]an\w*|pesk\w*|pjesk\w*|pesak|pijesak|pijes[ck]\w*|sand\w*)", re.I)
_PEBBLE = re.compile(r"\b(?:[sš]ljun\w*|oblut\w*|pebbl\w*|shingle)", re.I)
_BEACHY = re.compile(r"pla[zž]|obal|\bmor[ea]\b|beach|uvala", re.I)
_KIDS_POOL = re.compile(r"bazen\w*\s+za\s+(?:decu|djecu|najmla\w*)|de[cč]ij?i\s+bazen|dje[cč]ij?i\s+bazen|"
                        r"kids'?\s*pool|children'?s\s+pool|baby\s+pool", re.I)
_KIDS_CLUB = re.compile(r"de[cč]ij?i\s+klub|dje[cč]ij?i\s+klub|mini[\s-]?klub|mini[\s-]?club|kids'?\s*club|"
                        r"klub\s+za\s+(?:decu|djecu)", re.I)
_CLUB_AGE = re.compile(r"(?:od|from)\s*(\d{1,2})\s*(?:do\s*\d{1,2}\s*)?(?:god|yrs|years)|\(\s*(\d{1,2})\s*-\s*\d{1,2}\s*"
                       r"(?:god\w*)?\s*\)", re.I)
_PLAYGROUND = re.compile(r"de[cč]ij?e?\s+igrali[sš]t\w*|dje[cč]ij?e?\s+igrali[sš]t\w*|igrali[sš]t\w*\s+za\s+decu|"
                         r"playground", re.I)
_PLAYROOM = re.compile(r"igraonic\w*|kids'?\s*room|playroom", re.I)
_ANIMATION = re.compile(r"animaci\w*|animator\w*", re.I)
_KIDS_WORD = re.compile(r"\bdec\w*|\bdjec\w*|\bdete\w*|najmla\w*|kids?|childr", re.I)
_KIDS_WELCOME = re.compile(r"deca\s+dobrodo[sš]l\w*|djeca\s+dobrodo[sš]l\w*|children\s+welcome", re.I)
_ADULTS_ONLY = re.compile(r"samo\s+za\s+odrasle|adults?[\s-]+only", re.I)
_ADULT_AGE = re.compile(r"odrasle\s*(\d{1,2})\s*\+|min\.?\s*(\d{1,2})\s*god", re.I)
_COT = re.compile(r"krevetac\w*|kreveca\b|bebi\s+krevet\w*|krevet\w*\s+za\s+beb\w*|baby\s+cot\w*|\bcots?\b|\bcribs?\b",
                  re.I)
_FREE_TEXT = re.compile(r"(?:dec[aei]|djec[aei]|dete|dijete)\w*\s+(?:do|od\s*0\s*do)\s*(\d{1,2}(?:[.,]\d+)?)\s*"
                        r"god\w*[^.;]{0,40}?(?:besplatn\w*|gratis|free)", re.I)
_BEACH_NUM = re.compile(r"(\d{1,4})\s*(m|km)\b\.?\s+od\s+(?:\w+\s+){0,4}?(?:pla[zž]\w*|mora|obale)", re.I)
_BEACHFRONT = re.compile(r"(?:direktno|neposredno|odmah)\s+na\s+(?:\w+\s+){0,3}?pla[zž]\w*|na\s+samoj\s+pla[zž]\w*|"
                         r"direkt\w*\s+pristup\w*\s+(?:\w+\s+){0,2}?pla[zž]\w*|beachfront", re.I)
_DIST_VAL = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(m|km)$", re.I)
_BEACH_LABEL = re.compile(r"^(pla[zž]a|pla[zž]e|more|beach)$", re.I)


def _sentences(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+|\s+#\s+", ln) if s.strip()]
    return out


def distances(lines: list[str]) -> dict[str, float]:
    """The "Udaljenosti" block: label line, then "80 m" / "1,2 km" line. Metres."""
    out: dict[str, float] = {}
    for i, ln in enumerate(lines):
        if ln.lower() != "udaljenosti":
            continue
        k = i + 1
        while k + 1 < len(lines):
            m = _DIST_VAL.match(lines[k + 1])
            if not m or _DIST_VAL.match(lines[k]):
                break
            v = _num(m.group(1)) * (1000 if m.group(2).lower() == "km" else 1)
            out.setdefault(lines[k], v)
            k += 2
    return out


def extract(page: str, url: str = "") -> dict:
    """One Olympic / Travelland hotel detail page → facts. Unknown stays absent."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    body = scope(page)
    lines = lines_of(body)
    sents = _sentences(lines)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    name = " ".join(htmllib.unescape(_TAG.sub(" ", h1.group(1))).split()) if h1 else ""
    fam: dict = {}
    ev: dict[str, str] = {}

    def setf(key, value, evidence):
        if key not in fam:
            fam[key] = value
            ev[key] = _short(evidence)

    # --- boards: structured price tabs first, then the "Usluga …" sentence(s)
    rooms, lists, structured = parse_rooms(page)
    board_ev = []
    if structured:
        board_ev.append("price tabs: " + ", ".join(sorted(structured)))
    text_boards: set[str] = set()
    for s in sents:
        if re.match(r"^usluga\b", s, re.I) or re.search(r"usluga\s+(?:u\s+hotelu\s+)?je\s+na\s+bazi", s, re.I):
            codes = board_codes(s)
            if codes:
                text_boards.update(codes)
                board_ev.append(_short(s, 80))
    boards = sorted(structured | text_boards, key=lambda c: "RO BB HB FB AI".split().index(c))
    if any(c in ("HB", "FB", "AI") for c in boards):
        setf("half_board", True, "board options " + "/".join(boards))

    # --- distances and beach
    dist = distances(lines)
    beach = next((v for k, v in dist.items() if _BEACH_LABEL.match(k)), None)
    if beach is not None:
        setf("beach_m", int(beach), f"Udaljenosti: plaža {int(beach)} m")
    else:
        for s in sents:
            m = _BEACH_NUM.search(s)
            if m:
                v = _num(m.group(1)) * (1000 if m.group(2).lower() == "km" else 1)
                setf("beach_m", int(v), m.group(0))
                break
    for s in sents:
        m = _BEACHFRONT.search(s)
        if m:
            setf("beachfront", True, m.group(0))
            break
    sand = next((m for s in sents if _BEACHY.search(s) and (m := _SAND.search(s))), None)
    pebble = next((m for s in sents if _BEACHY.search(s) and (m := _PEBBLE.search(s))), None)
    if sand and pebble:
        setf("beach_type", "mixed", f"{sand.group(0)} + {pebble.group(0)}")      # sand_beach stays unknown
    elif sand:
        setf("beach_type", "sand", sand.group(0))
        setf("sand_beach", True, sand.group(0))
    elif pebble:
        setf("beach_type", "pebble", pebble.group(0))
        setf("sand_beach", False, pebble.group(0))

    # --- kids' facilities
    for key, rx in (("kids_pool", _KIDS_POOL), ("playground", _PLAYGROUND), ("playroom", _PLAYROOM),
                    ("kids_welcome", _KIDS_WELCOME)):
        m = next((m for s in sents if (m := rx.search(s))), None)
        if m:
            setf(key, True, m.group(0))
    club = next(((s, m) for s in sents if (m := _KIDS_CLUB.search(s))), None)
    if club:
        setf("kids_club", True, club[1].group(0))
        tail = club[0][club[1].start():club[1].start() + 80]
        am = _CLUB_AGE.search(tail)
        if am:
            setf("kids_club_min_age", int(am.group(1) or am.group(2)), tail[:am.end()])
    anim = next((m for s in sents if (m := _ANIMATION.search(s)) and _KIDS_WORD.search(s)), None)
    if anim:
        setf("kids_animation", True, anim.group(0))
    adults = next(((s, m) for s in sents if (m := _ADULTS_ONLY.search(s))), None)
    if adults:
        setf("adults_only", True, adults[1].group(0))
        am = next((a for s in sents if _ADULTS_ONLY.search(s) or "odrasl" in s.lower() for a in [_ADULT_AGE.search(s)]
                   if a), None)
        if am:
            setf("adults_only_min_age", int(am.group(1) or am.group(2)), am.group(0))
    cot = next((m for s in sents if (m := _COT.search(s))), None)
    if cot:
        setf("cots_mentioned", True, cot.group(0))

    # --- rooms
    sep = next((r for r in rooms if r["separate_bedroom"]), None)
    if sep:
        setf("separate_bedroom", True, f"{sep['name']}: {sep['evidence']}")
    else:
        m = next((m for s in sents if (m := _SEP_TEXT.search(s))), None)
        if m:
            setf("separate_bedroom", True, m.group(0))
    fr = next((r for r in rooms if r["family"]), None)
    if fr:
        setf("family_room", True, f"{fr['name']} (max {fr['max_persons']})" if fr["max_persons"] else fr["name"])
    else:
        m = next((m for s in sents if (m := _TWO_PLUS_TWO.search(s))), None)
        if m:
            setf("family_room", True, m.group(0))

    # --- prices and child policy
    rows = [r for pl in lists for r in pl["rows"]]
    extras = [e for pl in lists for e in pl["extras"]]
    kids_rules = child_rules(extras)
    free = [r for r in kids_rules if r["kind"] == "discount" and r["pct"] == 100]
    generic = [r for r in free if r["child"] is None]
    first = [r for r in free if r["child"] == 1]
    second = [r for r in free if r["child"] == 2]
    if generic:
        setf("kids_free_max_age", min(r["age_to"] for r in generic), generic[0]["label"])
    elif first and second:
        setf("kids_free_max_age", min(max(r["age_to"] for r in first), max(r["age_to"] for r in second)),
             f"{first[0]['label']}; {second[0]['label']}")
    if first:
        setf("first_child_free_max_age", max(r["age_to"] for r in first), first[0]["label"])
    if "kids_free_max_age" not in fam:
        m = next((m for s in sents if (m := _FREE_TEXT.search(s))), None)
        if m:
            setf("kids_free_max_age", _num(m.group(1)), m.group(0))
    if any((r.get("occupancy") or {}).get("kids", 0) >= 2 for r in rows):
        setf("price_2plus2_listed", True, "price rows with Deca: 2")

    for k, v in list(fam.items()):              # 2.0 → 2 for tidy JSON
        if isinstance(v, float) and v.is_integer():
            fam[k] = int(v)
    return {
        "parser": PARSER_VERSION,
        "source": HOSTS.get(host),
        "url": url,
        "hotel_name": name,
        "board_options": boards,
        "board_evidence": board_ev,
        "family": fam,
        "evidence": ev,
        "child_policy": kids_rules,
        "distances": dist,
        "rooms": [{k: v for k, v in r.items() if k != "evidence"} for r in rooms],
        "price_table": rows,
    }


# ------------------------------------------------------------------------ cache ---

def cache_key(url: str) -> str:
    """Scheme/host/query-insensitive key: "olympic.rs/letovanje/.../102986/"."""
    p = urlparse(url)
    path = p.path if p.path.endswith("/") else p.path + "/"
    return p.netloc.lower().removeprefix("www.") + path


def load_cache(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("pages"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "pages": {}}


def save_cache(path: Path, cache: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _compact(facts: dict) -> dict:
    """What the cache keeps: everything except the bulky price table, which is cut to the
    family-relevant rows (2 kids listed) plus at most 40 others."""
    rows = facts.get("price_table") or []
    fam_rows = [r for r in rows if (r.get("occupancy") or {}).get("kids", 0) >= 2]
    rest = [r for r in rows if r not in fam_rows][:40]
    return {**facts, "price_table": fam_rows + rest, "price_rows_total": len(rows)}


# ----------------------------------------------------------------------- enrich ---

def _host_of(url: str) -> str | None:
    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    return host if host in HOSTS else None


def apply(facts: dict, hotel: dict | None, offers: list[dict]) -> tuple[int, int]:
    """Copy page facts into a hotel (only unknown keys) and set a single stated board on
    offers whose board is "?". Returns (facts_set, boards_set)."""
    n_facts = n_boards = 0
    if hotel is not None and facts.get("family"):
        fam = hotel.setdefault("family", {"verified": []})
        set_now = []
        for k in FAMILY_KEYS:
            if k in facts["family"] and fam.get(k) is None:
                fam[k] = facts["family"][k]
                set_now.append(k)
        n_facts = len(set_now)
        if set_now or facts.get("board_options"):
            hotel["enriched"] = {
                "url": facts.get("url"), "fetched": facts.get("fetched"), "keys": sorted(set_now),
                "evidence": {k: facts.get("evidence", {}).get(k) for k in set_now},
                "board_options": facts.get("board_options", []),
                "child_policy": facts.get("child_policy", []),
            }
    boards = facts.get("board_options") or []
    if len(boards) == 1:
        for o in offers:
            if o.get("board") in ("?", "", None):
                o["board"] = boards[0]
                o["board_from"] = "detail page"
                n_boards += 1
    return n_facts, n_boards


def _priority(offer: dict, hotel: dict | None) -> tuple:
    fam = (hotel or {}).get("family", {}) or {}
    musts = ("sand_beach", "beach_m") if (hotel or {}).get("season") == "summer" else ("separate_bedroom",)
    unknown = sum(fam.get(k) is None for k in musts)
    return (offer.get("board") != "?", -unknown)


def enrich(offers: list[dict], hotels, cfg: dict, today: date, budget: int | None = None,
           session: PoliteSession | None = None, cache_path: str | Path | None = None,
           fetch=None) -> dict:
    """Enrich Olympic/Travelland offers from their detail pages.

    offers   offer dicts (as built by the sources: "hotel", "url", "board" …); edited in place.
    hotels   list of hotel dicts or {id: hotel}; hotel["family"] edited in place.
    budget   max live page reads this run (default cfg["sources"]["enrich"]["budget"] or 10).
    fetch    optional callable(url) -> html, for tests; default PoliteSession.get.
    Returns run stats."""
    ecfg = (cfg.get("sources", {}) or {}).get("enrich", {}) or {}
    budget = int(ecfg.get("budget", 10) if budget is None else budget)
    max_age = int(ecfg.get("max_age_days", 7))
    path = Path(cache_path or ecfg.get("cache", DEFAULT_CACHE))
    by_id = hotels if isinstance(hotels, dict) else {h["id"]: h for h in hotels}
    cache = load_cache(path)
    pages = cache["pages"]
    stats = {"pages": 0, "fetched": 0, "fresh_cache": 0, "stale_cache": 0, "no_budget": 0, "skipped_blocked": 0, "failed": 0,
             "facts_set": 0, "boards_set": 0, "blocked": []}

    groups: dict[str, list[dict]] = {}
    for o in offers:
        if _host_of(o.get("url")):
            groups.setdefault(cache_key(o["url"]), []).append(o)
    order = sorted(groups, key=lambda k: min(_priority(o, by_id.get(o.get("hotel") or o.get("hotel_id")))
                                             for o in groups[k]))
    blocked: set[str] = set()
    getter = fetch
    dirty = False
    for key in order:
        group = groups[key]
        url = group[0]["url"]
        host = _host_of(url)
        stats["pages"] += 1
        entry = pages.get(key)
        age = (today - date.fromisoformat(entry["fetched"])).days if entry else None
        fresh = entry is not None and age is not None and 0 <= age < max_age and entry.get("parser") == PARSER_VERSION
        if fresh:
            stats["fresh_cache"] += 1
        elif budget > 0 and host not in blocked:
            if getter is None:
                s = session or PoliteSession(cfg["sources"].get("delay_seconds", 6), cfg["sources"].get("jitter_seconds", 4),
                                             cfg["sources"].get("timeout_seconds", 30))
                session, getter = s, s.get
            budget -= 1
            try:
                page = getter(url)
                facts = extract(page, url) if page else {"parser": PARSER_VERSION, "url": url, "missing": True,
                                                         "family": {}, "board_options": []}
                facts["fetched"] = today.isoformat()
                entry = pages[key] = _compact(facts)
                dirty = True
                stats["fetched"] += 1
            except Blocked as e:
                log.warning("enrich: %s blocked us, leaving it alone this run: %s", host, e)
                blocked.add(host)
                stats["blocked"].append(host)
                stats["failed"] += 1
            except (Unavailable, ValueError) as e:
                log.warning("enrich: skipped %s: %s", url, e)
                stats["failed"] += 1
            if entry is None:
                continue
        elif entry is not None:
            stats["stale_cache"] += 1               # older than a week, no budget left: still better than unknown
        else:
            stats["skipped_blocked" if host in blocked else "no_budget"] += 1
            continue
        for hid in {o.get("hotel") or o.get("hotel_id") for o in group}:
            mine = [o for o in group if (o.get("hotel") or o.get("hotel_id")) == hid]
            f, b = apply(entry, by_id.get(hid), mine)
            stats["facts_set"] += f
            stats["boards_set"] += b
    if dirty:
        save_cache(path, cache)
    log.info("enrich: %(pages)d pages, %(fetched)d read live, %(fresh_cache)d from cache, %(stale_cache)d stale, "
             "%(no_budget)d waiting for budget; %(facts_set)d facts and %(boards_set)d boards filled", stats)
    return stats
