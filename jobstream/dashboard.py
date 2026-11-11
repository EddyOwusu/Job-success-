"""A one-page dashboard: what to do today, your pipeline, shortlist, results and source health.

`build()` writes a single self-contained HTML file (no internet needed to open it); it only reads.
`serve()` runs a small web server on this computer (and, with lan=True, for your phone on your home
Wi-Fi). When it's served, the page's buttons work: Apply, Build pack, Skip, Mark applied, and status
changes. Every button call must carry a secret the page was given, so other websites can't press them.
"""
from __future__ import annotations

import json
import secrets
import socket
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from .config import OUTPUT_DIR, Context
from .db import DB


# ---------------------------------------------------------------------------- data
def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return None
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - t).days)


def _job(r) -> dict:
    b = json.loads(r["score_json"] or "{}")
    a = json.loads(r["assessment_json"] or "{}") if r["assessment_json"] else {}
    extra = json.loads(r["extra"] or "{}")
    return {
        "uid": r["uid"], "title": r["title"], "company": r["company"], "location": (r["location"] or "")[:70],
        "sector": extra.get("sector") or "tech", "status": r["status"], "score": r["score"], "fit": r["fit_score"],
        "verdict": a.get("verdict"), "sponsor": r["sponsor_match"], "scaleup": bool(b.get("scaleup")),
        "salary_min": r["salary_min"], "salary_max": r["salary_max"], "url": r["url"],
        "posted_days": _days_since(r["posted_at"]), "seen_days": _days_since(r["first_seen"]),
        "matched": (b.get("matched_skills") or [])[:8], "missing": (b.get("missing_skills") or [])[:5],
        "why": (a.get("strengths") or [None])[0], "flag": (a.get("red_flags") or [None])[0],
        "alerted": bool(r["alerted_at"]) and (_days_since(r["alerted_at"]) or 0) <= 2,
        "attempt": extra.get("apply_attempt"), "apply_url": r["apply_url"] or r["url"],
        "networked": bool(extra.get("networking_at")),
    }


def _spend(ctx: Context) -> dict:
    from .config import DATA_DIR
    from .spend import Ledger
    try:
        today = Ledger(DATA_DIR / "spend.db").today()
    except Exception:
        today = 0.0
    return {"today": round(today, 2), "budget": float(ctx.settings["llm"].get("daily_budget_usd") or 0)}


def _short(uid: str) -> str:
    """A short form of a job id for commands (the CLI accepts any unique part of an id)."""
    tail = str(uid).split(":")[-1]
    return tail[:8] if len(tail) > 12 else tail


