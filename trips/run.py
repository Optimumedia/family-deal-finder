"""One run: load hotels + offers → price history → drive time → score → alerts → docs/data.json → digest.

    python -m trips.run            # normal run
    python -m trips.run --offline  # skip the drive-time lookup (tests / no internet)
"""
from __future__ import annotations

import argparse
import json
import logging
import tomllib
from datetime import date, datetime
from pathlib import Path

from . import db, digest, geo, score
from .sources import manual

log = logging.getLogger("trips")


def load_config(path: str | Path = "config.toml") -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def build(con, cfg: dict, today: date, offline: bool = False) -> tuple[list[dict], list[dict]]:
    hotels = db.hotels(con)
    home = (cfg["family"]["home_lat"], cfg["family"]["home_lng"])
    drives = {hid: db.cached_drive(con, hid, h["lat"], h["lng"]) for hid, h in hotels.items()} if offline \
        else geo.drive_minutes(con, hotels, home)
    offers = db.offers(con)
    items, alerts = [], []
    for o in offers:
        h = hotels.get(o["hotel_id"])
        if not h:
            log.warning("offer for unknown hotel %s — add it to data/hotels.toml", o["hotel_id"])
            continue
        peers = [p for p in offers if hotels.get(p["hotel_id"], {}).get("season") == h["season"]]
        r = score.rate(h, o, peers, cfg, drives.get(h["id"]), today)
        now = o["history"][-1]
        item = {
            "key": o["key"], "hotel_id": h["id"], "name": h["name"], "stars": h.get("stars"), "area": h.get("area"),
            "season": h["season"], "lat": h.get("lat"), "lng": h.get("lng"), "notes": h.get("notes"),
            "source": o["source"], "url": o["url"], "check_in": o["check_in"], "nights": o["nights"],
            "board": o["board"], "room": o["room"], "occupancy": o["occupancy"],
            "price_eur": now["price_eur"], "was_eur": now.get("was_eur"), "discount_label": now.get("discount_label"),
            "valid_until": now.get("valid_until"), "first_seen": o["first_seen"], "last_seen": o["last_seen"],
            "history": [{"seen": s["seen"], "price_eur": s["price_eur"]} for s in o["history"]],
            **{k: r[k] for k in ("overall", "tier", "capped", "excluded", "family", "deal")},
            "email": score.email_draft(h, o, r["family"]["questions"], cfg) if r["family"]["questions"] else "",
        }
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
    if it["tier"]["key"] in ("great", "exceptional", "once") or it["overall"] >= 60:
        if db.mark_alert(con, f"new|{it['key']}", when):
            out.append({"icon": it["tier"]["icon"], "url": it["url"],
                        "text": f"New: {it['name']} — {price}, score {it['overall']:.0f}"})
    h = it["history"]
    if len(h) >= 2:
        prev = min(x["price_eur"] for x in h[:-1])
        drop = (prev - h[-1]["price_eur"]) / prev * 100
        if drop >= cfg["deal"]["drop_alert_pct"] and db.mark_alert(con, f"drop|{it['key']}|{h[-1]['seen']}", when):
            out.append({"icon": "📉", "url": it["url"], "text": f"Price drop −{drop:.0f}%: {it['name']} — {price}"})
    dl = it["deal"]["days_left"]
    if dl is not None and 0 <= dl <= 3 and db.mark_alert(con, f"deadline|{it['key']}|{it['valid_until']}", when):
        out.append({"icon": "⏰", "url": it["url"],
                    "text": f"Offer ends in {dl} day{'s' if dl != 1 else ''} ({it['valid_until']}): {it['name']} — {price}"})
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--db", default="data/trips.db")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    con = db.connect(args.db)
    for h in manual.load_hotels():
        db.upsert_hotel(con, h)
    new = sum(db.add_sighting(con, o) for o in manual.load()) if cfg["sources"].get("manual") else 0
    today = date.today()
    items, alerts = build(con, cfg, today, offline=args.offline)
    con.commit()
    export(items, alerts, cfg)
    result = "off"
    if cfg["email"].get("enabled"):
        result = digest.send(digest.render(alerts), digest.load_settings())
    shown = sum(not i["excluded"] for i in items)
    log.info("%d offers (%d new sightings), %d fit the family, %d alerts, digest: %s",
             len(items), new, shown, len(alerts), result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
