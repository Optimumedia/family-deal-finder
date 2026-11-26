# Brief for platform-improvement agents (round 2)

**Project:** `C:\Users\HP Omni Book 14\family-deal-finder` (Python 3.14). **Never run git commands.**

**The family:** two parents from Skopje, North Macedonia, with twins born October 2023. The birthdate is in the git-ignored `config.local.toml`: never copy it anywhere.

**Hard rules for a deal:**
- Reachable: a direct flight from Skopje, or at most a 5h drive (up to 45 min over counts as borderline).
- Summer: a sandy beach and breakfast + dinner.
- Winter: a 1-bedroom apartment with 2 cots and family activities nearby.
- Discounts must be real.

**Read first:**
- `README.md`, `PRODUCT.md` and `DESIGN.md` (for any UI work)
- `config.toml`
- `trips/run.py`: the run order is sources → merge → enrich → validate → db → build/score → export
- `trips/score.py`, `trips/db.py`, `trips/enrich.py`, `trips/validate.py`, `trips/sources/*.py`
- `docs/data.json`, the real current output: 488 offers. Study its shape.

## Rules
- **Edit only the files your task names as yours.** Everything else is read-only.
- Several agents work at the same time. `trips/run.py`, `trips/db.py` and `config.toml` belong to the integrator: put the changes you need there as an exact diff in `proposals/<yourname>.md`.
- **Respect the web:** use `trips.http.PoliteSession` or the module's own polite pattern. Honest User-Agent, robots.txt obeyed, ≥5 s between requests to a host. Never get around a block. Booking.com, Airbnb, Vrbo, Expedia and Fibula's private API are all excluded.
- **Few live requests:** work from saved fixtures and live-test only what you must. Do NOT run the full `python -m trips.run` live: it takes about 20 minutes and hits every site. `python -m trips.run --offline` is fine; it uses the local DB.
- **Tests:** add tests for what you build. The full suite must pass: `PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -t .`
- Write `proposals/<yourname>.md`:
  - what you changed
  - the exact integration diffs for files you don't own
  - any config block
  - the effect on the current data (counts before and after, using the offline run where possible)
  - known limits
- **Final report under 250 words:** the files changed, the measured effect, and what needs integrating.
