# Deal engine: proposed changes outside score.py / digest.py

The engine changes are done in `trips/score.py`, `trips/digest.py`, `tests/test_engine.py` and the new
`tests/test_deal_engine.py`. The fields below already reach `docs/data.json`, because `run.build` copies
`deal` whole. Four other files need changes from the integrator.

## 1. `trips/db.py`: record the second daily run (important)

Today a snapshot is keyed `(offer_key, seen=YYYY-MM-DD)` with `INSERT OR IGNORE`. That means:
- the 17:30 check is dropped;
- "3 observations" really means "3 different days";
- a price change during the day is lost.

The fix adds a `checks` counter for unchanged repeat checks, and a timestamped row when the price changes
on the same day. `score.py` already reads both: `checks` counts as observations, and `seen` may be
`YYYY-MM-DDTHH:MM`. Only live sources count repeats. Manual sightings are re-read on every run, so letting
them count would inflate the evidence.

```diff
 CREATE TABLE IF NOT EXISTS snapshot (
     offer_key TEXT NOT NULL,
-    seen TEXT NOT NULL,               -- YYYY-MM-DD
+    seen TEXT NOT NULL,               -- YYYY-MM-DD, or YYYY-MM-DDTHH:MM for a same-day price change
     price_eur REAL NOT NULL,
     was_eur REAL,
     discount_label TEXT,
     valid_until TEXT,
+    checks INTEGER NOT NULL DEFAULT 1, -- unchanged repeat checks folded into this row
     PRIMARY KEY (offer_key, seen)
 );
```
```diff
 def connect(path: str | Path = "data/trips.db") -> sqlite3.Connection:
     ...
     con.executescript(SCHEMA)
+    if "checks" not in {r[1] for r in con.execute("PRAGMA table_info(snapshot)")}:
+        con.execute("ALTER TABLE snapshot ADD COLUMN checks INTEGER NOT NULL DEFAULT 1")
     return con
```
```diff
-def add_sighting(con, o: dict) -> bool:
-    """Store one price sighting. Returns True if it was new (not seen before on that day)."""
+def add_sighting(con, o: dict, live: bool = False, at: str | None = None) -> bool:
+    """Store one price sighting. Returns True when it adds a price point. A live repeat check with
+    the same price on the same day bumps `checks`; a changed price gets its own HH:MM row."""
     key = offer_key(o)
     seen = str(o["seen"])
     con.execute("""INSERT INTO offer(...) ... """, (...))          # unchanged
-    cur = con.execute("""INSERT OR IGNORE INTO snapshot(offer_key, seen, price_eur, was_eur, discount_label, valid_until)
-                         VALUES(?,?,?,?,?,?)""",
-                      (key, seen, float(o["price_eur"]), o.get("was_eur"), o.get("discount_label"),
-                       str(o["valid_until"]) if o.get("valid_until") else None))
-    return cur.rowcount > 0
+    vu = str(o["valid_until"]) if o.get("valid_until") else None
+    last = con.execute("SELECT seen, price_eur, was_eur, valid_until FROM snapshot WHERE offer_key=? "
+                       "AND substr(seen,1,10)=? ORDER BY seen DESC LIMIT 1", (key, seen[:10])).fetchone()
+    row = (float(o["price_eur"]), o.get("was_eur"), o.get("discount_label"), vu)
+    if last is not None:
+        if (last["price_eur"], last["was_eur"], last["valid_until"]) == (row[0], row[1], vu):
+            if live:
+                con.execute("UPDATE snapshot SET checks=checks+1 WHERE offer_key=? AND seen=?", (key, last["seen"]))
+            return False
+        if not live:
+            return False
+        seen = f"{seen[:10]}T{at or datetime.now().strftime('%H:%M')}"
+    con.execute("INSERT OR IGNORE INTO snapshot(offer_key, seen, price_eur, was_eur, discount_label, valid_until)"
+                " VALUES(?,?,?,?,?,?)", (key, seen, *row))
+    return True
```
Also add `from datetime import datetime` at the top, and `checks` to the `offers()` query:
```diff
-            "SELECT seen, price_eur, was_eur, discount_label, valid_until FROM snapshot WHERE offer_key=? ORDER BY seen",
+            "SELECT seen, price_eur, was_eur, discount_label, valid_until, checks FROM snapshot WHERE offer_key=? ORDER BY seen",
```
`test_history_dedupes_same_day` keeps passing, because the default `live=False` gives the same behaviour.

## 2. `trips/run.py`: typed alerts, a signal on every alert, and live sightings

```diff
     sightings = manual.load() if cfg["sources"].get("manual") else []
+    auto_sightings: list[dict] = []
     ...
-            sightings += auto_offers
+            auto_sightings += auto_offers
     ...
-    new = sum(db.add_sighting(con, o) for o in sightings)
+    new = sum(db.add_sighting(con, o) for o in sightings) \
+        + sum(db.add_sighting(con, o, live=True) for o in auto_sightings)
```

