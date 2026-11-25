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


def render(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    lines = ["Family Deal Finder — what's new", ""]
    for a in alerts:
        lines.append(f"{a['icon']} {a['text']}")
        if a.get("url"):
            lines.append(f"   {a['url']}")
    lines += ["", "Dashboard: open docs/index.html (or the GitHub Pages link once published)."]
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
