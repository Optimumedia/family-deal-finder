"""Family prices from hotel detail pages: real 2+2 rows, estimated 2+2 totals, cheapest board.

Most Olympic / Travelland list prices are for 2 adults only ("2+0"), so they can't be
compared with real family prices. The hotel's detail page (read by trips/enrich.py) often
says more:

1. `family_offers()` — price rows that explicitly price **2 adults + 2 kids** whose stated
   ages fit the twins on that date ("Broj osoba: 2 (Deca: 2, Uzrast: 0-5 i 0-5)", priced per
   unit per day or per stay) become extra "2+2" offers in the normal offer shape. Their room
   text ends with "(family price from hotel page)". Rows priced per person are skipped: how
   the kids are charged there is not stated.
2. `estimate()` — for a 2+0 offer priced per person, the child policy gives an ESTIMATED
   2+2 total when it states a price for BOTH children at the twins' age (first child, second
   child, or "each child"). Several rules for the same child (they differ by room or period)
   → the dearest one is used, so the estimate errs high. It is stored as
   `family_price_est` + `family_price_basis` (plain language). `price_eur` and `occupancy`
   are never changed by an estimate.
3. `cheapest_board()` — when the offer's board is "?" and the page lists 2+ boards with
   prices, the board of the lowest per-person price is `board_cheapest` (the list card's
   "from" price is that board's price). `board` itself stays "?".

Nothing is guessed: a child without a stated rule, an unknown age range, or a per-unit price
means no estimate. Twins' ages come from score.kids_age_on(cfg, check-in date).
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .score import kids_age_on

FAMILY_TAG = "family price from hotel page"
MAX_FAMILY_OFFERS = 8                 # per hotel page: one per price period, earliest first
BOARD_ORDER = ("RO", "BB", "HB", "FB", "AI")

_PER_PERSON = re.compile(r"osob|per\s+person", re.I)
_PER_UNIT = re.compile(r"jedinic|per\s+unit", re.I)
_PER_STAY = re.compile(r"boravk|per\s+stay", re.I)
_BOARD_SUPP = re.compile(r"\b(?:HB|FB|AI|BB|polupansion|pun\w*\s+pansion|all\s*inclusive)\b", re.I)
_AGE_RANGE = re.compile(r"(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)")


def _f(s: str) -> float:
    return float(s.replace(",", "."))


def in_range(age: float, lo, hi) -> bool:
    """"2 - 11" on a price list means 2.00 to 11.99 years; "0 - 1.99" means up to 1.99."""
    if lo is None or hi is None:
        return False
    lo, hi = float(lo), float(hi)
    top = hi + 1 if hi.is_integer() else hi + 1e-9
    return lo <= age < top


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _eur(x: float) -> str:
    return f"€{x:,.0f}" if abs(x - round(x)) < 0.005 or x >= 100 else f"€{x:,.2f}"


def _pct(x: float) -> str:
    return f"{x:.0f} %" if abs(x - round(x)) < 0.05 else f"{x:.1f} %"


# --------------------------------------------------------------- 1. real 2+2 rows ---

def kid_ranges(text: str | None) -> list[tuple[float, float]]:
    """"0-5 i 0-5" → [(0, 5), (0, 5)]."""
    return [(_f(a), _f(b)) for a, b in _AGE_RANGE.findall(text or "")]


def is_family_row(row: dict, age: float) -> bool:
    """A price row for exactly 2 paying adults + 2 kids whose stated ages fit the twins."""
    occ = row.get("occupancy") or {}
    if occ.get("persons") != 2 or occ.get("kids") != 2:
        return False
    ranges = kid_ranges(occ.get("kid_ages"))
    return len(ranges) == 2 and all(in_range(age, lo, hi) for lo, hi in ranges)


def _row_multiplier(row: dict, nights: int) -> int | None:
    unit = row.get("unit") or ""
    if _PER_STAY.search(unit):
        return 1
    if _PER_UNIT.search(unit):
        return nights
    return None                       # per person (kids' share unstated) or unknown unit


def family_offers(facts: dict, base_offers: list[dict], cfg: dict, today: date) -> list[dict]:
    """Extra "2+2" offers from a page's explicit 2-adults-2-kids price rows.

    One offer per price period (the cheapest fitting room in it), stays of the base offers'
    length starting on the period's first day (or today), at most MAX_FAMILY_OFFERS."""
    if not base_offers:
        return []
    base = base_offers[0]
    nights0 = int(base.get("nights") or 5)
    boards = facts.get("board_options") or []
    best: dict[tuple[str, str], dict] = {}
    for row in facts.get("price_table") or []:
        if not row.get("from") or not row.get("to") or row.get("price") is None:
            continue
        nights = max(nights0, int(row.get("min_nights") or 0))
        start = max(_d(row["from"]), today)
        if start + timedelta(days=nights) > _d(row["to"]) + timedelta(days=1):
            continue                  # the stay doesn't fit in this price period any more
        if not is_family_row(row, kids_age_on(cfg, start)):
            continue
        mult = _row_multiplier(row, nights)
        if mult is None:
            continue
        price = round(float(row["price"]) * mult, 2)
        key = (row["from"], row["to"])
        if key not in best or price < best[key]["price_eur"]:
            board = row.get("board") or (boards[0] if len(boards) == 1 else "?")
            was = row.get("was")
            best[key] = {
                "hotel": base.get("hotel") or base.get("hotel_id"),
                "source": base["source"],
                "url": base["url"],
                "seen": base.get("seen") or today.isoformat(),
                "check_in": start.isoformat(),
                "nights": nights,
                "board": board,
                "room": f"{row.get('room') or 'room'} ({FAMILY_TAG})",
                "occupancy": "2+2",
                "price_eur": price,
                "was_eur": round(float(was) * mult, 2) if was and float(was) > float(row["price"]) else None,
                "discount_label": row.get("label") if was else None,
                "valid_until": row.get("valid_until"),
                "family_price_from": "hotel page",
                "family_price_basis": (f"The hotel page prices {row.get('room') or 'this room'} for 2 adults + 2 kids "
                                       f"aged {(row.get('occupancy') or {}).get('kid_ages')}: "
                                       f"{_eur(float(row['price']))} {row.get('unit') or ''}".strip()),
            }
    out = sorted(best.values(), key=lambda o: o["check_in"])
    return out[:MAX_FAMILY_OFFERS]


