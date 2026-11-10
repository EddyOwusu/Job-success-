"""A one-page dashboard: what to do today, your pipeline, shortlist, results and source health.

`build()` writes a single self-contained HTML file (no internet needed to open it).
`serve()` runs a small read-only web server so you can open it on your phone over
your home Wi-Fi. The page only reads data; nothing on it can change your applications.
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
    }


def collect(db: DB, ctx: Context) -> dict:
    from . import growth, health, insights, learn, radar, speculative

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
        j.update(applied_days=_days_since(r["applied_at"]), method=r["method"])
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
                         "cmd": f"jobagent apply {j['uid']}", "url": j["url"]})
    for f in db.due_followups():
        todo.append({"kind": "follow", "text": f"Follow up: {f['company']} ({f['title']}). {f['message']}",
                     "cmd": f"jobagent followups --done {f['id']}"})
    for j in apps:
        if j["status"] == "interview":
            todo.append({"kind": "interview", "text": f"Interview: {j['company']} ({j['title']}). Read your prep pack.",
                         "cmd": f"jobagent prep {j['uid']}"})
    for r in speculative.due_followups(db):
        todo.append({"kind": "follow", "text": f"Follow up your speculative note to {r['company']}",
                     "cmd": f"jobagent speculative --close \"{r['company']}\""})
    for r in speculative.unsent(db):
        todo.append({"kind": "send", "text": f"Send your speculative note to {r['company']}",
                     "cmd": f"jobagent speculative --sent \"{r['company']}\""})
    ready = [j for j in shortlist if j["status"] == "packed"]
    if ready:
        todo.append({"kind": "apply", "text": f"{len(ready)} application packs are ready to submit",
                     "cmd": "jobagent apply --top 5"})

    rep = learn.report(db)
    gap_list, pool = [], 0
    try:
        gap_list, pool = growth.gaps(db, ctx, limit=6)
    except Exception:
        pass
    new_sponsors = radar.recent_new(db, 14)
    last_run = db.conn.execute("SELECT at, kind FROM events WHERE kind IN ('run','watch') ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "generated": datetime.now().strftime("%a %d %b %Y, %H:%M"),
        "name": ctx.profile.personal.first_name, "example": bool(ctx.using_examples),
        "last_run": last_run["at"][:16].replace("T", " ") if last_run else None,
        "counts": {**counts, "new_today": new_today},
        "todo": todo[:12],
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
CSS = r"""
:root{--bg:#f2f5f7;--surface:#fff;--sunk:#e8edf1;--ink:#14202b;--muted:#566573;--line:#d6dde3;--accent:#0d6b5b;
--accent-soft:#dcefe9;--accent-ink:#fff;--good:#167a3b;--good-soft:#dff3e5;--warn:#9a5800;--warn-soft:#fbecd3;
--bad:#b42318;--bad-soft:#fbe2df;--nhs:#005eb8;--uni:#6b3fa0;--corp:#8a5a00;--tech:#0d6b5b;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
--mono:ui-monospace,"SFMono-Regular",Menlo,Consolas,"Liberation Mono",monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0c1318;--surface:#131e26;--sunk:#0f181f;
--ink:#e5edf2;--muted:#93a4b1;--line:#24323d;--accent:#46bfa3;--accent-soft:#12352e;--accent-ink:#06231d;--good:#5fcf8c;
--good-soft:#123222;--warn:#f0a945;--warn-soft:#3a2a10;--bad:#f2786c;--bad-soft:#3b1714;--nhs:#63a8ec;--uni:#b796e3;
--corp:#e0b25c;--tech:#46bfa3;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0c1318;--surface:#131e26;--sunk:#0f181f;--ink:#e5edf2;--muted:#93a4b1;--line:#24323d;
--accent:#46bfa3;--accent-soft:#12352e;--accent-ink:#06231d;--good:#5fcf8c;--good-soft:#123222;--warn:#f0a945;
--warn-soft:#3a2a10;--bad:#f2786c;--bad-soft:#3b1714;--nhs:#63a8ec;--uni:#b796e3;--corp:#e0b25c;--tech:#46bfa3;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.5;margin:0}
.wrap{max-width:1120px;margin:0 auto;padding-block:24px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));
padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:20px}
h1{font-size:1.5rem;margin:0;letter-spacing:-.01em}h2{font-size:1.02rem;margin:0}
.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.sub{color:var(--muted);font-size:.86rem}
.banner{background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:10px 14px;font-size:.9rem}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
@media (max-width:760px){.stats{grid-template-columns:repeat(3,minmax(0,1fr))}}
.stat{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;min-width:0}
.stat b{display:block;font-size:1.7rem;line-height:1.1;font-variant-numeric:tabular-nums}
.stat span{font-size:.78rem;color:var(--muted)}
.stat.hot b{color:var(--accent)}
.grid2{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:860px){.grid2{grid-template-columns:1fr}}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;min-width:0}
.ph{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid var(--line)}
.pb{padding:14px 16px}.pb.flush{padding:0}
.empty{color:var(--muted);font-size:.9rem}
.todo{display:grid;gap:0;list-style:none;margin:0;padding:0}
.todo li{display:grid;grid-template-columns:76px minmax(0,1fr);gap:12px;padding:11px 16px;border-top:1px solid var(--line);align-items:start}
.todo li:first-child{border-top:0}
.tag{font-size:.7rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:3px 8px;border-radius:999px;text-align:center;white-space:nowrap;align-self:start}
code{font-family:var(--mono);font-size:.82em;background:var(--sunk);border-radius:4px;padding:1px 5px;overflow-wrap:anywhere}
.k-apply{background:var(--accent-soft);color:var(--accent)}.k-follow{background:var(--warn-soft);color:var(--warn)}
.k-interview{background:var(--good-soft);color:var(--good)}.k-send{background:var(--sunk);color:var(--muted)}
.cmd{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:.76rem;color:var(--muted);background:var(--sunk);
border:1px solid var(--line);border-radius:6px;padding:2px 8px;margin-top:4px;cursor:pointer;max-width:100%;overflow-wrap:anywhere;text-align:left}
.cmd:hover,.cmd:focus-visible{border-color:var(--accent);color:var(--ink);outline:none}
.cmd.done{border-color:var(--good);color:var(--good)}
.ins{display:grid;gap:10px}.ins div{display:grid;grid-template-columns:76px minmax(0,1fr);gap:12px;font-size:.9rem}
.p1{background:var(--bad-soft);color:var(--bad)}.p2{background:var(--warn-soft);color:var(--warn)}.p3{background:var(--sunk);color:var(--muted)}
.bars{display:grid;gap:8px}.bar{display:grid;grid-template-columns:150px minmax(0,1fr) 44px;gap:10px;align-items:center;font-size:.86rem}
@media (max-width:520px){.bar{grid-template-columns:110px minmax(0,1fr) 36px}}
.track{height:9px;background:var(--sunk);border-radius:5px;overflow:hidden}.fill{height:100%;background:var(--accent);border-radius:5px}
.fill.bad{background:var(--bad)}.fill.mut{background:var(--muted)}
.num{font-family:var(--mono);font-size:.8rem;text-align:right;font-variant-numeric:tabular-nums}
.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chipbtn{font:inherit;font-size:.8rem;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:4px 12px;cursor:pointer}
.chipbtn[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}
.chipbtn:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
input[type=search]{font:inherit;font-size:.86rem;padding:5px 10px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);min-width:0;width:200px;max-width:100%}
.jobs{display:grid}
.job{display:grid;grid-template-columns:56px minmax(0,1fr) auto;gap:14px;padding:13px 16px;border-top:1px solid var(--line);align-items:start}
.job:first-child{border-top:0}
.score{text-align:center}.score b{display:block;font-size:1.25rem;font-variant-numeric:tabular-nums;line-height:1.1}
.score span{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.jt{font-weight:650}.jt a{color:inherit;text-decoration:none}.jt a:hover{text-decoration:underline}
.meta{color:var(--muted);font-size:.84rem}.note{font-size:.84rem;margin-top:2px}.note.flag{color:var(--warn)}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
.chip{font-family:var(--mono);font-size:.66rem;font-weight:600;letter-spacing:.03em;padding:1px 6px;border-radius:4px;border:1px solid currentColor;white-space:nowrap}
.s-tech{color:var(--tech)}.s-nhs{color:var(--nhs)}.s-university{color:var(--uni)}.s-corporate{color:var(--corp)}
.pill{font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:999px;white-space:nowrap}
.st-packed,.st-shortlisted{background:var(--accent-soft);color:var(--accent)}.st-applied{background:var(--sunk);color:var(--ink)}
.st-interview,.st-offer{background:var(--good-soft);color:var(--good)}.st-rejected,.st-withdrawn{background:var(--bad-soft);color:var(--bad)}
.right{display:grid;gap:6px;justify-items:end}
@media (max-width:620px){.job{grid-template-columns:44px minmax(0,1fr)}.right{grid-column:2;justify-items:start}}
.kv{display:grid;gap:8px;font-size:.9rem}.kv div{display:flex;justify-content:space-between;gap:12px}
.kv span:last-child{font-family:var(--mono);font-size:.82rem}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;background:var(--good)}
.dot.warn{background:var(--warn)}.dot.broken{background:var(--bad)}.dot.new{background:var(--muted)}
.small{font-size:.82rem;color:var(--muted)}
.more{font:inherit;font-size:.86rem;background:none;border:0;color:var(--accent);cursor:pointer;padding:12px 16px;text-align:left;width:100%}
table{width:100%;border-collapse:collapse;font-size:.86rem;font-variant-numeric:tabular-nums}
th{text-align:left;font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600;padding:8px 16px;border-bottom:1px solid var(--line)}
td{padding:8px 16px;border-bottom:1px solid var(--line)}tr:last-child td{border-bottom:0}.tw{overflow-x:auto}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s, r=document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const money = j => (j.salary_min || j.salary_max) ? '£' + Math.round((j.salary_min || j.salary_max)/1000) + 'k–£' + Math.round((j.salary_max || j.salary_min)/1000) + 'k' : '';
const safeUrl = u => (typeof u === 'string' && /^https?:\/\//.test(u)) ? u : null;
function cmd(text){
  const b = el('button', 'cmd', text); b.type = 'button'; b.title = 'Copy this command';
  b.addEventListener('click', () => {
    const ok = () => { b.classList.add('done'); const t = b.textContent; b.textContent = 'Copied'; setTimeout(() => { b.textContent = t; b.classList.remove('done'); }, 1200); };
    const fallback = () => { const r = document.createRange(); r.selectNodeContents(b); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
    try { navigator.clipboard.writeText(text).then(ok, fallback); } catch (e) { fallback(); }
  });
  return b;
}
function rich(text){   // `code` spans, safely
  const f = document.createDocumentFragment();
  String(text).split('`').forEach((part, i) => f.append(i % 2 ? el('code', null, part) : document.createTextNode(part)));
  return f;
}
function bar(label, value, max, cls, right){
  const row = el('div', 'bar'); row.append(el('span', null, label));
  const t = el('div', 'track'), f = el('div', 'fill' + (cls ? ' ' + cls : '')); f.style.width = (max ? Math.max(2, 100*value/max) : 0) + '%'; t.append(f);
  row.append(t, el('span', 'num', right != null ? right : String(value))); return row;
}
// ---- header + stats
$('#gen').textContent = 'Updated ' + D.generated + (D.last_run ? ' · last search ' + D.last_run + ' UTC' : '');
if (D.example) $('#banner').hidden = false;
const c = D.counts, S = $('#stats');
[['New today', c.new_today || 0, c.new_today ? 'hot' : ''], ['Shortlisted', c.shortlisted || 0], ['Packs ready', c.packed || 0],
 ['Applied', c.applied || 0], ['Interviews', c.interview || 0, c.interview ? 'hot' : ''], ['Offers', c.offer || 0, c.offer ? 'hot' : '']]
 .forEach(([l, v, cls]) => { const d = el('div', 'stat' + (cls ? ' ' + cls : '')); d.append(el('b', null, String(v)), el('span', null, l)); S.append(d); });
// ---- do today
const T = $('#todo');
if (!D.todo.length) T.replaceWith(el('p', 'empty pb', 'Nothing urgent. Run “jobagent watch” to check for fresh jobs.'));
D.todo.forEach(t => { const li = el('li'); li.append(el('span', 'tag k-' + t.kind, {apply:'Apply', follow:'Follow up', interview:'Interview', send:'Send'}[t.kind] || t.kind));
  const d = el('div'); const u = safeUrl(t.url);
  if (u) { const a = el('a', null, t.text); a.href = u; a.target = '_blank'; a.rel = 'noopener'; a.style.color = 'inherit'; d.append(a); } else d.append(el('div', null, t.text));
  d.append(el('div')); d.lastChild.append(cmd(t.cmd)); li.append(d); T.append(li); });
// ---- suggestions
const I = $('#insights');
if (!D.insights.length) I.append(el('p', 'empty', 'No suggestions right now.'));
D.insights.forEach(i => { const r = el('div'); r.append(el('span', 'tag p' + i.p, {1:'Act', 2:'This week', 3:'FYI'}[i.p]));
  const d = el('span'); d.append(el('b', null, i.title + '. '), rich(i.detail)); r.append(d); I.append(r); });
// ---- pipeline
const P = $('#pipeline'), order = [['shortlisted','Shortlisted'],['packed','Packs ready'],['applied','Applied'],['interview','Interview'],['offer','Offer'],['rejected','Rejected']];
const pmax = Math.max(1, ...order.map(([k]) => c[k] || 0));
order.forEach(([k, l]) => P.append(bar(l, c[k] || 0, pmax, k === 'rejected' ? 'mut' : '')));
const B = $('#blockers'), bmax = Math.max(1, ...Object.values(D.blockers));
Object.entries(D.blockers).filter(([, v]) => v).forEach(([k, v]) => B.append(bar(k, v, bmax, 'mut')));
if (!B.children.length) B.append(el('p', 'empty', 'Nothing filtered out yet.'));
// ---- shortlist
let sector = 'all', query = '', limit = 12;
const sectors = ['all', ...new Set(D.shortlist.map(j => j.sector))];
const F = $('#sectors');
sectors.forEach(s => { const b = el('button', 'chipbtn', s === 'all' ? 'All' : s === 'nhs' ? 'NHS' : s[0].toUpperCase() + s.slice(1)); b.type = 'button';
  b.setAttribute('aria-pressed', String(s === sector)); b.addEventListener('click', () => { sector = s; limit = 12; [...F.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); drawJobs(); }); F.append(b); });
$('#q').addEventListener('input', e => { query = e.target.value.toLowerCase(); limit = 12; drawJobs(); });
function jobRow(j, withStatus){
  const row = el('div', 'job'), sc = el('div', 'score');
  const v = j.fit != null ? j.fit : j.score; sc.append(el('b', null, v != null ? String(Math.round(v)) : '–'), el('span', null, j.fit != null ? 'fit' : 'score'));
  const mid = el('div'), t = el('div', 'jt'), u = safeUrl(j.url);
  if (u) { const a = el('a', null, j.title); a.href = u; a.target = '_blank'; a.rel = 'noopener'; t.append(a); } else t.textContent = j.title;
  mid.append(t, el('div', 'meta', [j.company, j.location, money(j)].filter(Boolean).join(' · ')));
  if (j.why) mid.append(el('div', 'note', j.why));
  if (j.flag) mid.append(el('div', 'note flag', 'Watch out: ' + j.flag));
  const ch = el('div', 'chips'); ch.append(el('span', 'chip s-' + j.sector, j.sector === 'nhs' ? 'NHS' : j.sector.toUpperCase()));
  if (j.scaleup) ch.append(el('span', 'chip s-tech', 'SCALE-UP'));
  if (!j.sponsor) ch.append(el('span', 'chip', 'CHECK SPONSOR'));
  if (j.posted_days != null && j.posted_days <= 2) ch.append(el('span', 'chip s-tech', 'NEW'));
  j.matched.slice(0, 5).forEach(m => ch.append(el('span', 'chip', m))); mid.append(ch);
  const right = el('div', 'right'); right.append(el('span', 'pill st-' + j.status, withStatus && j.applied_days != null && j.status === 'applied' ? 'applied ' + j.applied_days + 'd ago' : j.status === 'packed' ? 'pack ready' : j.status));
  right.append(cmd(j.status === 'interview' ? 'jobagent prep ' + j.uid : withStatus ? 'jobagent show ' + j.uid : 'jobagent apply ' + j.uid));
  row.append(sc, mid, right); return row;
}
function drawJobs(){
  const J = $('#jobs'); J.textContent = '';
  const rows = D.shortlist.filter(j => (sector === 'all' || j.sector === sector) && (!query || (j.title + ' ' + j.company + ' ' + j.matched.join(' ')).toLowerCase().includes(query)));
  $('#jobcount').textContent = rows.length + ' jobs';
  if (!rows.length) J.append(el('p', 'empty pb', D.shortlist.length ? 'No jobs match that filter.' : 'No jobs yet. Run “jobagent run” to search.'));
  rows.slice(0, limit).forEach(j => J.append(jobRow(j)));
  if (rows.length > limit) { const m = el('button', 'more', 'Show ' + Math.min(20, rows.length - limit) + ' more'); m.type = 'button'; m.addEventListener('click', () => { limit += 20; drawJobs(); }); J.append(m); }
}
drawJobs();
// ---- applications
const A = $('#apps');
if (!D.applications.length) A.append(el('p', 'empty pb', 'No applications yet. When you apply, each one appears here with its status.'));
D.applications.slice(0, 30).forEach(j => A.append(jobRow(j, true)));
// ---- what's working
const L = $('#learn'), le = D.learn;
if (!le.total) L.append(el('p', 'empty', 'After about 20 applications with a result, this shows where your interviews come from.'));
else { L.append(el('p', 'small', le.total + ' applications: ' + le.positive + ' interviews or offers, ' + le.negative + ' rejections, ' + le.ghosted + ' no reply, ' + le.pending + ' waiting.'));
  le.findings.forEach(f => L.append(el('p', 'note', f)));
  Object.entries(le.by).forEach(([dim, groups]) => { if (!groups.some(g => g.rate != null)) return; L.append(el('h2', null, 'Interview rate by ' + dim.toLowerCase())); const w = el('div', 'bars'); w.style.margin = '8px 0 14px';
    groups.forEach(g => w.append(bar(g.label + ' (' + g.decided + ')', g.rate != null ? g.rate : 0, 1, '', g.rate != null ? Math.round(100*g.rate) + '%' : 'few'))); L.append(w); }); }
// ---- skill gaps
const G = $('#gaps');
if (!D.gaps.length) G.append(el('p', 'empty', 'Shows the skills your near-miss jobs ask for, once there are enough jobs.'));
else { const gm = Math.max(...D.gaps.map(g => g.share)); D.gaps.forEach(g => G.append(bar(g.skill + (g.status ? ' ✓' : ''), g.share, gm, '', Math.round(100*g.share) + '%')));
  G.append(el('p', 'small', 'Share of ' + D.gap_pool + ' near-match jobs asking for each skill.')); const d = el('div'); d.append(cmd('jobagent grow --plan')); G.append(d); }
// ---- sources
const H = $('#health');
if (!D.health.length) H.append(el('p', 'empty', 'No searches recorded yet.'));
D.health.forEach(s => { const r = el('div'); const l = el('span'); l.append(el('i', 'dot ' + (s.state === 'ok' ? '' : s.state)), document.createTextNode(s.name));
  r.append(l, el('span', null, s.state === 'broken' ? 'BROKEN' : s.state === 'warn' ? 'check' : (s.boards != null ? s.boards + ' boards · ' : '') + s.seen.toLocaleString() + ' postings')); H.append(r);
  if (s.detail && (s.state === 'broken' || s.state === 'warn')) H.append(el('p', 'small', s.detail)); });
// ---- visa + radar
const V = $('#routes');
if (!D.routes.length) { V.append(el('p', 'empty', 'Run “jobagent visa” to check which routes are open to you.')); }
D.routes.forEach(r => { const d = el('div'); d.append(el('span', null, r.name), el('span', null, r.status.replace('_', ' '))); V.append(d); });
const R = $('#radar'); R.append(el('p', null, D.radar.count + ' newly licensed sponsors in the last 14 days · ' + D.radar.boards + ' company job boards searched'));
if (D.radar.names.length) R.append(el('p', 'small', D.radar.names.join(', ')));
"""

BODY = """
<div class="wrap">
  <div class="top"><h1>Job search dashboard</h1><span class="sub" id="gen"></span></div>
  <div class="banner" id="banner" hidden>Showing the example profile. Run <b>jobagent init</b> and fill in your details.</div>
  <div class="stats" id="stats"></div>
  <div class="grid2">
    <section class="panel"><div class="ph"><h2>Do today</h2><span class="sub">tap a command to copy it</span></div><ul class="todo" id="todo"></ul></section>
    <section class="panel"><div class="ph"><h2>Suggestions</h2></div><div class="pb ins" id="insights"></div></section>
  </div>
  <section class="panel">
    <div class="ph"><h2>Shortlist</h2><div class="filters"><span id="sectors" class="filters"></span>
      <input type="search" id="q" placeholder="Filter by title, company, skill" aria-label="Filter jobs"><span class="sub" id="jobcount"></span></div></div>
    <div class="jobs" id="jobs"></div>
  </section>
  <div class="grid2">
    <section class="panel"><div class="ph"><h2>Pipeline</h2></div><div class="pb"><div class="bars" id="pipeline"></div>
      <h2 style="margin:18px 0 8px">Filtered out for you</h2><div class="bars" id="blockers"></div></div></section>
    <section class="panel"><div class="ph"><h2>What's working</h2></div><div class="pb" id="learn"></div></section>
  </div>
  <section class="panel"><div class="ph"><h2>Applications</h2></div><div class="jobs" id="apps"></div></section>
  <div class="grid2">
    <section class="panel"><div class="ph"><h2>Skills that would open more doors</h2></div><div class="pb"><div class="bars" id="gaps"></div></div></section>
    <section class="panel"><div class="ph"><h2>Job sources</h2></div><div class="pb kv" id="health"></div></section>
  </div>
  <div class="grid2">
    <section class="panel"><div class="ph"><h2>Visa routes</h2></div><div class="pb kv" id="routes"></div></section>
    <section class="panel"><div class="ph"><h2>Sponsor radar</h2></div><div class="pb" id="radar"></div></section>
  </div>
</div>
"""


def render(data: dict, standalone: bool = True) -> str:
    """The page as HTML. standalone=False gives a fragment (no <html>/<body>) for embedding."""
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    head = ('<title>Job Search Dashboard</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            f"<style>{CSS}</style>")
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


def serve(make_page, port: int = 8765, lan: bool = False, token: Optional[str] = None, announce=print):
    """Serve the dashboard read-only. With lan=True it is reachable from other devices on your
    network, behind a random address only you know."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    token = token or (secrets.token_urlsafe(9) if lan else "")
    path = f"/{token}" if token else "/"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0].rstrip("/") != path.rstrip("/"):
                self.send_error(404)
                return
            body = make_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), Handler)
    announce(f"Dashboard on this computer:  http://127.0.0.1:{port}{path}")
    if lan:
        announce(f"On your phone (same Wi-Fi):  http://{lan_ip()}:{port}{path}")
        announce("Anyone on your network who has that address can read it. Press Ctrl+C to stop.")
    return server

