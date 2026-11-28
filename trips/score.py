"""Scoring: hard family rules → Family Fit (0–100) → Deal quality (0–100) → tier.

Family Fit weights follow the family-first research (see FAMILY_W below):
    sleep setup 18 · beach (summer) / activities (winter) 22 · travel effort 15 ·
    kids' facilities 12 · kids' cost 8 · food 10 · health 5 · logistics 4 · reviews 6
times a confidence factor 0.85 + 0.15 × (share of known facts that are verified).

Deal quality ignores the agency's "was" price as proof. It trusts our own price
history first (≥3% below this offer's lowest price of the last N days, with at
least 3 checks over 2 days, blended with the median price), then the peer
comparison (cheaper per night than similar offers), and only then — at a
reduced weight — the stated discount (which alone can't lift an offer above "Great deal"). A price pushed up shortly before a "was"
claim is flagged `fake?`. Each offer also gets a "book now / can wait / watch"
signal with a reason and a confidence level. A "2+0" (adults-only) price never
outranks a comparable "2+2" one on price grounds.

A must-have that is unknown (2 cots, sandy beach, separate bedroom …) never
excludes a hotel, but caps the rating and creates a question for the hotel.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from statistics import median

TIERS = [
    (90, "once", "💎", "Once-in-a-lifetime"),
    (80, "exceptional", "🔥", "Exceptional deal"),
    (70, "great", "⭐", "Great deal"),
    (55, "good", "👍", "Good deal"),
    (0, "watch", "👀", "Worth a look"),
]
FULL_BOARDS = {"HB", "FB", "AI"}


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s)[:10])


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def kids_age_on(cfg: dict, when) -> float:
    """Twins' age in years on a date. Without a birthdate, assume the oldest a
    3-year-old on 2026-11-25 can be (safe side for cot and 'free under 4' limits)."""
    bd = cfg["family"].get("kids_birthdate") or "2022-11-26"
    return (_d(when) - _d(bd)).days / 365.25


def tier(score: float) -> dict:
    for floor, key, icon, label in TIERS:
        if score >= floor:
            return {"key": key, "icon": icon, "label": label}
    return {"key": "watch", "icon": "👀", "label": "Worth a look"}


# ----------------------------------------------------------------- family ---
#
# Family Fit = the sum of the points in `parts` (out of 100) × a confidence factor.
#
#   part        pts  summer                                   winter
#   sleep        18  family room / separate bedroom + 2 cots  separate bedroom + 2 cots + fits 4
#   beach        22  sand · distance (or beachfront) · shallow —
#   activities   22  —                                        ski kindergarten · kids' pool · playroom
#   travel       15  ≤3h drive = full, 5h limit = 40%, a direct flight 80%
#   kids         12  kids' club for age 3 · kids' pool · playground / playroom / animation
#   kids_cost     8  free-child age limits vs the twins' age on check-in
#   food         10  breakfast + dinner (HB offered but not priced = 75%)
#   health        5  doctor nearby
#   logistics     4  stroller-friendly
#   reviews       6  stars
#
# Each fact is worth 1 when yes and 0 when no. An unknown nice-to-have is worth 0.5 (neutral);
# an unknown must-have only 0.35, because it is a real risk for the parents (and it caps the rating). The confidence factor is 0.85 + 0.15 × the share of
# known facts the hotel itself confirmed, so agency/detail-page info counts 85 %.
# `explain` says in words where the non-obvious points come from.

FAMILY_W = {"sleep": 18, "place": 22, "travel": 15, "kids": 12, "kids_cost": 8, "food": 10,
            "health": 5, "logistics": 4, "reviews": 6}
UNK_MUST = 0.35                 # an unknown must-have (an unknown nice-to-have is 0.5)
UNVERIFIED_CONF = 0.85          # confidence when every known fact is agency / detail-page info
AVAILABLE = "available"        # checklist state: offered by the hotel, not included in this price
# Room names that mean a unit with a separate bedroom / two or more rooms.
ROOM_SEP = re.compile(r"\b(?:one|two|three|[1-4])[\s-]*bed[\s-]*rooms?\b|\b(?:two|three|[2-4])[\s-]*rooms?\b|"
                      r"\b(?:dvo|tro|[cč]etvoro)sob\w*|\bseparate\s+bedroom|spava[cć]\w*\s+sob\w*|"
                      r"\bmaisonette\b|\bduplex\b", re.I)
ROOM_CAP = re.compile(r"up to (\d+) guests|\bmax\.?\s*(\d+)\b", re.I)


def _fact(fam: dict, key: str):
    return fam.get(key)          # None = unknown


def _age_txt(age: float) -> str:
    return f"{int(age)}y {int((age % 1) * 12)}m"


def kids_cost(fam: dict, offer: dict, kids_age: float) -> tuple[float, str]:
    """0..1: how little the twins add to a stay here, from the detail page's free-child age limits
    vs the twins' age on check-in ("0–2 free" = free while younger than 2: the safe side for the
    family). Same for 2+0 and 2+2 offers: whether the price includes them is the deal's job."""
    both, first = _fact(fam, "kids_free_max_age"), _fact(fam, "first_child_free_max_age")
    age = _age_txt(kids_age)
    if both is not None and kids_age < both:
        return 1.0, f"Children stay free up to {both:g}: both twins ({age}) free"
    if first is not None and kids_age < first:
        return 0.6, f"1st child free up to {first:g}: one twin ({age}) free, the other pays"
    if both is not None or first is not None:
        lim = max(x for x in (both, first) if x is not None)
        return 0.15, f"Children free only up to {lim:g}: both twins ({age}) pay"
    return 0.4, ("Free-child age limit unknown (this price includes the twins)" if offer.get("occupancy") == "2+2"
                 else "Free-child age limit unknown: ask what the twins cost")