# ------------------------------------------------------------ 2. estimated 2+2 ---

def _child_costs(policy: list[dict], n: int, age: float, adult_share: float, nights: int) -> list[tuple[float, str]]:
    """(cost for the whole stay, plain-language rule) for child number n (1 or 2)."""
    out = []
    word = "first" if n == 1 else "second"
    for r in policy or []:
        if r.get("child") not in (n, None) or not in_range(age, r.get("age_from"), r.get("age_to")):
            continue
        if r.get("kind") == "discount" and r.get("pct") is not None:
            pct = float(r["pct"])
            share = max(0.0, 1 - pct / 100)
            who = f"the {word} child" if r.get("child") == n else "each child"
            out.append((share * adult_share,
                        f"{who} stays free" if share == 0 else f"{who} pays {_pct(share * 100)} of an adult"))
        elif (r.get("kind") == "supplement" and r.get("child") == n and r.get("eur_max") is not None
              and _PER_PERSON.search(r.get("unit") or "") and re.search(r"dan|day|no[cć]", r.get("unit") or "", re.I)
              and not _BOARD_SUPP.search(r.get("label") or "")):
            eur = float(r["eur_max"])
            out.append((eur * nights, f"the {word} child pays {_eur(eur)} a night"))
    return out


def estimate(offer: dict, policy: list[dict], rooms: list[dict] | None, cfg: dict) -> tuple[float, str] | None:
    """Estimated 2+2 total for a 2+0 offer priced per person, or None when the page doesn't
    state enough. Returns (eur, basis)."""
    if offer.get("occupancy") != "2+0" or not policy:
        return None
    if not _PER_PERSON.search(offer.get("room") or ""):
        return None                   # a per-unit price may already include the kids; can't tell
    if rooms and all((r.get("max_persons") or 0) < 4 for r in rooms if r.get("max_persons") is not None) \
            and any(r.get("max_persons") is not None for r in rooms):
        return None                   # no room on the page sleeps 4
    adults = int((cfg.get("family") or {}).get("adults", 2))
    nights = int(offer.get("nights") or 0)
    price = float(offer.get("price_eur") or 0)
    if adults <= 0 or nights <= 0 or price <= 0:
        return None
    age = kids_age_on(cfg, offer["check_in"])
    share = price / adults
    parts, total, ranged = [], price, False
    for n in (1, 2):
        costs = _child_costs(policy, n, age, share, nights)
        if not costs:
            return None
        cost, text = max(costs, key=lambda c: c[0])         # dearest stated rule: err high
        if len({round(c[0], 2) for c in costs}) > 1:
            ranged = True
        total += cost
        parts.append(text)
    extra = total - price
    total = round(total, 0)
    rule = " and ".join(dict.fromkeys(parts))          # "each child stays free" once
    head = "Both kids stay free" if extra < 0.5 else f"+{_pct(extra / price * 100)} for the kids"
    basis = f"Estimate from the hotel's child policy for kids aged {int(age)} on {offer['check_in']}: {rule}. {head}"
    if ranged:
        basis += " (the page lists different rules per room or period; the dearest one is used)"
    basis += ". Needs a room for 4, which may cost more than the cheapest unit."
    return float(total), basis


