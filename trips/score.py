"""Scoring: hard family rules → Family Fit (0–100) → Deal quality (0–100) → tier.

Family Fit weights follow the family-first research:
    sleep setup 20 · beach (summer) / activities (winter) 20 · travel effort 15 ·
    kids' facilities 12 · food 10 · health & safety 8 · logistics 7 · reviews 8
times a confidence factor 0.6 + 0.4 × (share of known facts that are verified).

Deal quality ignores the agency's "was" price as proof. It trusts our own price
history first (below this offer's lowest price of the last N days), then the
peer comparison (cheaper per night than similar offers), and only then — at a
reduced weight — the stated discount.

A must-have that is unknown (2 cots, sandy beach, separate bedroom …) never
excludes a hotel, but caps the rating and creates a question for the hotel.
"""
from __future__ import annotations

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

def _fact(fam: dict, key: str):
    return fam.get(key)          # None = unknown


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

    def check(key, label, state, must=False, question=None):
        status = "unknown" if state is None else ("yes" if state else "no")
        checklist.append({"key": key, "label": label, "state": status, "must": must,
                          "verified": key in verified})
        if must and state is False:
            failed.append(label)
        if must and state is None:
            unknown_musts.append(label)
        if question and (state is None or key not in verified) and status != "no":
            questions.append(question)

    # --- reach: direct flight from SKP or ≤ max drive (plus border buffer)
    total_drive = None
    if drive_min is not None:
        total_drive = drive_min + (reach_cfg["border_buffer_minutes"] if hotel.get("border") else 0)
    direct = bool(hotel.get("direct_flight_skp"))
    if direct:
        reach = True
    elif total_drive is None:
        reach = None
    elif total_drive <= reach_cfg["max_drive_minutes"]:
        reach = True
    elif total_drive <= reach_cfg["max_drive_minutes"] + reach_cfg.get("tolerance_minutes", 0):
        reach = None            # borderline: the free router is conservative — check the real route
    else:
        reach = False
    check("reach", "Direct flight or ≤5h drive", reach, must=True)

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

    board = offer.get("board", "")
    if season == "summer":
        s = cfg["summer"]
        sand = _fact(fam, "sand_beach")
        check("sand_beach", "Sandy beach", sand if s["need_sand"] else True, must=s["need_sand"],
              question="Is the beach in front of the hotel sand or pebbles, and how far out does the water stay shallow "
                       "for small children?")
        bm = _fact(fam, "beach_m")
        check("beachfront", f"Beach ≤{s['max_beach_m']} m", None if bm is None else bm <= s["max_beach_m"], must=True)
        check("board", "Breakfast + dinner", None if board == "?" else board in s["need_board"], must=True,
              question="Is half board (breakfast + dinner) available, and what does it cost for 2 adults and 2 small "
                       "children?" if board == "?" else None)
        shallow = _fact(fam, "shallow_entry")
        check("shallow_entry", "Shallow, gradual entry", shallow)
    else:
        w = cfg["winter"]
        sep = _fact(fam, "separate_bedroom")
        check("separate_bedroom", "Separate bedroom (cots in the other room)", sep, must=w["need_separate_bedroom"],
              question="Which room or apartment type has a separate bedroom for us, with space for 2 cots in the "
                       "other room?")
        check("board", "Breakfast + dinner", None if board == "?" else board in FULL_BOARDS)
        check("ski_school", "Ski kindergarten from age 3", _fact(fam, "ski_school_from_3"),
              question="Is there a ski kindergarten or snow play area that takes 3-year-olds, and how far is it?")

    kc = _fact(fam, "kids_club")
    kc_age = _fact(fam, "kids_club_min_age")
    kc_ok = None if kc is None else (bool(kc) and (kc_age is None or kc_age <= kids_age))
    check("kids_club", "Kids' club takes age 3", kc_ok,
          question="What is the minimum age for the kids' club, and do children need to be potty-trained?")
    check("kids_pool", "Kids' pool", _fact(fam, "kids_pool"))
    check("family_room", "Family room fits 2+2", _fact(fam, "family_room") if season == "summer" else
          _fact(fam, "separate_bedroom"))
    if offer.get("occupancy") != "2+2":
        questions.append("What is the total price for 2 adults and two 3-year-olds for these dates, including the cots "
                         "and the children's meals?")

    # --- component scores (0..1)
    def tri(v, yes=1.0, unk=0.5, no=0.0):
        return unk if v is None else (yes if v else no)

    sleep = 0.6 * tri(_fact(fam, "family_room") if season == "summer" else _fact(fam, "separate_bedroom")) \
        + 0.4 * tri(cots_ok)
    if season == "summer":
        bm = _fact(fam, "beach_m")
        near = 0.5 if bm is None else (1.0 if bm <= 50 else 0.7 if bm <= 150 else 0.2)
        place = 0.5 * tri(_fact(fam, "sand_beach")) + 0.35 * near + 0.15 * tri(_fact(fam, "shallow_entry"))
    else:
        place = 0.6 * tri(_fact(fam, "ski_school_from_3")) + 0.4 * tri(_fact(fam, "kids_pool"))
    if direct:
        travel = 0.8
    elif total_drive is None:
        travel = 0.5
    else:
        travel = clamp(1 - (total_drive - 180) / (reach_cfg["max_drive_minutes"] - 180))
    kids = 0.5 * tri(kc_ok, unk=0.25) + 0.5 * tri(_fact(fam, "kids_pool"), unk=0.25)
    food = 1.0 if board in FULL_BOARDS else 0.5 if board == "?" else 0.3
    health = tri(_fact(fam, "doctor_near"))
    logistics = tri(_fact(fam, "stroller_ok"))
    reviews = clamp((hotel.get("stars") or 3) / 5)
    raw = (20 * sleep + 20 * place + 15 * travel + 12 * kids + 10 * food + 8 * health + 7 * logistics + 8 * reviews)
    known = [c for c in checklist if c["state"] != "unknown"]
    conf = 0.6 + 0.4 * (sum(c["verified"] for c in known) / len(known) if known else 0)
    return {
        "score": round(raw * conf, 1),
        "raw": round(raw, 1),
        "confidence": round(conf, 2),
        "checklist": checklist,
        "failed": failed,
        "unknown_musts": unknown_musts,
        "questions": questions[:6],
        "drive_minutes": total_drive,
        "kids_age": round(kids_age, 2),
    }