def family_fit(hotel: dict, offer: dict, cfg: dict, drive_min: float | None) -> dict:
    fam = hotel.get("family", {}) or {}
    verified = set(fam.get("verified", []))
    season = hotel["season"]
    kids_age = kids_age_on(cfg, offer["check_in"])
    reach_cfg = cfg["reach"]
    checklist: list[dict] = []
    failed: list[str] = []
    unknown_musts: list[str] = []
    questions: list[str] = []
    explain: dict[str, str] = {}

    def check(key, label, state, must=False, question=None):
        status = state if state == AVAILABLE else "unknown" if state is None else ("yes" if state else "no")
        checklist.append({"key": key, "label": label, "state": status, "must": must,
                          "verified": key in verified})
        if must and status == "no":
            failed.append(label)
        if must and status == "unknown":
            unknown_musts.append(label)
        if question and (status in ("unknown", AVAILABLE) or key not in verified) and status != "no":
            questions.append(question)

    def tri(v, unk=0.5):
        return unk if v is None else (1.0 if v else 0.0)

    # --- reach: direct flight from SKP or ≤ max drive (plus border buffer)
    total_drive = None
    if drive_min is not None:
        total_drive = drive_min + (reach_cfg["border_buffer_minutes"] if hotel.get("border") else 0)
    direct = bool(hotel.get("direct_flight_skp"))
    limit = reach_cfg["max_drive_minutes"]
    if direct:
        reach = True
    elif total_drive is None:
        reach = None
    elif total_drive <= limit:
        reach = True
    elif total_drive <= limit + reach_cfg.get("tolerance_minutes", 0):
        reach = None            # borderline: the free router is conservative — check the real route
    else:
        reach = False
    check("reach", "Direct flight or ≤5h drive", reach, must=True)
    banned = {c.upper() for c in cfg.get(hotel.get("season", ""), {}).get("exclude_countries", [])}
    if banned and (hotel.get("country") or "").upper() in banned:
        check("country", f"Not in {hotel['country'].upper()} (our {hotel['season']} rule)", False, must=True)
    if fam.get("adults_only"):                 # detail page says "adults only": never fits the twins
        check("adults_only", "Children welcome", False, must=True)
    # --- guest rating: the family's rule, 4.3+/5 (Google etc.) and 8.2+/10 (Booking etc.)
    from . import ratings as _ratings          # local import: ratings imports nothing from score
    rok, rwhy = _ratings.verdict(fam.get("ratings", []), _ratings.settings(cfg))
    if rok is False:
        check("rating", rwhy, False, must=True)
    else:
        check("rating", rwhy, rok, must=cfg.get("ratings", {}).get("unknown_is_must", True))
    if rok is not None:
        checklist[-1]["verified"] = True       # a published rating is a fact, not agency marketing

    # --- cots: 2 cots that take the twins at their age on the trip date
    cots_max = _fact(fam, "cots_max")
    cot_age_max = _fact(fam, "cot_age_max")
    need = cfg["family"]["cots_needed"]
    if cots_max is None or cot_age_max is None:
        cots_ok = None if cots_max is None or cots_max >= need else False
    else:
        cots_ok = cots_max >= need and cot_age_max >= kids_age
    age_txt = f"{int(kids_age)} years {int((kids_age % 1) * 12)} months"
    check("cots", f"{need} cots for twins aged {age_txt}", cots_ok, must=True,
          question=f"Can you guarantee {need} cots in one room for our twins, who will be {age_txt} old on "
                   f"{_d(offer['check_in']).strftime('%d.%m.%Y')}? What is your cot age limit, and are they "
                   f"full-size cots or travel cots?")
    cots_v = tri(cots_ok, unk=0.45 if fam.get("cots_mentioned") else UNK_MUST)

    board = offer.get("board", "")
    hb_offered = bool(_fact(fam, "half_board"))
    room = offer.get("room") or ""
    if season == "summer":
        s = cfg["summer"]
        sand = _fact(fam, "sand_beach")
        check("sand_beach", "Sandy beach", sand if s["need_sand"] else True, must=s["need_sand"],
              question="Is the beach in front of the hotel sand or pebbles, and how far out does the water stay shallow "
                       "for small children?")
        bm, front = _fact(fam, "beach_m"), bool(_fact(fam, "beachfront"))
        if front:
            near_ok, near = True, 1.0
        elif bm is None:
            near_ok, near = None, UNK_MUST
        else:
            near_ok = bm <= s["max_beach_m"]
            near = 1.0 if bm <= 50 else 0.8 if near_ok else 0.1
        check("beachfront", "On the beach" if front else f"Beach ≤{s['max_beach_m']} m", near_ok, must=True)
        if board in s["need_board"]:
            check("board", "Breakfast + dinner", True, must=True)
            food = 1.0
        elif board == "SC":
            # Whole villa / apartment: kitchen instead of breakfast + dinner. Kept (capped), not thrown out.
            check("board", "Self-catering — no breakfast/dinner", None, must=True)
            food = 0.5
        elif board == "?" and hb_offered:
            check("board", "Breakfast + dinner — available (check price)", AVAILABLE, must=True,
                  question="This price may be for bed & breakfast: what does half board (breakfast + dinner) add for "
                           "2 adults and 2 small children?")
            food = 0.75
            explain["food"] = "Half board is offered; the price shown may not include it"
        elif board == "?":
            check("board", "Breakfast + dinner", None, must=True,
                  question="Is half board (breakfast + dinner) available, and what does it cost for 2 adults and 2 "
                           "small children?")
            food = UNK_MUST
        else:
            check("board", "Breakfast + dinner", False, must=True)
            food = 0.2
        shallow = _fact(fam, "shallow_entry")
        check("shallow_entry", "Shallow, gradual entry", shallow)
        sand_v = 0.5 if sand is None and fam.get("beach_type") == "mixed" else tri(sand, unk=UNK_MUST)
        place = 0.5 * sand_v + 0.35 * near + 0.15 * tri(shallow)
        if sand is False:
            place *= 0.5                       # pebbles: the beach is half as useful to two toddlers
            explain["beach"] = "Pebble beach: beach points halved"
        elif front:
            explain["beach"] = "Beachfront (detail page)"
        sep = _fact(fam, "separate_bedroom")
        fr = _fact(fam, "family_room")
        room_v = 1.0 if sep else 0.85 if fr else 0.0 if fr is False else UNK_MUST
        sleep = 0.6 * room_v + 0.4 * cots_v
        check("family_room", "Family room fits 2+2", fr if not sep else True)
    else:
        w = cfg["winter"]
        sep = _fact(fam, "separate_bedroom")
        if sep is None and ROOM_SEP.search(room):
            sep = True
            explain["sleep"] = f"Separate bedroom from the room name ({ROOM_SEP.search(room).group(0)})"
        check("separate_bedroom", "Separate bedroom (cots in the other room)", sep, must=w["need_separate_bedroom"],
              question="Which room or apartment type has a separate bedroom for us, with space for 2 cots in the "
                       "other room?")
        if board == "SC":
            check("board", "Self-catering (own kitchen)", True)
            food = 0.9
        elif board in FULL_BOARDS:
            check("board", "Breakfast + dinner", True)
            food = 1.0
        elif board == "?" and hb_offered:
            check("board", "Breakfast + dinner — available (check price)", AVAILABLE)
            food = 0.8
        elif board == "?":
            check("board", "Breakfast + dinner", None)
            food = 0.5
        else:
            check("board", "Breakfast + dinner", False)
            food = 0.5
        ski = _fact(fam, "ski_school_from_3")
        check("ski_school", "Ski kindergarten from age 3", ski,
              question="Is there a ski kindergarten or snow play area that takes 3-year-olds, and how far is it?")
        cap = ROOM_CAP.search(room)
        cap = int(cap.group(1) or cap.group(2)) if cap else None
        fits4 = True if _fact(fam, "family_room") or (cap or 0) >= 4 else _fact(fam, "family_room")
        sleep = 0.55 * tri(sep, unk=UNK_MUST) + 0.3 * cots_v + 0.15 * tri(fits4)
        check("family_room", "Family room fits 2+2", sep)
        play = True if any(_fact(fam, k) for k in ("playroom", "kids_club", "kids_animation")) else None
        place = 0.6 * tri(ski) + 0.2 * tri(_fact(fam, "kids_pool")) + 0.2 * tri(play)

    kc = _fact(fam, "kids_club")
    kc_age = _fact(fam, "kids_club_min_age")
    kc_ok = None if kc is None else (bool(kc) and (kc_age is None or kc_age <= kids_age))
    check("kids_club", "Kids' club takes age 3", kc_ok,
          question="What is the minimum age for the kids' club, and do children need to be potty-trained?")
    check("kids_pool", "Kids' pool", _fact(fam, "kids_pool"))
    if offer.get("occupancy") != "2+2":
        questions.append("What is the total price for 2 adults and two 3-year-olds for these dates, including the cots "
                         "and the children's meals?")

    # --- component scores (0..1)
    if direct:
        travel = 0.8
    elif total_drive is None:
        travel = 0.5
    elif total_drive <= limit:
        travel = 1.0 - 0.6 * clamp((total_drive - 180) / (limit - 180))
    else:
        travel = 0.2                           # borderline: over the limit but within the tolerance
    extras = True if any(_fact(fam, k) for k in ("playground", "playroom", "kids_animation")) else None
    kids = 0.4 * tri(kc_ok) + 0.35 * tri(_fact(fam, "kids_pool")) + 0.25 * tri(extras)
    cost, explain["kids_cost"] = kids_cost(fam, offer, kids_age)
    health = tri(_fact(fam, "doctor_near"))
    logistics = tri(_fact(fam, "stroller_ok"))
    reviews = clamp((hotel.get("stars") or 3) / 5)
    vals = {"sleep": sleep, "place": place, "travel": travel, "kids": kids, "kids_cost": cost, "food": food,
            "health": health, "logistics": logistics, "reviews": reviews}
    parts = {("beach" if season == "summer" else "activities") if k == "place" else k: FAMILY_W[k] * v
             for k, v in vals.items()}
    raw = sum(parts.values())
    known = [c for c in checklist if c["state"] != "unknown"]
    conf = UNVERIFIED_CONF + (1 - UNVERIFIED_CONF) * (sum(c["verified"] for c in known) / len(known) if known else 0)
    return {
        "score": round(raw * conf, 1),
        "raw": round(raw, 1),
        "confidence": round(conf, 2),
        # points before the confidence factor; occupancy never changes them (price is the deal's job)
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "explain": explain,
        "price_covers_kids": offer.get("occupancy") == "2+2",
        "checklist": checklist,
        "failed": failed,
        "unknown_musts": unknown_musts,
        "questions": questions[:6],
        "drive_minutes": total_drive,
        "kids_age": round(kids_age, 2),
    }