# --------------------------------------------------------------- 3. cheapest board ---

def board_prices(rows: list[dict]) -> dict[str, float]:
    """Lowest per-person price per board in a page's price rows."""
    out: dict[str, float] = {}
    for r in rows or []:
        b, p = r.get("board"), r.get("price")
        if b in BOARD_ORDER and p is not None and _PER_PERSON.search(r.get("unit") or "") \
                and not (r.get("occupancy") or {}).get("kids"):
            out[b] = min(out.get(b, float("inf")), float(p))
    return out


def cheapest_board(prices: dict[str, float], board_options: list[str]) -> tuple[str, str] | None:
    """(board, basis) when 2+ boards are priced and one is strictly the cheapest."""
    priced = {b: p for b, p in (prices or {}).items() if b in (board_options or prices)}
    if len(priced) < 2:
        return None
    ranked = sorted(priced.items(), key=lambda kv: kv[1])
    (b0, p0), (b1, p1) = ranked[0], ranked[1]
    if p0 >= p1:
        return None
    others = ", ".join(f"{b} from {_eur(p)}" for b, p in ranked[1:])
    return b0, f"Cheapest price on the hotel page is {b0} ({_eur(p0)} per person a night); {others}"


# ----------------------------------------------------------------------- glue ---

def annotate(offer: dict, enriched: dict | None, cfg: dict) -> dict:
    """The extra fields for one offer from a hotel's stored page facts (hotel["enriched"]):
    family_price_est / family_price_basis and board_cheapest / board_cheapest_basis.
    Only offers from the same site as the page are annotated."""
    if not enriched:
        return {}
    host = _host(enriched.get("url"))
    if host and _host(offer.get("url")) != host:
        return {}
    out: dict = {}
    est = estimate(offer, enriched.get("child_policy") or [], enriched.get("rooms"), cfg)
    if est:
        out["family_price_est"], out["family_price_basis"] = est
    if offer.get("board") in ("?", "", None):
        cb = cheapest_board(enriched.get("board_prices") or {}, enriched.get("board_options") or [])
        if cb:
            out["board_cheapest"], out["board_cheapest_basis"] = cb
    return out


def _host(url: str | None) -> str | None:
    m = re.match(r"^\w+://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else None
