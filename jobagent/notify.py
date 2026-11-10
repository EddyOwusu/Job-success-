"""Announcements: terminal, push (ntfy.sh / Telegram) and email."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from .http import session

log = logging.getLogger(__name__)


def push(title: str, message: str, url: str = "") -> list[str]:
    """Send a short push notification on every configured channel. Returns channels used."""
    used = []
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        try:
            headers = {"Title": title.encode("utf-8"), "Tags": "briefcase"}
            if url:
                headers["Click"] = url
            session().post(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"), headers=headers, timeout=15)
            used.append("ntfy")
        except Exception as e:
            log.warning("ntfy failed: %s", e)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            session().post(f"https://api.telegram.org/bot{token}/sendMessage",
                           json={"chat_id": chat, "text": f"{title}\n\n{message}"[:4000], "disable_web_page_preview": True},
                           timeout=15)
            used.append("telegram")
        except Exception as e:
            log.warning("telegram failed: %s", e)
    return used


def email(subject: str, markdown_body: str, html_body: str = "", attachments: list[Path] | None = None) -> bool:
    host, user, pwd, to = (os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_TO"))
    if not (host and user and pwd and to):
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(markdown_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    for p in attachments or []:
        msg.add_attachment(p.read_bytes(), maintype="application", subtype="octet-stream", filename=p.name)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            s.login(user, pwd)
            s.send_message(msg)
        return True
    except Exception as e:
        log.warning("email failed: %s", e)
        return False