# ------------------------------------------------------------------- deal ---
#
# Deal quality = points for (our price history · peer comparison · family price ·
# deadline · flexibility · reach). Every part is exported in `deal["parts"]`, so the
# dashboard can show where the score comes from.
#
# Verdicts:
#   real         ≥ real_min_pct below this offer's lowest price of the last history_days,
#                backed by ≥ min_observations checks over ≥ min_days days
#   unconfirmed  cheaper than our recorded low, but the history is still too thin to call it
#   fake?        a "was" claim while the price is not cheaper than before, or the price was
#                pushed up ≥ inflation_pct in the inflation_days before the claim appeared
#   stated       only the agency's "was" price (no history to check it against)
#   flat         history, no real saving, no claim
#   none         nothing to go on

DEAL_DEFAULTS = {
    "history_days": 30,          # baseline window
    "stated_weight": 0.5,        # unverified savings count this much
    "real_min_pct": 3,           # "real" = at least this far below the window's low
    "min_observations": 3,       # … backed by this many price checks
    "min_days": 2,               # … on at least this many different days
    "inflation_pct": 15,         # a rise this big shortly before a "was" claim = pre-sale inflation
    "inflation_days": 14,
    "book_now_days": 7,          # a deadline this close + price at its low → book now
    "near_low_pct": 3,           # "at or near its low" = within this of the window's low
    "trend_days": 14,            # trend looks at this many recent days
    "trend_pct": 3,              # fitted change over that span to count as rising / falling
}
# Deal-score weights (points out of 100).
W_HISTORY, W_PEERS, W_FAMILY_PRICE, W_DEADLINE, W_FLEX, W_REACH = 35, 20, 15, 10, 10, 10
ADULTS_ONLY_FAMILY_PRICE = 0.3   # share of the family-price points a 2+0 price earns
# A "2+0" price leaves the twins' cost unknown, so its price evidence (history + peers) is
# scaled down until even the best 2+0 price can't beat the family-price points a 2+2 offer
# gets for free: 55·w + 4.5 ≤ 15. A 2+0 offer then never outranks a comparable 2+2 offer
# (same family fit, deadline and reach) on price grounds, whatever either price does.
ADULTS_ONLY_PRICE_WEIGHT = W_FAMILY_PRICE * (1 - ADULTS_ONLY_FAMILY_PRICE) / (W_HISTORY + W_PEERS)
FAKE_CAP = 54
# A discount only the agency states (no price history of ours behind it) earns history points
# in proportion to the claim, full points only for a −50% claim (× stated_weight), and the offer
# can't rise above "Great deal": "Exceptional" and "Once-in-a-lifetime" need a verified saving.
STATED_FULL = 0.5
UNPROVEN_CAP = 79


