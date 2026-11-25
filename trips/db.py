"""SQLite store: hotels, offers, price snapshots (= price history), drive-time cache, sent alerts.

The database lives on this PC (data/trips.db, git-ignored). Only docs/data.json is published.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotel (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL                -- the hotel entry from data/hotels.toml, as JSON
);
CREATE TABLE IF NOT EXISTS offer (
    key TEXT PRIMARY KEY,             -- hotel|check_in|nights|board|room|occupancy|source
    hotel_id TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT,
    check_in TEXT NOT NULL,
    nights INTEGER NOT NULL,
    board TEXT NOT NULL,
    room TEXT,
    occupancy TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot (
    offer_key TEXT NOT NULL,
    seen TEXT NOT NULL,               -- YYYY-MM-DD
    price_eur REAL NOT NULL,
    was_eur REAL,
    discount_label TEXT,
    valid_until TEXT,
    PRIMARY KEY (offer_key, seen)
);
CREATE TABLE IF NOT EXISTS drive_cache (
    hotel_id TEXT PRIMARY KEY,
    lat REAL, lng REAL,
    minutes REAL                      -- router time, before the border buffer
);
CREATE TABLE IF NOT EXISTS alert_sent (
    key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);
"""


def connect(path: str | Path = "data/trips.db") -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def offer_key(o: dict) -> str:
    return "|".join(str(o.get(k, "")) for k in ("hotel", "check_in", "nights", "board", "room", "occupancy", "source"))


def upsert_hotel(con, h: dict) -> None:
    con.execute("INSERT INTO hotel(id, data) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (h["id"], json.dumps(h, ensure_ascii=False)))


def add_sighting(con, o: dict) -> bool:
    """Store one price sighting. Returns True if it was new (not seen before on that day)."""
    key = offer_key(o)
    seen = str(o["seen"])
    con.execute("""INSERT INTO offer(key, hotel_id, source, url, check_in, nights, board, room, occupancy, first_seen, last_seen)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                     url=excluded.url,
                     first_seen=min(offer.first_seen, excluded.first_seen),
                     last_seen=max(offer.last_seen, excluded.last_seen)""",
                (key, o["hotel"], o["source"], o.get("url"), str(o["check_in"]), int(o["nights"]), o["board"],
                 o.get("room"), o.get("occupancy", "2+2"), seen, seen))
    cur = con.execute("""INSERT OR IGNORE INTO snapshot(offer_key, seen, price_eur, was_eur, discount_label, valid_until)
                         VALUES(?,?,?,?,?,?)""",
                      (key, seen, float(o["price_eur"]), o.get("was_eur"), o.get("discount_label"),
                       str(o["valid_until"]) if o.get("valid_until") else None))
    return cur.rowcount > 0


def hotels(con) -> dict[str, dict]:
    return {r["id"]: json.loads(r["data"]) for r in con.execute("SELECT id, data FROM hotel")}


def offers(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM offer ORDER BY hotel_id, check_in"):
        o = dict(r)
        o["history"] = [dict(s) for s in con.execute(
            "SELECT seen, price_eur, was_eur, discount_label, valid_until FROM snapshot WHERE offer_key=? ORDER BY seen",
            (r["key"],))]
        out.append(o)
    return out


def cached_drive(con, hotel_id: str, lat: float, lng: float) -> float | None:
    r = con.execute("SELECT lat, lng, minutes FROM drive_cache WHERE hotel_id=?", (hotel_id,)).fetchone()
    if r and abs(r["lat"] - lat) < 1e-6 and abs(r["lng"] - lng) < 1e-6:
        return r["minutes"]
    return None


def save_drive(con, hotel_id: str, lat: float, lng: float, minutes: float) -> None:
    con.execute("INSERT OR REPLACE INTO drive_cache(hotel_id, lat, lng, minutes) VALUES(?,?,?,?)",
                (hotel_id, lat, lng, minutes))


def mark_alert(con, key: str, when: str) -> bool:
    """True the first time an alert key is seen (so each alert goes out once)."""
    return con.execute("INSERT OR IGNORE INTO alert_sent(key, sent_at) VALUES(?, ?)", (key, when)).rowcount > 0
