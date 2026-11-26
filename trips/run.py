"""One run: load hotels + offers → price history → drive time → score → alerts → docs/data.json → digest.

    python -m trips.run            # normal run
    python -m trips.run --offline  # skip the drive-time lookup (tests / no internet)
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

from . import conditions, db, dedupe, digest, enrich, family_prices, flights, geo, geocode, health, ratings, score, validate
from .http import PoliteSession
from .sources import al_me_coast, bg_more, bgski, charters, flight_hotels, gr_apartments, gr_hotel_prices, hotel_direct, kopaonik, manual, micazu, mk_agencies, mk_local, oliverstravels, olympic, rentals, rs_agencies, travelland

# Sources that find hotels/villas and prices (agencies, villa sites, owner rentals).
AUTO_SOURCES = (travelland, olympic, mk_agencies, bgski, charters, kopaonik, rs_agencies, al_me_coast, bg_more, gr_apartments, gr_hotel_prices, mk_local, flight_hotels, oliverstravels, rentals, micazu)

log = logging.getLogger("trips")


def load_config(path: str | Path = "config.toml", local: str | None = "config.local.toml") -> dict:
    """config.toml (public, in git) + config.local.toml next to it (private, git-ignored: e.g. the
    twins' birthdate). Local values override the public ones, table by table."""
    cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    lp = Path(path).with_name(local) if local else None
    if lp and lp.exists():
        for section, values in tomllib.loads(lp.read_text(encoding="utf-8")).items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                cfg[section] = {**cfg[section], **values}
            else:
                cfg[section] = values
    return cfg


def build(con, cfg: dict, today: date, offline: bool = False) -> tuple[list[dict], list[dict]]:
    hotels = db.hotels(con)
    geocode.apply(hotels, cfg, today, offline=offline)   # hotel-level pins (off unless [geocode] enabled)
    ratings.apply(hotels, cfg, today, offline=offline)   # Google rating via the official Places API (needs a key)
    offers = db.offers(con)
    flights.apply(hotels, cfg, offers)                   # direct SKP flight to an airport near the hotel, in the trip month
    home = (cfg["family"]["home_lat"], cfg["family"]["home_lng"])
    drives = {hid: db.cached_drive(con, hid, h["lat"], h["lng"]) for hid, h in hotels.items()} if offline \
        else geo.drive_minutes(con, hotels, home)
    estimated = set() if offline else set(geo.last_estimated)
    lim = validate.limits(cfg)
    photos = db.images(con)
    camps = db.campaigns(con, since=(today - timedelta(days=3)).isoformat())
    items, alerts = [], []
    for o in offers:
        h = hotels.get(o["hotel_id"])
        if not h:
            log.warning("offer for unknown hotel %s — add it to data/hotels.toml", o["hotel_id"])
            continue
        last = o["history"][-1]
        why = validate.problems({**o, "hotel": o["hotel_id"], "price_eur": last["price_eur"],
                                 "was_eur": last.get("was_eur")}, today, lim, h)
        if why:                       # past stay date, or saved before a rule existed: keep history, don't publish
            log.info("not published %s: %s", o["key"], "; ".join(why))
            continue
        peers = [p for p in offers if hotels.get(p["hotel_id"], {}).get("season") == h["season"]]
        r = score.rate(h, o, peers, cfg, drives.get(h["id"]), today)
        now = o["history"][-1]
        item = {
            "key": o["key"], "hotel_id": h["id"], "kind": h.get("kind", "hotel"), "name": h["name"], "stars": h.get("stars"), "area": h.get("area"),
            "season": h["season"], "lat": h.get("lat"), "lng": h.get("lng"), "notes": h.get("notes"),
            "flight": h.get("flight"),
            "drive_estimate": h["id"] in estimated,   # straight-line guess: the router was down this run
            "image": h.get("image") or photos.get(h["id"]),
            "source": o["source"], "url": o["url"], "check_in": o["check_in"], "nights": o["nights"],
            "board": o["board"], "room": o["room"], "occupancy": o["occupancy"],
            "price_eur": now["price_eur"], "was_eur": now.get("was_eur"), "discount_label": now.get("discount_label"),
            "valid_until": now.get("valid_until"), "first_seen": o["first_seen"], "last_seen": o["last_seen"],
            "history": [{"seen": s["seen"], "price_eur": s["price_eur"]} for s in o["history"]],
            **{k: r[k] for k in ("overall", "tier", "capped", "excluded", "family", "deal")},
            "campaigns": [{k: c[k] for k in ("title", "pct", "valid_until", "url")} for c in camps.get(h["id"], [])],
        }
        item.update(family_prices.annotate(item, h.get("enriched"), cfg))
        items.append(item)
        alerts += _alerts(con, item, cfg, today)
    items.sort(key=lambda i: (i["excluded"], -i["overall"]))
    return items, alerts


def _alerts(con, it: dict, cfg: dict, today: date) -> list[dict]:
    out = []
    when = today.isoformat()
    price = f"€{it['price_eur']:,.0f} ({it['occupancy']}, {it['nights']} nights {it['board']}, from {it['check_in']})"
    if it["excluded"]:
        return out
    d = it["deal"]
    sig = {"signal": d.get("signal"), "signal_reason": d.get("signal_reason")}
    if it["tier"]["key"] in ("great", "exceptional", "once") or it["overall"] >= 60:
        if db.mark_alert(con, f"new|{it['key']}", when):
            out.append({"type": "new", **sig, "icon": it["tier"]["icon"], "url": it["url"],
                        "text": f"New: {it['name']} — {price}, score {it['overall']:.0f}"})
    h = it["history"]
    if len(h) >= 2:
        prev = min(x["price_eur"] for x in h[:-1])
        drop = (prev - h[-1]["price_eur"]) / prev * 100
        if drop >= cfg["deal"]["drop_alert_pct"] and db.mark_alert(con, f"drop|{it['key']}|{h[-1]['seen']}", when):
            out.append({"type": "drop", **sig, "icon": "📉", "url": it["url"],
                        "text": f"Price drop −{drop:.0f}%: {it['name']} — {price}"})
    dl = d["days_left"]
    if dl is not None and 0 <= dl <= 3 and db.mark_alert(con, f"deadline|{it['key']}|{it['valid_until']}", when):
        out.append({"type": "deadline", **sig, "icon": "⏰", "url": it["url"],
                    "text": f"Offer ends in {dl} day{'s' if dl != 1 else ''} ({it['valid_until']}): {it['name']} — {price}"})
    if d.get("signal") == "book now" and d.get("confidence") != "low" and it["overall"] >= 55 \
            and db.mark_alert(con, f"book|{it['key']}|{h[-1]['seen'][:10]}", when):
        out.append({"type": "new", **sig, "icon": "🛎️", "url": it["url"], "text": f"Book now: {it['name']} — {price}"})
    return out


def export(items: list[dict], alerts: list[dict], cfg: dict, path: str | Path = "docs/data.json") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated": datetime.now().isoformat(timespec="minutes"),
        "family": {"adults": cfg["family"]["adults"], "kids": cfg["family"]["kids"], "home": cfg["family"]["home"],
                   "max_drive_minutes": cfg["reach"]["max_drive_minutes"]},
        "alerts": alerts,
        "items": items,
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


_DROP = re.compile(r"\b(hotel|apart|aparthotel|apartments?|apartmani|resort|spa|and|by|the|ex|holiday|hotels?)\b|\d\s*\*|[^\w\s]")


def norm_name(name: str) -> str:
    return " ".join(_DROP.sub(" ", name.lower()).split())


def _contains(a: str, b: str) -> bool:
    """One name inside the other, word-aligned, and the shorter one is at least 2 words
    (so a bare resort name like "bansko" never swallows "lion bansko")."""
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return len(short.split()) >= 2 and f" {short} " in f" {long_} "


def merge_auto(manual_hotels: list[dict], auto_hotels: list[dict], auto_offers: list[dict],
               images: dict[str, str] | None = None) -> list[dict]:
    """Auto-found hotels that match a hand-curated one (same season, same normalised name)
    are folded into it, so its verified family facts are kept. Returns the auto hotels to add.
    When `images` is given, the photo of a folded-in auto hotel is recorded there under the
    known hotel's id (first one wins), for known hotels that have no photo of their own."""
    has_photo = {h["id"] for h in manual_hotels if h.get("image")}
    known = {(h["season"], norm_name(h["name"])): h["id"] for h in manual_hotels}
    remap, add = {}, {}
    for h in auto_hotels:
        n = norm_name(h["name"])
        hit = known.get((h["season"], n)) or next(
            (hid for (season, kn), hid in known.items() if season == h["season"] and _contains(n, kn)), None)
        if hit:
            remap[h["id"]] = hit
            if images is not None and h.get("image") and hit not in has_photo:
                images.setdefault(hit, h["image"])
        else:
            add[h["id"]] = h
    for o in auto_offers:
        o["hotel"] = remap.get(o["hotel"], o["hotel"])
    return list(add.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--db", default="data/trips.db")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = db.connect(args.db)
    today = date.today()
    curated = manual.load_hotels()
    sightings = manual.load() if cfg["sources"].get("manual") else []
    auto_sightings: list[dict] = []
    hl = health.RunHealth()

    def session() -> PoliteSession:
        sc = cfg["sources"]
        return PoliteSession(sc["delay_seconds"], sc["jitter_seconds"], sc["timeout_seconds"],
                             host_delays=sc.get("host_delays"), cache_path="data/http-cache.sqlite")

    if not args.offline:
        curated_ids = {h["id"] for h in curated}
        # auto hotels already in the DB are known too, so a re-found duplicate folds into the id
        # its price history is under (curated first in line, so curated still wins)
        known = list(curated) + [h for hid, h in db.hotels(con).items() if hid not in curated_ids]
        added_all: list[dict] = []
        photos: dict[str, str] = {}        # known hotel id -> photo of an agency card folded into it
        for src in AUTO_SOURCES:
            s = session()
            auto_hotels, auto_offers = [], []
            with hl.track(getattr(src, "SOURCE", src.__name__), s) as st:   # a crashing source can't stop the run
                auto_hotels, auto_offers = src.fetch(cfg, today, session=s)
                st.offers_parsed = len(auto_offers)
            for h in auto_hotels:
                if validate.bad_image(h):
                    h["image"] = None
            added = dedupe.merge_auto_v2(known, auto_hotels, auto_offers, photos)  # + earlier sources, + DB
            added_all += added
            ids = {k["id"] for k in known}
            known += [h for h in added if h["id"] not in ids]
            auto_sightings += auto_offers
        if cfg["sources"].get("enrich", {}).get("enabled"):
            # detail pages fill unknown family facts and a single stated board (cached, weekly, budgeted)
            es = session()
            with hl.track("Detail pages", es) as st:
                enrich.enrich(auto_sightings, known, cfg, today, session=es)
                st.offers_parsed = len(auto_sightings)
        # every non-curated hotel: new ones, plus DB ones enrich may have filled in this run
        for h in known:
            if h["id"] not in curated_ids:
                db.upsert_hotel(con, h)
        for hid, url in photos.items():
            db.save_image(con, hid, url, today.isoformat())
    for h in curated:                      # curated facts always win
        db.upsert_hotel(con, h)
    hv = db.hotels(con)                    # every hotel is upserted by now (auto + curated)
    sightings, rejects = validate.split(sightings, today, cfg, hv)
    auto_sightings, auto_rejects = validate.split(auto_sightings, today, cfg, hv)
    validate.log_rejects(rejects + auto_rejects)
    hl.add_rejects(validate.by_source(rejects + auto_rejects))
    new = sum(db.add_sighting(con, o) for o in sightings) \
        + sum(db.add_sighting(con, o, live=True) for o in auto_sightings)
    new_camps = []
    if not args.offline:
        names = {hid: h["name"] for hid, h in db.hotels(con).items()}
        s, camps = session(), []
        with hl.track(hotel_direct.SOURCE, s) as st:
            camps = hotel_direct.fetch(cfg, today, session=s)
            st.offers_parsed = len(camps)
        for c in camps:
            if db.add_campaign(con, c):
                new_camps.append({"type": "campaign", "icon": "🏨", "url": c["url"],
                                  "text": f"New on {names.get(c['hotel'], c['hotel'])}'s own website: {c['title']}"})
    items, alerts = build(con, cfg, today, offline=args.offline)
    area = conditions.update(items, cfg, today, offline=args.offline)   # sea/snow + family places per area
    conditions.attach(items, area)
    alerts = new_camps + alerts
    con.commit()
    con.close()
    export(items, alerts, cfg)
    result = "off"
    if cfg["email"].get("enabled"):
        result = digest.send(digest.render(alerts), digest.load_settings())
    shown = sum(not i["excluded"] for i in items)
    log.info("%d offers (%d new sightings), %d fit the family, %d alerts, digest: %s",
             len(items), new, shown, len(alerts), result)
    if args.offline:
        return 0
    report = hl.write("docs/health.json")   # + data/health-history.json (last runs, for the 7-run average)
    # 3 = finished, but a source crashed / was blocked / suddenly returned 0. run_local.ps1 still publishes.
    return 3 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