def deal_settings(cfg: dict) -> dict:
    return {**DEAL_DEFAULTS, **(cfg.get("deal") or {})}


def per_night(o: dict) -> float:
    return o["history"][-1]["price_eur"] / max(1, o["nights"])


def _t(seen) -> float:
    """Snapshot time as fractional days (a date, or a 'YYYY-MM-DDTHH:MM' timestamp)."""
    s = str(seen)
    t = float(_d(s).toordinal())
    if len(s) >= 16 and s[10] in "T ":
        t += (int(s[11:13]) * 60 + int(s[14:16])) / 1440
    return t


def _checks(h: dict) -> int:
    """Price checks one snapshot stands for (db may fold repeat same-day checks into one row)."""
    return max(1, int(h.get("checks") or 1))


def _claim(h: dict) -> bool:
    return bool(h.get("was_eur")) and h["was_eur"] > h["price_eur"]


def _inflation(hist: list[dict], d: dict) -> dict | None:
    """Pre-sale inflation: the price rose ≥ inflation_pct within inflation_days before the
    current run of "was" claims began. Returns {"rise_pct", "claim_seen"} or None."""
    i = len(hist)
    while i > 0 and _claim(hist[i - 1]):
        i -= 1
    if i == len(hist) or i == 0:          # no claim now, or claimed since the first sighting
        return None
    claim_day = _d(hist[i]["seen"])
    start = claim_day - timedelta(days=d["inflation_days"])
    before = hist[:i]
    pre = [h for h in before if _d(h["seen"]) >= start]
    # the price in force when that window opened (if we saw it within the baseline window)
    anchor = [h for h in before if claim_day - timedelta(days=d["history_days"]) <= _d(h["seen"]) < start][-1:]
    lo, rise = None, 0.0
    for h in anchor + pre:
        p = h["price_eur"]
        lo = p if lo is None else min(lo, p)
        rise = max(rise, (p - lo) / lo)
    if rise * 100 >= d["inflation_pct"]:
        return {"rise_pct": round(rise * 100, 1), "claim_seen": str(hist[i]["seen"])[:10]}
    return None


