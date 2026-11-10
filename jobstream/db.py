"""SQLite storage: jobs, scores, applications, contacts, follow-ups, discovered boards."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uid TEXT PRIMARY KEY,
    source TEXT, source_id TEXT, company TEXT, title TEXT, location TEXT,
    url TEXT, apply_url TEXT, description TEXT,
    salary_min REAL, salary_max REAL, salary_currency TEXT, remote TEXT,
    posted_at TEXT, ats TEXT, ats_token TEXT, extra TEXT,
    fingerprint TEXT,
    first_seen TEXT, last_seen TEXT,
    sponsor_match TEXT,          -- matched name on the sponsor register, or NULL
    score REAL, score_json TEXT,
    assessment_json TEXT, fit_score REAL,
    status TEXT DEFAULT 'new'    -- new | shortlisted | skipped | packed | applied | interview | offer | rejected | withdrawn
);
CREATE INDEX IF NOT EXISTS jobs_fp ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT, company TEXT, title TEXT,
    applied_at TEXT, method TEXT, pack_dir TEXT, notes TEXT,
    status TEXT DEFAULT 'applied'
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT, job_uid TEXT, name TEXT, role TEXT, email TEXT,
    email_confidence TEXT, linkedin TEXT, source TEXT, notes TEXT,
    contacted_at TEXT,
    UNIQUE(company, name, email)
);

CREATE TABLE IF NOT EXISTS followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT, due TEXT, kind TEXT, message TEXT, done INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS boards (
    ats TEXT, token TEXT, company TEXT, sponsor_name TEXT,
    status TEXT,                -- live | none | error
    jobs_count INTEGER, checked_at TEXT,
    PRIMARY KEY (ats, token)
);

CREATE TABLE IF NOT EXISTS probes (
    sponsor_name TEXT PRIMARY KEY, checked_at TEXT, found TEXT
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_uid TEXT, status TEXT, at TEXT, source TEXT   -- source: you | inbox | agent
);

-- Every Skilled Worker sponsor we have seen, to spot new licences and removals day to day
CREATE TABLE IF NOT EXISTS sponsor_seen (
    name TEXT PRIMARY KEY, town TEXT, rating TEXT,
    first_seen TEXT, last_seen TEXT, removed_at TEXT,
    baseline INTEGER DEFAULT 0,      -- 1 = was already on the register when tracking started
    prev_rating TEXT, rating_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS inbox_seen (
    msg_id TEXT PRIMARY KEY, at TEXT, job_uid TEXT, verdict TEXT
);

-- What each source returned on each run, to notice when one breaks
CREATE TABLE IF NOT EXISTS source_runs (
    run_at TEXT, kind TEXT, key TEXT, seen INTEGER, returned INTEGER, empty_desc INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS source_runs_kind ON source_runs(kind, key, run_at);

CREATE TABLE IF NOT EXISTS projects (
    skill TEXT PRIMARY KEY, status TEXT DEFAULT 'planned',   -- planned | in_progress | done | dropped
    created_at TEXT, done_at TEXT, plan_path TEXT, demand REAL
);

-- Speculative approaches to sponsors with no suitable vacancy right now
CREATE TABLE IF NOT EXISTS speculative (
    company TEXT PRIMARY KEY, sponsor_name TEXT, score REAL, reasons TEXT,
    created_at TEXT, pack_dir TEXT,
    status TEXT DEFAULT 'drafted',     -- drafted | sent | replied | closed
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS learned (
    key TEXT PRIMARY KEY, value TEXT, at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT, kind TEXT, message TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(company: str, title: str) -> str:
    import re

    norm = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    return f"{norm(company)}|{norm(title)}"


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a database was first created."""
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(applications)")}
        if "features" not in cols:
            self.conn.execute("ALTER TABLE applications ADD COLUMN features TEXT")
        if "outcome_at" not in cols:
            self.conn.execute("ALTER TABLE applications ADD COLUMN outcome_at TEXT")
        if "alerted_at" not in {r[1] for r in self.conn.execute("PRAGMA table_info(jobs)")}:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN alerted_at TEXT")

    # ------------------------------------------------------------------ learned values
    def get_learned(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM learned WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_learned(self, key: str, value) -> None:
        self.conn.execute("INSERT OR REPLACE INTO learned (key, value, at) VALUES (?,?,?)",
                          (key, json.dumps(value), now_iso()))
        self.conn.commit()

    # ------------------------------------------------------------------ jobs
    def upsert_job(self, job: Job, sponsor_match: Optional[str]) -> bool:
        """Insert or refresh a job. Returns True when the job is new (also across sources)."""
        fp = fingerprint(job.company, job.title)
        ts = now_iso()
        cur = self.conn.execute("SELECT uid FROM jobs WHERE uid=?", (job.uid,))
        if cur.fetchone():
            self.conn.execute(
                "UPDATE jobs SET last_seen=?, description=COALESCE(NULLIF(?, ''), description), sponsor_match=? WHERE uid=?",
                (ts, job.description, sponsor_match, job.uid),
            )
            return False
        dup = self.conn.execute(
            "SELECT uid FROM jobs WHERE fingerprint=? AND location=?", (fp, job.location)
        ).fetchone()
        if dup:  # the same advert reposted on another board
            self.conn.execute("UPDATE jobs SET last_seen=? WHERE uid=?", (ts, dup["uid"]))
            return False
        self.conn.execute(
            """INSERT INTO jobs (uid, source, source_id, company, title, location, url, apply_url,
               description, salary_min, salary_max, salary_currency, remote, posted_at, ats, ats_token,
               extra, fingerprint, first_seen, last_seen, sponsor_match)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.uid, job.source, job.source_id, job.company, job.title, job.location, job.url,
                job.apply_url, job.description, job.salary_min, job.salary_max, job.salary_currency,
                job.remote, job.posted_at.isoformat() if job.posted_at else None, job.ats,
                job.ats_token, json.dumps(job.extra), fp, ts, ts, sponsor_match,
            ),
        )
        return True

    def commit(self) -> None:
        self.conn.commit()

    @staticmethod
    def row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            source=row["source"], source_id=row["source_id"], company=row["company"],
            title=row["title"], location=row["location"] or "", url=row["url"] or "",
            apply_url=row["apply_url"] or "", description=row["description"] or "",
            salary_min=row["salary_min"], salary_max=row["salary_max"],
            salary_currency=row["salary_currency"] or "GBP", remote=row["remote"],
            posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
            ats=row["ats"], ats_token=row["ats_token"], extra=json.loads(row["extra"] or "{}"),
        )

    def get_job(self, uid_or_prefix: str) -> Optional[sqlite3.Row]:
        row = self.conn.execute("SELECT * FROM jobs WHERE uid=?", (uid_or_prefix,)).fetchone()
        if row:
            return row
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE uid LIKE ? OR source_id=?", (f"%{uid_or_prefix}%", uid_or_prefix)
        ).fetchall()
        return rows[0] if len(rows) == 1 else None

    def jobs(self, where: str = "1=1", params: Iterable[Any] = (), order: str = "score DESC", limit: int = 1000):
        return self.conn.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY {order} LIMIT ?", (*params, limit)
        ).fetchall()

    def set_score(self, uid: str, score: float, breakdown_json: str) -> None:
        self.conn.execute("UPDATE jobs SET score=?, score_json=? WHERE uid=?", (score, breakdown_json, uid))

    def set_assessment(self, uid: str, fit: float, assessment_json: str) -> None:
        self.conn.execute(
            "UPDATE jobs SET fit_score=?, assessment_json=? WHERE uid=?", (fit, assessment_json, uid)
        )

    def set_status(self, uid: str, status: str, source: str = "agent") -> None:
        self.conn.execute("UPDATE jobs SET status=? WHERE uid=?", (status, uid))
        if status in ("applied", "interview", "offer", "rejected", "withdrawn"):
            self.conn.execute("INSERT INTO status_history (job_uid, status, at, source) VALUES (?,?,?,?)",
                              (uid, status, now_iso(), source))
            if status != "applied":
                self.conn.execute("UPDATE applications SET status=?, outcome_at=COALESCE(outcome_at, ?) WHERE job_uid=?",
                                  (status, now_iso(), uid))
        self.conn.commit()

    # ------------------------------------------------------------------ applications
    def record_application(self, job: sqlite3.Row, method: str, pack_dir: str, notes: str = "",
                           features: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO applications (job_uid, company, title, applied_at, method, pack_dir, notes, features) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (job["uid"], job["company"], job["title"], now_iso(), method, pack_dir, notes,
             json.dumps(features or {})),
        )
        self.set_status(job["uid"], "applied", source="you")

    def applications_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE applied_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]

    def applications_to_company(self, company: str, days: int = 30) -> int:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.conn.execute(
            "SELECT COUNT(*) FROM applications WHERE lower(company)=lower(?) AND applied_at>=?",
            (company, since),
        ).fetchone()[0]

    # ------------------------------------------------------------------ contacts / follow-ups
    def add_contact(self, **kw) -> None:
        cols = ",".join(kw)
        self.conn.execute(
            f"INSERT OR IGNORE INTO contacts ({cols}) VALUES ({','.join('?' * len(kw))})", tuple(kw.values())
        )

    def contacts_for(self, company: str):
        return self.conn.execute("SELECT * FROM contacts WHERE lower(company)=lower(?)", (company,)).fetchall()

    def add_followup(self, job_uid: str, due: datetime, kind: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO followups (job_uid, due, kind, message) VALUES (?,?,?,?)",
            (job_uid, due.date().isoformat(), kind, message),
        )

    def due_followups(self):
        today = datetime.now(timezone.utc).date().isoformat()
        return self.conn.execute(
            """SELECT f.*, j.company, j.title, j.status FROM followups f JOIN jobs j ON j.uid=f.job_uid
               WHERE f.done=0 AND f.due<=? AND j.status IN ('applied') ORDER BY f.due""",
            (today,),
        ).fetchall()

    def complete_followup(self, fid: int) -> None:
        self.conn.execute("UPDATE followups SET done=1 WHERE id=?", (fid,))
        self.conn.commit()

    # ------------------------------------------------------------------ boards / discovery
    def upsert_board(self, ats: str, token: str, company: str, sponsor_name: str, status: str, count: int) -> None:
        self.conn.execute(
            """INSERT INTO boards (ats, token, company, sponsor_name, status, jobs_count, checked_at)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT(ats, token) DO UPDATE SET
               status=excluded.status, jobs_count=excluded.jobs_count, checked_at=excluded.checked_at,
               company=COALESCE(excluded.company, boards.company),
               sponsor_name=COALESCE(excluded.sponsor_name, boards.sponsor_name)""",
            (ats, token, company, sponsor_name, status, count, now_iso()),
        )

    def live_boards(self):
        return self.conn.execute("SELECT * FROM boards WHERE status='live'").fetchall()

    def probed(self, sponsor_name: str) -> bool:
        return bool(self.conn.execute("SELECT 1 FROM probes WHERE sponsor_name=?", (sponsor_name,)).fetchone())

    def mark_probed(self, sponsor_name: str, found: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO probes (sponsor_name, checked_at, found) VALUES (?,?,?)",
            (sponsor_name, now_iso(), found),
        )

    # ------------------------------------------------------------------ events
    def log(self, kind: str, message: str) -> None:
        self.conn.execute("INSERT INTO events (at, kind, message) VALUES (?,?,?)", (now_iso(), kind, message))
        self.conn.commit()