def collect(db: DB, ctx: Context) -> dict:
    from . import growth, health, insights, learn, radar, speculative
    from .visa import threshold_for

    today = date.today().isoformat()
    counts = dict(db.conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    new_today = db.conn.execute("SELECT COUNT(*) FROM jobs WHERE first_seen LIKE ?", (f"{today}%",)).fetchone()[0]

    shortlist = [_job(r) for r in db.jobs("status IN ('shortlisted','packed')",
                                          order="COALESCE(fit_score, score) DESC", limit=150)]
    apps = []
    for r in db.conn.execute(
            """SELECT j.*, a.applied_at, a.method, a.pack_dir FROM applications a JOIN jobs j ON j.uid=a.job_uid
               ORDER BY a.applied_at DESC LIMIT 200"""):
        j = _job(r)
        j.update(applied_days=_days_since(r["applied_at"]), method=r["method"], applied_on=(r["applied_at"] or "")[:10])
        apps.append(j)

    blockers = {"Advert says no sponsorship": 0, "Salary below visa threshold": 0, "Employer not on sponsor register": 0,
                "Security clearance needed": 0, "Other": 0}
    for (sj,) in db.conn.execute("SELECT score_json FROM jobs WHERE status='skipped' AND score_json IS NOT NULL"):
        bl = (json.loads(sj).get("blockers") or [""])[0]
        key = ("Advert says no sponsorship" if "no visa" in bl else "Salary below visa threshold" if "threshold" in bl
               else "Employer not on sponsor register" if "register" in bl else "Security clearance needed"
               if "clearance" in bl.lower() else "Other")
        blockers[key] += 1

    ins = []
    try:
        ins = health.insights(db) + insights.compute(db, ctx)
        ins.sort(key=lambda i: i.priority)
    except Exception:
        pass

    # ---- do today
    todo = []
    for j in shortlist:
        if j["alerted"]:
            todo.append({"kind": "apply", "text": f"Apply today: {j['title']} at {j['company']}",
                         "cmd": f"jobstream apply {_short(j['uid'])}", "url": j["url"], "uid": j["uid"]})
    for f in db.due_followups():
        todo.append({"kind": "follow", "text": f"Follow up: {f['company']} ({f['title']}). {f['message']}",
                     "cmd": f"jobstream followups --done {f['id']}"})
    for j in apps:
        if j["status"] == "interview":
            todo.append({"kind": "interview", "text": f"Interview: {j['company']} ({j['title']}). Read your prep pack.",
                         "cmd": f"jobstream prep {_short(j['uid'])}"})
    for r in speculative.due_followups(db):
        todo.append({"kind": "follow", "text": f"Follow up your speculative note to {r['company']}",
                     "cmd": f"jobstream speculative --close \"{r['company']}\""})
    for r in speculative.unsent(db):
        todo.append({"kind": "send", "text": f"Send your speculative note to {r['company']}",
                     "cmd": f"jobstream speculative --sent \"{r['company']}\""})
    needs = [j for j in shortlist if j["attempt"]]
    ready = [j for j in shortlist if j["status"] == "packed" and not j["attempt"]]
    if ready:
        todo.append({"kind": "apply", "text": f"{len(ready)} application packs are ready to submit",
                     "cmd": "jobstream apply --top 5"})

    rep = learn.report(db)
    gap_list, pool = [], 0
    try:
        gap_list, pool = growth.gaps(db, ctx, limit=6)
    except Exception:
        pass
    new_sponsors = radar.recent_new(db, 14)
    last_run = db.conn.execute("SELECT at, kind FROM events WHERE kind IN ('run','watch') ORDER BY id DESC LIMIT 1").fetchone()
    sp = ctx.settings["sponsorship"]
    return {
        "generated": datetime.now().strftime("%a %d %b %Y, %H:%M"),
        "today": date.today().isoformat(),
        "title": ctx.settings.get("dashboard", {}).get("title", "JobStream"),
        "name": ctx.profile.personal.first_name, "example": bool(ctx.using_examples),
        "holder": {"first": ctx.profile.personal.first_name, "last": ctx.profile.personal.last_name},
        "visa_route": ctx.profile.visa.target_route if ctx.profile.visa.needs_sponsorship else "No sponsor needed",
        "threshold": threshold_for(ctx.profile.visa, ctx.settings)[0],
        "sponsor_count": db.conn.execute("SELECT COUNT(*) FROM sponsor_seen WHERE removed_at IS NULL").fetchone()[0],
        "found": sum(counts.values()),
        "last_run": last_run["at"][:16].replace("T", " ") if last_run else None,
        "counts": {**counts, "new_today": new_today},
        "todo": todo[:12],
        "needs": needs[:20],
        "spend": _spend(ctx),
        "live": None,                  # set by the server: buttons work only when the page is served
        "insights": [{"p": i.priority, "title": i.title, "detail": i.detail} for i in ins][:12],
        "shortlist": shortlist, "applications": apps, "blockers": blockers,
        "learn": {"total": rep.total, "positive": rep.positive, "negative": rep.negative, "ghosted": rep.ghosted,
                  "pending": rep.pending, "findings": rep.findings,
                  "by": {dim: [{"label": g.label, "n": g.n, "decided": g.decided, "positive": g.positive,
                                "rate": g.rate} for g in groups]
                         for dim, groups in rep.breakdowns.items() if dim in ("Sector", "Source", "Claude fit")}},
        "health": [{"name": s.name, "state": s.state, "detail": s.detail, "seen": s.seen,
                    "boards": s.boards if s.kind in health.BOARD_KINDS else None} for s in health.status(db)],
        "gaps": [{"skill": g.skill, "share": g.share, "required": g.required_share, "unlocks": g.unlocks,
                  "employers": g.employers[:4], "status": g.status}
                 for g in sorted(gap_list, key=lambda g: -g.share)],
        "gap_pool": pool,
        "routes": db.get_learned("visa_routes") or [],
        "radar": {"count": len(new_sponsors), "names": [r["name"] for r in new_sponsors[:8]],
                  "boards": len(db.live_boards())},
        "speculative": [{"company": r["company"], "status": r["status"]} for r in db.conn.execute(
            "SELECT company, status FROM speculative ORDER BY created_at DESC LIMIT 12")],
        "projects": [{"skill": r["skill"], "status": r["status"]} for r in db.conn.execute(
            "SELECT skill, status FROM projects ORDER BY created_at DESC")],
    }


# ---------------------------------------------------------------------------- page
def render(data: dict, standalone: bool = True) -> str:
    """The page as HTML. standalone=False gives a fragment (no <html>/<body>) for embedding."""
    from .dashboard_page import BODY, CSS, FONTS, JS

    payload = json.dumps(data, default=str).replace("</", "<\\/")
    head = ('<title>JobStream Dashboard</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            f"{FONTS}\n<style>{CSS}</style>")
    body = f'{BODY}\n<script type="application/json" id="data">{payload}</script>\n<script>{JS}</script>'
    if not standalone:
        return head + body
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}</head>\n<body>{body}</body></html>\n")


def build(db: DB, ctx: Context, path: Optional[Path] = None) -> Path:
    path = path or OUTPUT_DIR / "dashboard.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(collect(db, ctx)), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------- serving
def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def serve(make_page, port: int = 8765, lan: bool = False, token: Optional[str] = None, announce=print, runner=None):
    """Serve the dashboard. make_page(live) returns the HTML; live carries what the page's buttons need.
    With lan=True it is reachable from other devices on your network, behind a random address only you know.
    runner (actions.Runner) makes the buttons work; without one the page is read-only."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    token = token or (secrets.token_urlsafe(9) if lan else "")
    path = f"/{token}" if token else ""
    csrf = secrets.token_urlsafe(24)       # proves a button press came from this page, not another site
    live = {"csrf": csrf, "api": path + "/api"} if runner else None

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data) -> None:
            self._send(code, json.dumps(data, default=str).encode("utf-8"), "application/json")

        def _local(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def do_GET(self):
            route = self.path.split("?")[0].rstrip("/")
            if route == path:
                body = make_page(dict(live, local=self._local()) if live else None).encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
            elif runner and route == f"{path}/api/tasks":
                if self.headers.get("X-JobStream") != csrf:
                    return self._json(403, {"ok": False, "error": "Reload the dashboard"})
                self._json(200, {"tasks": runner.list()})
            else:
                self.send_error(404)

        def do_POST(self):
            route = self.path.split("?")[0].rstrip("/")
            if not runner or not route.startswith(f"{path}/api/"):
                return self.send_error(404)
            # a custom header plus JSON can't be sent by another website without a CORS preflight,
            # which this server never approves
            if self.headers.get("X-JobStream") != csrf or "application/json" not in (self.headers.get("Content-Type") or ""):
                return self._json(403, {"ok": False, "error": "Reload the dashboard"})
            try:
                n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"ok": False, "error": "Bad request"})
            action = route[len(f"{path}/api/"):]
            res = runner.submit(action, str(body.get("uid", "")), str(body.get("value", "")), local=self._local())
            self._json(200 if res.get("ok") else 400, res)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), Handler)
    server.url = f"http://127.0.0.1:{port}{path or '/'}"
    announce(f"Dashboard on this computer:  {server.url}")
    if lan:
        announce(f"On your phone (same Wi-Fi):  http://{lan_ip()}:{port}{path}")
        announce("Anyone on your network who has that address can use it. Press Ctrl+C to stop.")
    return server