def _trend(window: list[dict], d: dict) -> tuple[str, float | None, int]:
    """Least-squares price trend over the last trend_days: ("rising"|"falling"|"flat"|"unknown",
    fitted change in % over the span, span in days). Needs 3 checks on 2+ days."""
    if not window:
        return "unknown", None, 0
    end = _t(window[-1]["seen"])
    pts = [(_t(h["seen"]), h["price_eur"]) for h in window if _t(h["seen"]) >= end - d["trend_days"]]
    if len(pts) < 3 or len({int(x) for x, _ in pts}) < 2:
        return "unknown", None, 0
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    slope = sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x, _ in pts)
    span = pts[-1][0] - pts[0][0]
    pct = slope * span / my * 100
    word = "rising" if pct >= d["trend_pct"] else "falling" if pct <= -d["trend_pct"] else "flat"
    return word, round(pct, 1), max(1, round(span))


def _confidence(obs: int, days: int, d: dict) -> tuple[str, str]:
    if obs >= 2 * d["min_observations"] and days >= 2 * d["min_days"]:
        level = "high"
    elif obs >= d["min_observations"] and days >= d["min_days"]:
        level = "medium"
    else:
        level = "low"
    note = f"{obs} price check{'s' if obs != 1 else ''} over {days} day{'s' if days != 1 else ''}"
    if level == "low":
        note += " — too little history, treat as a hint"
    return level, note