# ------------------------------------------------------------------- deal ---

def per_night(o: dict) -> float:
    return o["history"][-1]["price_eur"] / max(1, o["nights"])


def deal_quality(offer: dict, peers: list[dict], cfg: dict, today: date, reach_ok: bool | None) -> dict:
    d = cfg["deal"]
    hist = offer["history"]
    now = hist[-1]
    price = now["price_eur"]
    window_start = _d(now["seen"]) - timedelta(days=d["history_days"])
    earlier = [h["price_eur"] for h in hist[:-1] if _d(h["seen"]) >= window_start]
    real_pct = (min(earlier) - price) / min(earlier) if earlier else None
    was = now.get("was_eur")
    stated_pct = (was - price) / was if was else None

    if real_pct is not None:
        real_n = clamp(real_pct / 0.25)
        verdict = "real" if real_pct > 0 else ("fake?" if (stated_pct or 0) > 0 else "flat")
    elif stated_pct is not None:
        real_n = clamp(stated_pct / 0.25) * d["stated_weight"]
        verdict = "stated"
    else:
        real_n, verdict = 0.0, "none"

    # Peers = same source, same occupancy and board: prices are only comparable like for like.
    same = [p for p in peers if p["key"] != offer["key"] and p["occupancy"] == offer["occupancy"]
            and p["source"] == offer["source"] and p["board"] == offer["board"]]
    peer_pct = None
    if len(same) >= 2:
        m = median(per_night(p) for p in same)
        peer_pct = (m - per_night(offer)) / m
    peer_n = 0.5 if peer_pct is None else clamp(0.5 + peer_pct / 0.5)

    family_cost = 1.0 if offer["occupancy"] == "2+2" else 0.3
    urgency, days_left = 0.0, None
    if now.get("valid_until"):
        days_left = (_d(now["valid_until"]) - today).days
        urgency = 1.0 if 0 <= days_left <= 7 else 0.5 if 0 <= days_left <= 30 else 0.0
    flex = 0.5                     # cancellation terms unknown for manual offers
    fit = 1.0 if reach_ok else 0.5 if reach_ok is None else 0.0
    score = 35 * real_n + 20 * peer_n + 15 * family_cost + 10 * urgency + 10 * flex + 10 * fit
    return {
        "score": round(score, 1),
        "verdict": verdict,
        "real_pct": None if real_pct is None else round(real_pct * 100, 1),
        "stated_pct": None if stated_pct is None else round(stated_pct * 100, 1),
        "peer_pct": None if peer_pct is None else round(peer_pct * 100, 1),
        "days_left": days_left,
        "history_points": len(hist),
    }


# ---------------------------------------------------------------- combine ---

def rate(hotel: dict, offer: dict, peers: list[dict], cfg: dict, drive_min, today: date) -> dict:
    fam = family_fit(hotel, offer, cfg, drive_min)
    reach = next(c for c in fam["checklist"] if c["key"] == "reach")["state"]
    deal = deal_quality(offer, peers, cfg, today, {"yes": True, "no": False}.get(reach))
    w = cfg["score"]["family_weight"]
    overall = w * fam["score"] + (1 - w) * deal["score"]
    capped = False
    if fam["unknown_musts"] and overall > cfg["score"]["unknown_cap"]:
        overall, capped = cfg["score"]["unknown_cap"], True
    if deal["verdict"] == "fake?":
        overall = min(overall, 54)
    excluded = bool(fam["failed"])
    return {
        "overall": round(overall, 1),
        "tier": tier(overall) if not excluded else {"key": "out", "icon": "✗", "label": "Doesn't fit"},
        "capped": capped,
        "excluded": excluded,
        "family": fam,
        "deal": deal,
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