In `_alerts`, add `"type"` and the signal to each alert dict, plus one new alert:
```diff
 def _alerts(con, it: dict, cfg: dict, today: date) -> list[dict]:
     out = []
+    sig = {"signal": it["deal"]["signal"], "signal_reason": it["deal"]["signal_reason"]}
     ...
-            out.append({"icon": it["tier"]["icon"], "url": it["url"],
+            out.append({"type": "new", **sig, "icon": it["tier"]["icon"], "url": it["url"],
                         "text": f"New: {it['name']} — {price}, score {it['overall']:.0f}"})
     ...
-            out.append({"icon": "📉", "url": it["url"], "text": f"Price drop −{drop:.0f}%: {it['name']} — {price}"})
+            out.append({"type": "drop", **sig, "icon": "📉", "url": it["url"], "text": f"Price drop −{drop:.0f}%: {it['name']} — {price}"})
     ...
-        out.append({"icon": "⏰", "url": it["url"],
+        out.append({"type": "deadline", **sig, "icon": "⏰", "url": it["url"],
                     "text": f"Offer ends in {dl} day{'s' if dl != 1 else ''} ({it['valid_until']}): {it['name']} — {price}"})
+    d = it["deal"]
+    if d["signal"] == "book now" and d["confidence"] != "low" and it["overall"] >= 55 \
+            and db.mark_alert(con, f"book|{it['key']}|{h[-1]['seen'][:10]}", when):
+        out.append({"type": "new", **sig, "icon": "🛎️", "url": it["url"], "text": f"Book now: {it['name']} — {price}"})
     return out
```
Hotel-website campaign alerts in `main()` should get `"type": "campaign"`. `digest.py` already falls
back to the icons (⏰ 📉 🏨), so nothing breaks before this lands.

## 3. `config.toml`: make the new thresholds editable

`score.DEAL_DEFAULTS` holds the same values, so this is optional.
```diff
 [deal]
 history_days = 30
 drop_alert_pct = 7
 stated_weight = 0.5
+# "Real" = at least this % below the 30-day low, backed by enough checks.
+real_min_pct = 3
+min_observations = 3
+min_days = 2
+# A rise this big within this many days before a "was" price appears = pre-sale inflation → "fake?".
+inflation_pct = 15
+inflation_days = 14
+# Book-now signal: a deadline this close + price within near_low_pct of its low.
+book_now_days = 7
+near_low_pct = 3
+# Trend: fitted change over the last trend_days that counts as rising / falling.
+trend_days = 14
+trend_pct = 3
```

## 4. `docs/index.html`: show the new fields

New `deal` fields: `baseline_low`, `baseline_median`, `observations`, `observed_days`, `trend`,
`trend_pct`, `signal` ("book now" / "can wait" / "watch"), `signal_reason`, `confidence`
("low" / "medium" / "high"), `confidence_note`, `inflated`, `vs_low_pct`, `vs_median_pct`,
`parts` (points per component), and `notes` (plain-language reasons). `family.parts` and
`family.price_covers_kids` are new too.

There's one new verdict, `unconfirmed`: cheaper than our low, but the history is still thin.

`real_pct` is now set **only** for verdict `real`. This fixes the compare table (line ~633), which showed
"Verified −-13%" for a negative difference.

```diff
 function verdict(o){
   const d = o.deal;
   if (d.verdict === 'real') return `<div class="verdict real">${ic('check')} Verified −${Math.round(d.real_pct)}% vs our recorded price</div>`;
-  if (d.verdict === 'fake?') return `<div class="verdict fake">${ic('xmark')} "Discount", but not cheaper than before</div>`;
+  if (d.verdict === 'fake?') return `<div class="verdict fake">${ic('xmark')} ${esc(d.notes[0] || '"Discount", but not cheaper than before')}</div>`;
+  if (d.verdict === 'unconfirmed') return `<div class="verdict">−${Math.round(d.vs_low_pct)}% vs our low, not confirmed yet (${esc(d.confidence_note)})</div>`;
   return '';
 }
+function signal(o){
+  const d = o.deal; if (d.signal === 'watch') return '';
+  return `<div class="signal ${d.signal === 'book now' ? 'now' : 'wait'}">${d.signal === 'book now' ? 'Book now' : 'Can wait'} · ${esc(d.signal_reason)}${d.confidence === 'low' ? ' <span class="q">(little history)</span>' : ''}</div>`;
+}
```
In the compare table, add `['Book or wait', h => h.best.deal.signal]` and
`['30-day low', h => h.best.deal.baseline_low ? eur(h.best.deal.baseline_low) : '—']`.