def _signal(price: float, low: float | None, days_left: int | None, trend: str, trend_pct, span: int,
            d: dict) -> tuple[str, str]:
    """'book now' / 'can wait' / 'watch', with a one-line reason."""
    near_low = low is None or price <= low * (1 + d["near_low_pct"] / 100)
    ends = None if days_left is None else ("today" if days_left == 0 else
                                           f"in {days_left} day{'s' if days_left != 1 else ''}")
    if days_left is not None and 0 <= days_left <= d["book_now_days"]:
        if near_low:
            return "book now", (f"Offer ends {ends} and the price is at its {d['history_days']}-day low"
                                if low is not None else f"Offer ends {ends}; no earlier price to compare")
        return "watch", f"Offer ends {ends}, but it is €{price - low:,.0f} above its {d['history_days']}-day low"
    if days_left is not None and days_left < 0:
        return "watch", "The offer's deadline has passed — check it is still on"
    if trend == "rising":
        return "book now", f"Price up {trend_pct:.0f}% over the last {span} days"
    if trend == "flat":
        return "can wait", "Price steady and no deadline" if days_left is None else f"Price steady; offer runs {ends}"
    if trend == "falling":
        return "can wait", f"Price falling ({trend_pct:.0f}% over {span} days) — waiting may pay"
    return "watch", "Not enough price history to call it yet"


