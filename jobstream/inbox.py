"""Read your inbox for replies to applications and update their status.

Uses IMAP, so it works with Gmail (with an App Password) and most other mail
providers. Everything runs on your computer. Only when the wording of a matched
email is unclear, and only if Claude is configured, is that one email's text
sent to Claude to classify it.

What it does with each reply:
  rejection          -> marks the application rejected
  interview / test   -> marks it interview and builds the interview prep pack
  acknowledgement    -> notes that the application arrived
  possible offer     -> tells you, never changes anything by itself
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Optional

from pydantic import BaseModel, Field

from .db import DB, now_iso
from .sponsors import _tokens

ATS_SENDERS = ("greenhouse", "lever.co", "ashbyhq", "smartrecruiters", "myworkday", "workday", "jobs.nhs.uk",
               "nhs.net", "trac.jobs", "jobtrain", "tal.net", "oleeo", "workable", "teamtailor", "pinpoint",
               "jobs.ac.uk", "successfactors", "icims", "taleo")

RULES = [
    ("offer", r"pleased to (make you an |offer you)|offer of employment|job offer|formal offer|conditional offer"),
    ("interview", r"invite you to (an |a )?(interview|call|chat|assessment)|(schedule|arrange|book) (a |an |your )?"
                  r"(call|interview|chat|time)|next stage|your availability|calendly\.com|phone screen|"
                  r"technical (test|assessment|exercise)|take[- ]home|assessment cent(re|er)|shortlisted for interview|"
                  r"move (you )?forward to|progress (you |your application )?to the next"),
    ("rejected", r"unfortunately|not (to )?(be )?(moving|progressing|proceeding) (forward|further)|"
                 r"decided (not to|to move forward with other)|other candidates|not been successful|unsuccessful|"
                 r"will not be taking your application|position has (now )?been filled|not shortlisted|"
                 r"no longer (being )?considered|regret to inform"),
    ("ack", r"received your application|thank(s| you) for (applying|your application|your interest)|"
            r"application (has been )?(received|submitted)"),
]


@dataclass
class Mail:
    msg_id: str
    sender: str
    sender_addr: str
    subject: str
    body: str
    date: str


@dataclass
class Update:
    job_uid: str
    company: str
    title: str
    verdict: str          # offer | interview | rejected | ack | unclear
    subject: str
    applied: bool         # True when the status was changed


class MailVerdict(BaseModel):
    verdict: str = Field(description="offer | interview | rejected | ack | other")
    reason: str


def configured() -> bool:
    return bool((os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER"))
                and (os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")))


def _decode(v: str | None) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _body(msg: email.message.Message) -> str:
    parts = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        if ctype in ("text/plain", "text/html") and not part.get_filename():
            try:
                raw = part.get_payload(decode=True) or b""
                text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                continue
            if ctype == "text/html":
                from .text import html_to_text
                text = html_to_text(text)
            parts.append(text)
            if ctype == "text/plain":
                break
    return re.sub(r"\s+", " ", " ".join(parts))[:6000]


def fetch(days: int = 30) -> list[Mail]:
    host = os.environ.get("IMAP_HOST", "imap.gmail.com")
    user = os.environ.get("IMAP_USER") or os.environ.get("SMTP_USER")
    pwd = os.environ.get("IMAP_PASSWORD") or os.environ.get("SMTP_PASSWORD")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    out = []
    with imaplib.IMAP4_SSL(host) as im:
        im.login(user, pwd)
        im.select("INBOX", readonly=True)          # never marks anything as read
        _, data = im.search(None, f'(SINCE "{since}")')
        for num in (data[0].split() if data and data[0] else [])[-500:]:
            _, msg_data = im.fetch(num, "(RFC822)")
            if not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            name, addr = parseaddr(_decode(msg.get("From")))
            out.append(Mail(msg_id=msg.get("Message-ID") or f"{num.decode()}-{msg.get('Date')}",
                            sender=name, sender_addr=addr.lower(), subject=_decode(msg.get("Subject")),
                            body=_body(msg), date=msg.get("Date") or ""))
    return out


def classify(mail: Mail) -> str:
    text = f"{mail.subject} {mail.body}".lower()
    for verdict, pat in RULES:
        if re.search(pat, text, re.I):
            return verdict
    return "unclear"


def _company_keys(company: str) -> list[str]:
    toks = [t for t in _tokens(company) if len(t) >= 3]
    keys = ["".join(toks), " ".join(toks)]
    distinctive = [t for t in toks if t not in {"the", "and", "university", "nhs", "trust", "foundation", "hospital",
                                                "hospitals", "group", "bank", "services", "college", "london"}]
    if distinctive and len(distinctive[0]) >= 4:
        keys.append(distinctive[0])
    return [k for k in dict.fromkeys(keys) if k]


def match(mail: Mail, apps: list) -> Optional[object]:
    """The application this email is about, or None. Needs the company named in the sender or subject,
    or an ATS sender plus the company in the body."""
    sender = f"{mail.sender} {mail.sender_addr}".lower()
    subject = mail.subject.lower()
    body = mail.body.lower()
    best, best_score = None, 0
    for a in apps:
        keys = _company_keys(a["company"])
        score = 0
        if any(k.replace(" ", "") in re.sub(r"[^a-z0-9]", "", sender) for k in keys):
            score += 3
        if any(k in subject for k in keys):
            score += 2
        if any(x in sender for x in ATS_SENDERS) and any(k in subject or k in body for k in keys):
            score += 2
        title_words = [w for w in re.findall(r"[a-z]{4,}", a["title"].lower())][:4]
        if title_words and sum(w in subject or w in body for w in title_words) >= min(2, len(title_words)):
            score += 1
        if score > best_score:
            best, best_score = a, score
    return best if best_score >= 3 else None


def sync(db: DB, ctx, llm=None, days: int = 30, on_interview=None) -> list[Update]:
    """Check the inbox and update application statuses. Returns what changed."""
    apps = db.conn.execute(
        "SELECT j.uid, j.company, j.title, j.status FROM jobs j JOIN applications a ON a.job_uid=j.uid "
        "WHERE j.status IN ('applied','interview')"
    ).fetchall()
    if not apps:
        return []
    updates: list[Update] = []
    for mail in fetch(days):
        if db.conn.execute("SELECT 1 FROM inbox_seen WHERE msg_id=?", (mail.msg_id,)).fetchone():
            continue
        app = match(mail, apps)
        verdict = classify(mail) if app else "unrelated"
        if app and verdict == "unclear" and llm is not None:
            try:
                v = llm.structured(
                    system="You classify emails a job applicant received about an application. Reply with the verdict only.",
                    prompt=f"Company: {app['company']}\nRole: {app['title']}\nFrom: {mail.sender} <{mail.sender_addr}>\n"
                           f"Subject: {mail.subject}\n\n{mail.body[:3000]}\n\nIs this an offer, an interview or "
                           f"assessment invitation, a rejection, an acknowledgement (ack), or other?",
                    schema=MailVerdict, effort="low", max_tokens=2000, cache_system=False)
                verdict = v.verdict if v.verdict in ("offer", "interview", "rejected", "ack") else "unclear"
            except Exception:
                pass
        db.conn.execute("INSERT OR IGNORE INTO inbox_seen (msg_id, at, job_uid, verdict) VALUES (?,?,?,?)",
                        (mail.msg_id, now_iso(), app["uid"] if app else None, verdict))
        if not app or verdict == "unrelated":
            continue
        changed = False
        if verdict == "rejected" and app["status"] == "applied":
            db.set_status(app["uid"], "rejected", source="inbox")
            changed = True
        elif verdict == "interview" and app["status"] == "applied":
            db.set_status(app["uid"], "interview", source="inbox")
            changed = True
            if on_interview:
                on_interview(app["uid"])
        elif verdict == "ack":
            db.log("inbox", f"Application acknowledged: {app['company']} / {app['title']}")
        updates.append(Update(app["uid"], app["company"], app["title"], verdict, mail.subject, changed))
    db.commit()
    return updates
