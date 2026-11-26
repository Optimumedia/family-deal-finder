"""Daily email digest (no Telegram). Settings from the git-ignored .email file.

Without .email the digest is only written to data/digest.txt — nothing is sent.
Each alert goes out once (alert_sent table).
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)


def load_settings(path: str | Path = ".email") -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


# Alert groups, in the order they appear. Alerts may carry an explicit "type"; older ones are
# recognised by their icon (run._alerts), anything else counts as a new deal.
GROUPS = [
    ("deadline", "Ending soon"),
    ("drop", "Price drops"),
    ("new", "New good deals"),
    ("campaign", "On hotels' own websites"),
]
ICON_TYPES = {"⏰": "deadline", "📉": "drop", "🏨": "campaign"}
SHOW_SIGNALS = {"book now": "BOOK NOW", "can wait": "can wait"}


def alert_type(a: dict) -> str:
    t = a.get("type") or ICON_TYPES.get(a.get("icon", ""), "new")
    return t if t in dict(GROUPS) else "new"


def render(alerts: list[dict], max_per_group: int = 6) -> str:
    """Short plain-text digest: alerts grouped by type, each with its book-now / can-wait signal
    when the alert carries one ("signal", "signal_reason")."""
    if not alerts:
        return ""
    groups: dict[str, list[dict]] = {}
    for a in alerts:
        groups.setdefault(alert_type(a), []).append(a)
    book = sum(a.get("signal") == "book now" for a in alerts)
    head = f"Family Deal Finder — {len(alerts)} alert{'s' if len(alerts) != 1 else ''}"
    lines = [head + (f", {book} to book now" if book else ""), ""]
    for key, title in GROUPS:
        items = groups.get(key, [])
        if not items:
            continue
        lines.append(f"{title} ({len(items)})")
        # book-now alerts first inside each group
        for a in sorted(items, key=lambda a: a.get("signal") != "book now")[:max_per_group]:
            sig = SHOW_SIGNALS.get(a.get("signal") or "")
            tail = ""
            if sig:
                tail = f" → {sig}" + (f": {a['signal_reason']}" if a.get("signal_reason") else "")
            lines.append(f"{a.get('icon', '•')} {a['text']}{tail}")
            if a.get("url"):
                lines.append(f"   {a['url']}")
        if len(items) > max_per_group:
            lines.append(f"   … and {len(items) - max_per_group} more on the dashboard")
        lines.append("")
    lines.append("Dashboard: open docs/index.html (or the GitHub Pages link once published).")
    return "\n".join(lines)


def send(body: str, settings: dict, out_file: str | Path = "data/digest.txt") -> str:
    Path(out_file).parent.mkdir(parents=True, exist_ok=True)
    Path(out_file).write_text(body, encoding="utf-8")
    need = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")
    if not body or not all(settings.get(k) for k in need):
        return "written"
    msg = EmailMessage()
    msg["Subject"] = "Family Deal Finder — new deals"
    msg["From"] = settings["SMTP_USER"]
    msg["To"] = settings["MAIL_TO"]
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings["SMTP_HOST"], int(settings.get("SMTP_PORT", 587)), timeout=30) as s:
            s.starttls()
            s.login(settings["SMTP_USER"], settings["SMTP_PASSWORD"])
            s.send_message(msg)
        return "sent"
    except (OSError, smtplib.SMTPException) as e:
        log.warning("digest email failed: %s", e)
        return "failed"
