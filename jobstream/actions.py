"""What the dashboard's buttons do.

Quick actions (skip, mark applied, change status, open a pack folder) run at once. Slow ones
(apply, build a pack, interview prep) go on a queue that one background worker runs in order,
so two browser sessions never run at the same time; the page polls for progress.

The worker opens its own database connection and settings, so a click always uses the latest
profile and CV.
"""
from __future__ import annotations

import itertools
import json
import os
import platform
import queue
import subprocess
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import DB_PATH, OUTPUT_DIR, load_context
from .db import DB

SLOW = {"apply", "pack", "interview", "network"}
QUICK = {"skip", "applied", "status", "open_pack", "dismiss"}
STATUSES = {"interview", "offer", "rejected", "withdrawn", "applied"}


@dataclass
class Task:
    id: int
    action: str
    uid: str
    label: str
    value: str = ""
    state: str = "queued"           # queued | running | done | failed
    messages: list[str] = field(default_factory=list)
    result: str = ""
    started: str = ""

    def public(self) -> dict:
        return {"id": self.id, "action": self.action, "uid": self.uid, "label": self.label, "state": self.state,
                "messages": self.messages[-6:], "result": self.result}


def pack_dir_for(row) -> Optional[Path]:
    """Where a job's application pack is on disk."""
    extra = json.loads(row["extra"] or "{}")
    if extra.get("pack_dir") and Path(extra["pack_dir"]).exists():
        return Path(extra["pack_dir"])
    from .apply.pack import pack_dir
    d = pack_dir(OUTPUT_DIR, DB.row_to_job(row))
    if d.exists():
        return d
    from .text import slug
    hits = sorted((OUTPUT_DIR / "applications").glob(f"*_{slug(row['company'])}_{slug(row['title'])[:40]}"))
    return hits[-1] if hits else None


def open_folder(path: Path) -> None:
    if platform.system() == "Windows":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Runner:
    def __init__(self, db_path: Path = DB_PATH, context_loader=load_context, llm_factory=None):
        self.db_path = db_path
        self.load = context_loader
        self.llm_factory = llm_factory
        self.tasks: dict[int, Task] = {}
        self._ids = itertools.count(1)
        self._q: "queue.Queue[Task]" = queue.Queue()
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True, name="jobstream-actions")
        self._worker.start()

    # ------------------------------------------------------------------ API
    def submit(self, action: str, uid: str, value: str = "", local: bool = True) -> dict:
        db = DB(self.db_path)
        try:
            row = db.get_job(uid)
            if not row:
                return {"ok": False, "error": "No such job"}
            label = f"{row['title']} at {row['company']}"
            if action in QUICK:
                return self._quick(db, row, action, value, local)
            if action not in SLOW:
                return {"ok": False, "error": f"Unknown action {action}"}
            with self._lock:
                busy = next((t for t in self.tasks.values() if t.uid == row["uid"] and t.action == action
                             and t.state in ("queued", "running")), None)
                if busy:
                    return {"ok": True, "task": busy.public()}
                t = Task(next(self._ids), action, row["uid"], label, value=value)
                self.tasks[t.id] = t
            self._q.put(t)
            return {"ok": True, "task": t.public()}
        finally:
            db.conn.close()

    def list(self) -> list[dict]:
        with self._lock:
            return [t.public() for t in sorted(self.tasks.values(), key=lambda t: t.id)][-20:]

    # ------------------------------------------------------------------ quick actions
    def _quick(self, db: DB, row, action: str, value: str, local: bool) -> dict:
        uid = row["uid"]
        if action == "skip":
            db.set_status(uid, "skipped", source="you")
            db.commit()
            return {"ok": True, "message": "Skipped"}
        if action == "dismiss":
            from .apply import record_attempt
            record_attempt(db, uid, "")
            db.commit()
            return {"ok": True, "message": "Removed from Needs you"}
        if action == "applied":
            from .apply import mark_applied, record_attempt
            ctx = self.load()
            mark_applied(db, ctx, uid, notes="marked on the dashboard")
            record_attempt(db, uid, "")
            db.commit()
            return {"ok": True, "message": "Recorded as applied. Follow-ups scheduled."}
        if action == "status":
            if value not in STATUSES:
                return {"ok": False, "error": "Unknown status"}
            if value == "interview":           # builds the prep pack, which takes a minute
                return self.submit("interview", uid, local=local)
            db.set_status(uid, value, source="you")
            db.commit()
            return {"ok": True, "message": f"Marked {value}"}
        if action == "open_pack":
            if not local:
                return {"ok": False, "error": "Open the pack on the computer running JobStream"}
            d = pack_dir_for(row)
            if not d:
                return {"ok": False, "error": "No pack yet: build one first"}
            open_folder(d)
            return {"ok": True, "message": f"Opened {d.name}"}
        return {"ok": False, "error": "Unknown action"}

    # ------------------------------------------------------------------ worker
    def _run(self) -> None:
        while True:
            t = self._q.get()
            t.state, t.started = "running", datetime.now().isoformat(timespec="seconds")
            try:
                t.result = self._slow(t)
                t.state = "done"
            except Exception as e:  # keep the worker alive whatever happens
                t.state, t.result = "failed", f"{e.__class__.__name__}: {e}"
                t.messages.append(traceback.format_exc(limit=2).splitlines()[-1])

    def _llm(self, ctx):
        if self.llm_factory:
            return self.llm_factory(ctx)
        from .llm import make_llm
        return make_llm(ctx.settings)

    def _slow(self, t: Task) -> str:
        ctx = self.load()
        db = DB(self.db_path)
        try:
            llm = self._llm(ctx)
            if t.action in ("apply", "pack"):
                from .apply import prepare_and_apply
                out = prepare_and_apply(db, ctx, llm, t.uid, mode="auto" if t.action == "apply" else "pack",
                                        force=t.value == "force")
                t.messages += out.messages
                if out.submitted:
                    return "Applied"
                if t.action == "pack":
                    return "Pack ready"
                row = db.get_job(t.uid)
                att = json.loads(row["extra"] or "{}").get("apply_attempt") or {}
                return "Not sent: " + (att.get("why") or "see the messages") + ". It's on your Needs you list."
            if t.action == "network":
                from .apply import build_networking
                _md, path = build_networking(db, ctx, llm, t.uid)
                return "Networking plan ready" + (f": {path.parent.name}/networking.md" if path else "")
            if t.action == "interview":
                from .interview import build_prep
                row = db.get_job(t.uid)
                db.set_status(t.uid, "interview", source="you")
                db.commit()
                path, msgs = build_prep(llm, ctx, db, db.row_to_job(row), row["sponsor_match"])
                t.messages += msgs
                return f"Interview prep ready: {Path(path).name}"
            raise ValueError(f"Unknown action {t.action}")
        finally:
            db.commit()
            db.conn.close()