def deal_quality(offer: dict, peers: list[dict], cfg: dict, today: date, reach_ok: bool | None) -> dict:
    d = deal_settings(cfg)
    hist = offer["history"]
    now = hist[-1]
    price = now["price_eur"]
    now_day = _d(now["seen"])
    window = [h for h in hist if _d(h["seen"]) >= now_day - timedelta(days=d["history_days"])]
    earlier = [h["price_eur"] for h in window[:-1]]
    low = min(earlier) if earlier else None
    mid = median(earlier) if earlier else None
    vs_low = (low - price) / low if low else None
    vs_mid = (mid - price) / mid if mid else None
    observations = sum(_checks(h) for h in window)
    obs_days = len({_d(h["seen"]) for h in window})
    enough = observations >= d["min_observations"] and obs_days >= d["min_days"]
    claim = _claim(now)
    stated_pct = (now["was_eur"] - price) / now["was_eur"] if claim else None
    inflated = _inflation(hist, d) if claim else None
    real_min = d["real_min_pct"] / 100
    sw = d["stated_weight"]
    notes: list[str] = []

    if vs_low is not None and vs_low >= real_min and enough:
        verdict = "real"
        real_n = clamp((vs_low + vs_mid) / 2 / 0.25)       # vs the low and vs the typical price
        if inflated:
            notes.append(f"The \"was\" price looks inflated (up {inflated['rise_pct']:.0f}% before the sale), "
                         f"but it is still {vs_low * 100:.0f}% below our recorded low")
    elif inflated:
        verdict, real_n = "fake?", 0.0
        notes.append(f"Price rose {inflated['rise_pct']:.0f}% in the {d['inflation_days']} days before the "
                     f"\"was\" price appeared ({inflated['claim_seen']})")
    elif vs_low is not None and claim and (vs_low <= 0 or (enough and vs_low < real_min)):
        verdict, real_n = "fake?", 0.0
        notes.append(f"Agency says −{stated_pct * 100:.0f}%, but it is not cheaper than our recorded low "
                     f"(€{low:,.0f})")
    elif vs_low is not None and vs_low >= real_min:
        verdict = "unconfirmed"
        real_n = clamp(vs_low / 0.25) * sw
        notes.append(f"{vs_low * 100:.0f}% below our recorded low, but only {observations} checks over "
                     f"{obs_days} days (needs {d['min_observations']} over {d['min_days']})")
    elif claim:
        verdict, real_n = "stated", clamp(stated_pct / STATED_FULL) * sw
    elif vs_low is not None:
        verdict, real_n = "flat", 0.0
    else:
        verdict, real_n = "none", 0.0

    # Peers = same source, same occupancy and board: prices are only comparable like for like.
    same = [p for p in peers if p.get("key") != offer.get("key") and p.get("occupancy") == offer.get("occupancy")
            and p.get("source") == offer.get("source") and p.get("board") == offer.get("board")]
    peer_pct = None
    if len(same) >= 2:
        m = median(per_night(p) for p in same)
        peer_pct = (m - per_night(offer)) / m
    peer_n = 0.5 if peer_pct is None else clamp(0.5 + peer_pct / 0.5)

    family_price = offer.get("occupancy") == "2+2"
    price_w = 1.0 if family_price else ADULTS_ONLY_PRICE_WEIGHT
    if not family_price:
        notes.append(f"Price for 2 adults only: the twins' cost is unknown, so price evidence counts "
                     f"{price_w * 100:.0f}%")
    urgency, days_left = 0.0, None
    if now.get("valid_until"):
        days_left = (_d(now["valid_until"]) - today).days
        urgency = 1.0 if 0 <= days_left <= 7 else 0.5 if 0 <= days_left <= 30 else 0.0
    flex = 0.5                     # cancellation terms unknown for manual offers
    fit = 1.0 if reach_ok else 0.5 if reach_ok is None else 0.0
    parts = {
        "history": W_HISTORY * real_n * price_w,
        "peers": W_PEERS * peer_n * price_w,
        "family_price": W_FAMILY_PRICE * (1.0 if family_price else ADULTS_ONLY_FAMILY_PRICE),
        "deadline": W_DEADLINE * urgency,
        "flex": W_FLEX * flex,
        "reach": W_REACH * fit,
    }
    score = sum(parts.values())

    trend, trend_pct, span = _trend(window, d)
    signal, reason = _signal(price, low, days_left, trend, trend_pct, span, d)
    confidence, conf_note = _confidence(observations, obs_days, d)

    def pct(x):
        return None if x is None else round(x * 100, 1)

    return {
        "score": round(score, 1),
        "verdict": verdict,
        # real_pct is only set for a verified saving (the dashboard shows it as "Verified −x%")
        "real_pct": pct(vs_low) if verdict == "real" else None,
        "vs_low_pct": pct(vs_low),
        "vs_median_pct": pct(vs_mid),
        "stated_pct": pct(stated_pct),
        "peer_pct": pct(peer_pct),
        "days_left": days_left,
        "history_points": len(hist),
        "baseline_low": None if low is None else round(low, 2),
        "baseline_median": None if mid is None else round(mid, 2),
        "observations": observations,
        "observed_days": obs_days,
        "inflated": inflated,
        "trend": trend,
        "trend_pct": trend_pct,
        "signal": signal,
        "signal_reason": reason,
        "confidence": confidence,
        "confidence_note": conf_note,
        "parts": {k: round(v, 1) for k, v in parts.items()},
        "notes": notes,
    }


