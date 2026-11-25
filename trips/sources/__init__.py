"""Offer sources. Each source yields offer dicts shaped like an entry in data/offers.toml.

Rules for every automatic source (same as the property finder):
- obey robots.txt (trips.http.PoliteSession does it), never touch /api/ or /search? paths a site disallows;
- slow and polite; stop on a bot wall (http.Blocked), never get around it;
- store facts only (price, dates, board, room) and link back to the source page.
"""