# ---------------------------------------------------------------- combine ---

def _rate_one(hotel: dict, offer: dict, peers: list[dict], cfg: dict, drive_min, today: date) -> dict:
    fam = family_fit(hotel, offer, cfg, drive_min)
    reach = next(c for c in fam["checklist"] if c["key"] == "reach")["state"]
    deal = deal_quality(offer, peers, cfg, today, {"yes": True, "no": False}.get(reach))
    w = cfg["score"]["family_weight"]
    overall = w * fam["score"] + (1 - w) * deal["score"]
    capped = False
    if fam["unknown_musts"] and overall > cfg["score"]["unknown_cap"]:
        overall, capped = cfg["score"]["unknown_cap"], True
    if deal["verdict"] == "fake?":
        overall = min(overall, FAKE_CAP)
    elif deal["verdict"] != "real" and overall > UNPROVEN_CAP:
        overall = UNPROVEN_CAP
        deal["notes"].append(f"Held at {UNPROVEN_CAP}: without a saving our own price history confirms, an "
                             f"offer can't go above Great deal")
    return {"overall": overall, "capped": capped, "excluded": bool(fam["failed"]), "family": fam, "deal": deal}


def comparable_family_offers(offer: dict, peers: list[dict], days: int = 7) -> list[dict]:
    """2+2 offers for the same hotel, nights and board, checking in within `days` of this one."""
    hid = offer.get("hotel_id")
    if hid is None:
        return []
    ci = _d(offer["check_in"])
    return [p for p in peers if p.get("hotel_id") == hid and p.get("occupancy") == "2+2"
            and p.get("key") != offer.get("key") and p.get("nights") == offer.get("nights")
            and p.get("board") == offer.get("board") and abs((_d(p["check_in"]) - ci).days) <= days]


def rate(hotel: dict, offer: dict, peers: list[dict], cfg: dict, drive_min, today: date) -> dict:
    r = _rate_one(hotel, offer, peers, cfg, drive_min, today)
    if offer.get("occupancy") != "2+2" and not r["excluded"]:
        # A 2+0 offer never outranks a 2+2 offer for the same stay: its low price leaves the twins out.
        rivals = [x for x in (_rate_one(hotel, p, peers, cfg, drive_min, today)
                              for p in comparable_family_offers(offer, peers)) if not x["excluded"]]
        if rivals:
            ceiling = min(x["overall"] for x in rivals)
            if r["overall"] > ceiling:
                r["overall"] = ceiling
                r["deal"]["notes"].append(f"Held at {ceiling:.0f}: a 2+2 price for the same stay scores "
                                          f"{ceiling:.0f}, and an adults-only price can't beat it")
    overall = r["overall"]
    return {
        "overall": round(overall, 1),
        "tier": tier(overall) if not r["excluded"] else {"key": "out", "icon": "✗", "label": "Doesn't fit"},
        "capped": r["capped"],
        "excluded": r["excluded"],
        "family": r["family"],
        "deal": r["deal"],
    }


def email_draft(hotel: dict, offer: dict, questions: list[str], cfg: dict) -> str:
    ci = _d(offer["check_in"])
    co = ci + timedelta(days=int(offer["nights"]))
    lines = [f"Subject: Family booking question – {ci:%d.%m.%Y}–{co:%d.%m.%Y}, 2 adults + twins", "",
             f"Hello {hotel['name']} team,", "",
             f"We are a family from Skopje (2 adults and young twins) looking at {offer.get('room') or 'a room'} "
             f"on {offer.get('board')} from {ci:%d.%m.%Y} to {co:%d.%m.%Y}. Before we book, could you please confirm in "
             f"writing:", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "Thank you very much!", ""]
    return "\n".join(lines)
