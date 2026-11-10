"""The dashboard's look: a travel document.

Design idea: this is a tool for getting a visa-sponsored job, so the page borrows the
visual language of the papers that journey runs on.
  - Cover: passport navy with gold-foil lettering, a visa-vignette field block, and a
    machine-readable strip that encodes today's real numbers.
  - Seal: a guilloche rosette drawn from your own numbers, so it changes as you progress.
  - Route: the pipeline drawn as a journey with stations, ending at "Visa".
  - Stamps: every application is an ink stamp on a passport page. Shape and word carry the
    status (rectangle = applied, oval = interview, solid gold disc = offer, struck = no),
    so nothing depends on colour alone.
Everything else stays quiet: paper, hairlines, form-style field labels, plain words.

Layout: one column of "sheets" under a full-width cover. Type: Bodoni Moda (certificate
display), Public Sans (text; a face made for government forms) and B612 Mono (document data;
designed for aircraft cockpit displays).
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;700&'
         'family=B612+Mono:wght@400;700&family=Bodoni+Moda:ital,opsz,wght@0,6..96,400..700;1,6..96,400..700&display=swap">')

CSS = r"""
:root{
  --cover:#16233f; --cover-line:#2b3b61; --cover-ink:#e9edf5; --cover-muted:#92a2c6; --foil:#cfae5c;
  --paper:#e8ede9; --page:#fbfcfa; --sunk:#eef2ee; --ink:#111b33; --muted:#55607a; --line:#c6cfcb;
  --blue:#1f4fbf; --green:#18794e; --red:#b3261e; --amber:#8a5a00; --grey:#5d6679; --foil-ink:#16233f;
  --display:"Bodoni Moda","Bodoni 72",Didot,"Times New Roman",serif;
  --text:"Public Sans","Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",sans-serif;
  --mono:"B612 Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#0b1324; --page:#121c33; --sunk:#0e1730; --ink:#e9edf5; --muted:#9aa6bf; --line:#293a5f;
  --blue:#8fb0ff; --green:#62d19a; --red:#ff8f80; --amber:#f0b45c; --grey:#9aa6bf; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#0b1324; --page:#121c33; --sunk:#0e1730; --ink:#e9edf5; --muted:#9aa6bf; --line:#293a5f;
  --blue:#8fb0ff; --green:#62d19a; --red:#ff8f80; --amber:#f0b45c; --grey:#9aa6bf; color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--text);font-size:15px;line-height:1.5}
.gut{max-width:1120px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1,h2,h3,p,dl,dd,ol,ul{margin:0;padding:0}
ol,ul{list-style:none}

/* ---------- cover */
.cover{background:var(--cover);color:var(--cover-ink)}
.cover-in{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:center;padding-block:30px 22px}
.issuer{font-family:var(--mono);font-size:.68rem;letter-spacing:.24em;text-transform:uppercase;color:var(--foil)}
.wordmark{font-family:var(--display);font-weight:500;font-size:clamp(2.3rem,6.4vw,4rem);line-height:1;letter-spacing:.07em;
  text-transform:uppercase;color:var(--foil);margin:8px 0 0;text-wrap:balance;font-variant-numeric:lining-nums}
.vignette{display:grid;grid-template-columns:repeat(5,auto);justify-content:start;gap:14px 30px;margin-top:22px}
.vignette dt{font-family:var(--mono);font-size:.6rem;letter-spacing:.16em;text-transform:uppercase;color:var(--cover-muted)}
.vignette dd{font-size:.95rem;font-weight:700;margin-top:2px;color:var(--cover-ink);white-space:nowrap;font-variant-numeric:tabular-nums}
.vignette dd.doc{font-family:var(--mono);font-weight:400;font-size:.84rem;margin-top:4px}
.sealbox{display:grid;justify-items:center;gap:6px}
#seal{width:156px;height:156px;display:block}
.sealbox span{font-family:var(--mono);font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:var(--cover-muted)}
.mrzband{border-top:1px solid var(--cover-line)}
.mrz{font-family:var(--mono);font-size:clamp(8px,2.02vw,13.5px);letter-spacing:.12em;line-height:1.55;color:var(--cover-muted);
  white-space:pre;overflow:hidden;padding-block:10px 12px}
.perf{height:9px;background:radial-gradient(circle at 6px 0,var(--paper) 3.2px,transparent 3.6px) 0 0/12px 9px repeat-x var(--cover)}
@media (max-width:760px){
  .cover-in{grid-template-columns:minmax(0,1fr);padding-block:22px 16px}
  .sealbox{position:absolute;right:max(16px,env(safe-area-inset-right,0px));top:18px}
  #seal{width:84px;height:84px}.sealbox span{display:none}
  .cover{position:relative}.wordmark,.issuer{max-width:calc(100% - 100px)}
  .vignette{grid-template-columns:repeat(2,minmax(0,auto));gap:12px 24px}
}

/* ---------- page furniture */
main{display:grid;gap:34px;padding-block:28px 56px}
.head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}
h2{font-family:var(--display);font-style:italic;font-weight:500;font-size:1.55rem;line-height:1.1;letter-spacing:.005em}
.meta{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.sheet{background:var(--page);border:1px solid var(--line);border-radius:3px;min-width:0}
.pad{padding:16px 18px}
.split{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:34px 28px;align-items:start}
.quad{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:34px 28px;align-items:start}
@media (max-width:860px){.split,.quad{grid-template-columns:minmax(0,1fr)}}
.empty{color:var(--muted);font-size:.92rem}
.notice{border:1px dashed var(--amber);color:var(--amber);border-radius:3px;padding:10px 14px;font-size:.9rem}
code{font-family:var(--mono);font-size:.82em;background:var(--sunk);border-radius:2px;padding:1px 5px;overflow-wrap:anywhere}
a{color:inherit}
:focus-visible{outline:2px solid var(--blue);outline-offset:2px}

/* command chips: tap to copy */
.cmd{font:inherit;font-family:var(--mono);font-size:.72rem;color:var(--muted);background:transparent;border:1px dashed var(--line);
  border-radius:2px;padding:3px 8px;cursor:pointer;text-align:left;max-width:100%;overflow-wrap:anywhere}
.cmd::before{content:"$ ";opacity:.6}
.cmd:hover{border-style:solid;border-color:var(--ink);color:var(--ink)}
.cmd.done{border-style:solid;border-color:var(--green);color:var(--green)}

/* small ink marks (flat stamps) */
.mark{display:inline-block;font-family:var(--mono);font-size:.62rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--c,var(--grey));border:1.5px solid currentColor;border-radius:2px;padding:2px 6px;white-space:nowrap;align-self:start;justify-self:start}
.c-blue{--c:var(--blue)}.c-green{--c:var(--green)}.c-red{--c:var(--red)}.c-amber{--c:var(--amber)}.c-grey{--c:var(--grey)}
.mark.solid{background:var(--foil);border-color:var(--foil);color:var(--foil-ink)}
.code{font-family:var(--mono);font-size:.66rem;font-weight:700;letter-spacing:.1em;border:1px solid var(--line);border-radius:2px;padding:2px 5px;color:var(--muted)}

/* ---------- the route */
.route{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));position:relative;padding:20px 8px 16px}
.route::before,.route::after{content:"";position:absolute;top:89px;left:calc(100% / 14);height:0}
.route::before{right:calc(100% / 14);border-top:2px dashed var(--line)}
.route::after{width:calc((100% - 100% / 7) * var(--p,0));border-top:2px solid var(--ink)}
.stn{display:grid;justify-items:center;text-align:center;grid-template-rows:56px 24px auto;position:relative;z-index:1}
.stn .n{font-family:var(--display);font-weight:500;font-size:2.7rem;line-height:56px;font-variant-numeric:lining-nums tabular-nums;color:var(--muted)}
.stn.reached .n{color:var(--ink)}
.stn .node{width:14px;height:14px;border-radius:50%;border:2px solid var(--line);background:var(--page);align-self:center}
.stn.reached .node{border-color:var(--ink);background:var(--ink)}
.stn.front .node{box-shadow:0 0 0 4px var(--page),0 0 0 5.5px var(--ink)}
.stn.dest .node{width:18px;height:18px;border-color:var(--foil);background:var(--page);border-radius:3px;transform:rotate(45deg)}
.stn.dest.reached .node{background:var(--foil)}
.stn .l{font-family:var(--mono);font-size:.64rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:6px}
.stn .x{font-size:.74rem;color:var(--muted);margin-top:2px}
@media (max-width:700px){
  .route{grid-template-columns:minmax(0,1fr);padding:10px 16px}
  .route::before{top:26px;bottom:26px;left:22px;right:auto;border-top:0;border-left:2px dashed var(--line);height:auto}
  .route::after{display:none}
  .stn{grid-template-columns:14px 78px minmax(0,1fr);grid-template-rows:auto;justify-items:start;text-align:left;align-items:center;gap:0 14px;padding:5px 0}
  .stn .node{grid-column:1;grid-row:1}.stn .n{grid-column:2;grid-row:1;font-size:2rem;line-height:40px}
  .stn .l{grid-column:3;grid-row:1;margin:0}.stn .x{grid-column:3;grid-row:2;margin:-8px 0 0}
  .stn.dest .node{width:14px;height:14px}
}

/* ---------- today + notes */
.todo li{display:grid;grid-template-columns:34px minmax(0,1fr);gap:12px;padding:13px 18px;border-top:1px solid var(--line)}
.todo li:first-child{border-top:0}
.todo .no{font-family:var(--mono);font-size:.78rem;color:var(--muted);padding-top:2px}
.todo .what{display:grid;gap:6px;justify-items:start}
.todo .what a{text-decoration-thickness:1px;text-underline-offset:3px}
.notes li{display:grid;grid-template-columns:84px minmax(0,1fr);gap:12px;padding:11px 0;border-top:1px solid var(--line);font-size:.92rem}
.notes li:first-child{border-top:0;padding-top:0}
.notes b{font-weight:700}
@media (max-width:520px){.notes li{grid-template-columns:minmax(0,1fr);gap:6px}}

/* ---------- shortlist ledger */
.filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.fbtn{font:inherit;font-family:var(--mono);font-size:.68rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;background:transparent;
  color:var(--muted);border:1px solid var(--line);border-radius:2px;padding:5px 9px;cursor:pointer}
.fbtn:hover{border-color:var(--ink);color:var(--ink)}
.fbtn[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:var(--page)}
input[type=search]{font:inherit;font-size:.86rem;padding:5px 10px;border:1px solid var(--line);border-radius:2px;background:var(--page);color:var(--ink);width:210px;max-width:100%}
.job{display:grid;grid-template-columns:62px minmax(0,1fr) 172px 176px;gap:6px 18px;padding:15px 18px;border-top:1px solid var(--line);align-items:start}
.job:first-child{border-top:0}
.fit{text-align:center}
.fit b{display:block;font-family:var(--display);font-weight:500;font-size:2rem;line-height:1;font-variant-numeric:lining-nums tabular-nums}
.fit span{font-family:var(--mono);font-size:.56rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.jt{font-weight:700;font-size:1rem;line-height:1.3}
.jt a{text-decoration:none}.jt a:hover{text-decoration:underline;text-underline-offset:3px}
.sub{color:var(--muted);font-size:.86rem}
.why{font-size:.86rem;margin-top:3px}.why.flag{color:var(--amber)}
.skills{font-family:var(--mono);font-size:.68rem;color:var(--muted);margin-top:5px;letter-spacing:.02em}
.creds{display:grid;gap:6px;justify-items:start;font-size:.78rem}
.cred{display:flex;gap:6px;align-items:baseline;color:var(--c,var(--muted))}
.cred i{font-style:normal;font-family:var(--mono);font-weight:700}
.act{display:grid;gap:8px;justify-items:end}
.more{font:inherit;font-family:var(--mono);font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;background:none;border:0;border-top:1px solid var(--line);
  color:var(--ink);cursor:pointer;padding:13px 18px;text-align:left;width:100%}
.more:hover{background:var(--sunk)}
@media (max-width:900px){.job{grid-template-columns:54px minmax(0,1fr)}.creds,.act{grid-column:2;justify-items:start}.creds{display:flex;flex-wrap:wrap;gap:6px 14px}}

/* ---------- stamps */
.stamps{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:30px 14px;padding:30px 18px 24px}
@media (max-width:520px){.stamps{grid-template-columns:repeat(2,minmax(0,1fr));gap:26px 12px;padding:24px 12px 20px}
  .stamp{padding:11px 8px}.stamp .w{font-size:.86rem;letter-spacing:.14em}.stamp.interview{padding:16px 12px}}
.slot{display:grid;justify-items:center;align-content:start;gap:14px;min-width:0}
.slot .cmd{font-size:.66rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stamp{--c:var(--blue);color:var(--c);font-family:var(--mono);text-align:center;display:grid;gap:4px;justify-items:center;align-content:center;
  width:100%;max-width:172px;min-height:112px;padding:13px 12px;border-radius:5px;transform:rotate(var(--r,0deg));position:relative}
.stamp::before{content:"";position:absolute;inset:0;border:2.5px solid currentColor;outline:1px solid currentColor;outline-offset:3px;border-radius:inherit;filter:url(#ink)}
.stamp .w{font-weight:700;font-size:1.02rem;letter-spacing:.2em;text-transform:uppercase;line-height:1.1}
.stamp .co{font-family:var(--text);font-weight:700;font-size:.9rem;line-height:1.2;overflow-wrap:anywhere}
.stamp .ro{font-size:.62rem;line-height:1.3;letter-spacing:.02em;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.stamp .d{font-size:.64rem;letter-spacing:.14em;border-top:1px solid currentColor;padding-top:4px;margin-top:2px}
.stamp.interview{--c:var(--green);border-radius:50%/46%;padding:18px 22px}
.stamp.offer{--c:var(--foil-ink);background:var(--foil);border-radius:50%;aspect-ratio:1;max-width:160px}
.stamp.offer::before{border-color:var(--foil);outline-color:var(--foil)}
.stamp.rejected,.stamp.withdrawn{--c:var(--red)}
.stamp.rejected::before,.stamp.withdrawn::before{outline:0;border-width:1.5px}
.stamp.rejected::after,.stamp.withdrawn::after{content:"";position:absolute;left:8%;right:8%;top:50%;border-top:1.5px solid currentColor;transform:rotate(-12deg)}
.stamp.ghost{color:var(--muted)}
.stamp.ghost::before{border:1.5px dashed var(--line);outline:0;filter:none}
@media (prefers-reduced-motion:no-preference){
  .stamp:not(.ghost){animation:press .42s cubic-bezier(.2,1.5,.4,1) backwards;animation-delay:calc(var(--i,0) * 55ms)}
  @keyframes press{from{transform:rotate(var(--r,0deg)) scale(1.16)}to{transform:rotate(var(--r,0deg)) scale(1)}}
}

/* ---------- bars (one series each: the heading names it) */
.bars{display:grid;gap:9px}
.bar{display:grid;grid-template-columns:minmax(0,150px) minmax(0,1fr) 46px;gap:12px;align-items:center;font-size:.86rem}
.track{height:6px;background:var(--sunk);border-radius:0 4px 4px 0}
.fill{height:100%;background:var(--ink);border-radius:0 4px 4px 0;min-width:2px}
.fill.quiet{background:var(--grey)}
.val{font-family:var(--mono);font-size:.76rem;text-align:right;font-variant-numeric:tabular-nums}
.bar:hover .fill{background:var(--blue)}
.cap{font-size:.8rem;color:var(--muted);margin-top:12px}
h3{font-family:var(--mono);font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:400;margin:16px 0 9px}
h3:first-child{margin-top:0}
.rows{display:grid}
.rows>div{display:flex;justify-content:space-between;align-items:baseline;gap:14px;padding:8px 0;border-top:1px solid var(--line);font-size:.9rem}
.rows>div:first-child{border-top:0;padding-top:0}
.rows .r{font-size:.8rem;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums;display:flex;gap:10px;align-items:baseline;justify-content:flex-end;flex-wrap:wrap}
.detail{font-size:.8rem;color:var(--muted);padding:0 0 8px}
.big{font-family:var(--display);font-size:2.4rem;line-height:1;font-weight:500;font-variant-numeric:lining-nums}
.colophon{font-family:var(--mono);font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s, r=document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const c = D.counts, n = k => c[k] || 0;
const safeUrl = u => (typeof u === 'string' && /^https?:\/\//.test(u)) ? u : null;
const MON = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
const docDate = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? m[3] + ' ' + MON[+m[2]-1] + ' ' + m[1] : ''; };
const money = j => (j.salary_min || j.salary_max) ? '£' + Math.round((j.salary_min || j.salary_max)/1000) + 'k–£' + Math.round((j.salary_max || j.salary_min)/1000) + 'k' : '';
const hash = s => { let h = 0; for (const ch of String(s)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return h; };
function rich(text){ const f = document.createDocumentFragment();
  String(text).split('`').forEach((part, i) => f.append(i % 2 ? el('code', null, part) : document.createTextNode(part))); return f; }
function cmd(text){
  const b = el('button', 'cmd', text); b.type = 'button'; b.title = 'Copy this command';
  b.addEventListener('click', () => {
    const ok = () => { b.classList.add('done'); const t = b.textContent; b.textContent = 'copied'; setTimeout(() => { b.textContent = t; b.classList.remove('done'); }, 1200); };
    const fallback = () => { const r = document.createRange(); r.selectNodeContents(b); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
    try { navigator.clipboard.writeText(text).then(ok, fallback); } catch (e) { fallback(); }
  });
  return b;
}
const short = uid => { const id = String(uid).split(':').pop(); return id.length > 12 ? id.slice(0, 8) : id; };
function link(text, url){ const u = safeUrl(url); if (!u) return document.createTextNode(text); const a = el('a', null, text); a.href = u; a.target = '_blank'; a.rel = 'noopener'; return a; }
function bar(label, value, max, right, tip, quiet){
  const row = el('div', 'bar'); if (tip) row.title = tip; row.append(el('span', null, label));
  const t = el('div', 'track'), f = el('div', 'fill' + (quiet ? ' quiet' : '')); f.style.width = (max ? 100 * value / max : 0) + '%'; t.append(f);
  row.append(t, el('span', 'val', right != null ? right : String(value))); return row;
}

// ---------- cover
document.title = D.title + ' · Dashboard';
$('#wordmark').textContent = D.title;
$('#issuer').textContent = D.visa_route + ' · United Kingdom';
const seq = [D.found, n('shortlisted') + n('packed'), n('applied') + n('interview') + n('offer') + n('rejected'), n('interview') + n('offer'), n('offer')];
const sealNo = seq.slice(0, 4).map(v => String(v).padStart(3, '0')).join('-');
[['Holder', (D.holder.first + ' ' + D.holder.last).trim()], ['Salary floor', '£' + Number(D.threshold).toLocaleString('en-GB')],
 ['Licensed sponsors', D.sponsor_count ? Number(D.sponsor_count).toLocaleString('en-GB') : 'not loaded'],
 ['Last search', D.last_run ? docDate(D.last_run) + ' ' + D.last_run.slice(11, 16) : 'never'], ['Seal no.', sealNo]]
 .forEach(([k, v]) => { const d = el('div'); d.append(el('dt', null, k), el('dd', /^(Last|Seal)/.test(k) ? 'doc' : null, v)); $('#vignette').append(d); });
// machine-readable strip: today's numbers, written the way a passport writes them
const A = s => String(s || '').normalize('NFD').toUpperCase().replace(/[^A-Z ]/g, '').trim().replace(/ +/g, '<');
const pad = (s, len) => (s + '<'.repeat(len)).slice(0, len);
const l1 = pad('P<GBR' + A(D.holder.last) + '<<' + A(D.holder.first), 44);
const body = D.today.slice(2).replace(/-/g, '') + 'GBR' + 'F' + String(seq[0]).padStart(4, '0') + 'S' + String(seq[1]).padStart(3, '0') +
  'A' + String(seq[2]).padStart(3, '0') + 'I' + String(seq[3]).padStart(2, '0') + 'O' + String(seq[4]).padStart(2, '0');
const check = [...body].reduce((t, ch, i) => t + (/\d/.test(ch) ? +ch : ch.charCodeAt(0) - 55) * [7, 3, 1][i % 3], 0) % 10;
$('#mrz').textContent = l1 + '\n' + pad(body, 43) + check;
$('#mrz').title = 'Today in passport notation: date, then Found, Shortlisted, Applied, Interviews, Offers, and a check digit';

// the seal: a guilloche rosette whose geometry comes from your own numbers
(function seal(){
  const cv = $('#seal'), css = cv.getBoundingClientRect().width || 156, dpr = Math.min(3, window.devicePixelRatio || 1);
  cv.width = cv.height = Math.round(css * dpr); const g = cv.getContext('2d'); g.scale(dpr, dpr);
  const R = css / 2, foil = getComputedStyle(document.documentElement).getPropertyValue('--foil').trim() || '#cfae5c';
  g.translate(R, R); g.strokeStyle = foil; g.lineJoin = 'round';
  const petals = 7 + (seq[1] % 9), lobes = 3 + (seq[2] % 6), rings = 9, twist = (seq[0] % 360) * Math.PI / 180;
  const ring = (r, w, a) => { g.globalAlpha = a; g.lineWidth = w; g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.stroke(); };
  ring(R - 1.5, 1.2, .95); ring(R - 5, .5, .7);
  for (let k = 0; k < rings; k++) {
    g.globalAlpha = .34 + .05 * k; g.lineWidth = .55; g.beginPath();
    const phase = twist + k * Math.PI / rings, base = (R - 12) * (.60 + .035 * k);
    for (let i = 0; i <= 720; i++) { const t = i / 720 * Math.PI * 2;
      const r = base + (R - 12) * .16 * Math.cos(petals * t + phase) + (R - 12) * .07 * Math.sin(lobes * 2 * t - phase * 2);
      const x = r * Math.cos(t), y = r * Math.sin(t); i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.closePath(); g.stroke();
  }
  const pts = 5 + (seq[3] % 4) + (seq[4] ? 3 : 0);               // the inner star grows with interviews and offers
  g.globalAlpha = .95; g.lineWidth = .9; g.beginPath();
  for (let i = 0; i <= pts * 2; i++) { const t = twist + i * Math.PI / pts, r = (i % 2 ? .13 : .3) * R; const x = r * Math.cos(t), y = r * Math.sin(t); i ? g.lineTo(x, y) : g.moveTo(x, y); }
  g.closePath(); g.stroke();
  if (seq[4]) { g.globalAlpha = 1; g.fillStyle = foil; g.fill(); }
})();
if (D.example) $('#notice').hidden = false;

// ---------- the route
const stations = [['Found', D.found, n('new_today') ? '+' + n('new_today') + ' today' : ''], ['Shortlisted', n('shortlisted'), ''],
  ['Packs ready', n('packed'), ''], ['Applied', n('applied'), ''], ['Interview', n('interview'), ''], ['Offer', n('offer'), ''], ['Visa', null, '']];
let front = 0; stations.forEach(([, v], i) => { if (v) front = i; });
const RT = $('#route'); RT.style.setProperty('--p', String(front / 6));
stations.forEach(([label, v, extra], i) => { const s = el('li', 'stn' + (v ? ' reached' : '') + (i === front ? ' front' : '') + (i === 6 ? ' dest' : ''));
  s.append(el('span', 'n', v == null ? '·' : String(v)), el('span', 'node'), el('span', 'l', label)); if (extra) s.append(el('span', 'x', extra)); RT.append(s); });
$('#routemeta').textContent = n('rejected') ? n('rejected') + ' closed without an offer' : 'updated ' + D.generated;

// ---------- today
const T = $('#todo'), KIND = {apply: ['Apply', 'c-blue'], follow: ['Follow up', 'c-amber'], interview: ['Interview', 'c-green'], send: ['Send', 'c-grey']};
if (!D.todo.length) T.replaceWith(el('p', 'empty pad', 'Nothing urgent. Run “jobagent watch” to check for fresh jobs.'));
D.todo.forEach((t, i) => { const li = el('li'); li.append(el('span', 'no', String(i + 1).padStart(2, '0')));
  const w = el('div', 'what'), k = KIND[t.kind] || [t.kind, 'c-grey']; w.append(el('span', 'mark ' + k[1], k[0]));
  const p = el('div'); p.append(link(t.text, t.url)); w.append(p, cmd(t.cmd)); li.append(w); T.append(li); });
$('#todometa').textContent = D.todo.length ? D.todo.length + ' to do · tap a command to copy it' : '';

// ---------- notes from the agent
const N = $('#notes'), PR = {1: ['Act', 'c-red'], 2: ['This week', 'c-blue'], 3: ['FYI', 'c-grey']};
if (!D.insights.length) N.replaceWith(el('p', 'empty', 'No notes right now.'));
D.insights.forEach(i => { const li = el('li'); li.append(el('span', 'mark ' + PR[i.p][1], PR[i.p][0])); const d = el('div'); d.append(el('b', null, i.title + '. '), rich(i.detail)); li.append(d); N.append(li); });

// ---------- shortlist
const SECT = {tech: 'TEC', nhs: 'NHS', university: 'UNI', corporate: 'COR'}, SECTNAME = {tech: 'Tech company', nhs: 'NHS', university: 'University', corporate: 'Large employer'};
let sector = 'all', query = '', limit = 10;
const F = $('#sectors');
['all', ...new Set(D.shortlist.map(j => j.sector))].forEach(s => { const b = el('button', 'fbtn', s === 'all' ? 'All' : (SECT[s] || s)); b.type = 'button'; b.title = s === 'all' ? 'Every sector' : (SECTNAME[s] || s);
  b.setAttribute('aria-pressed', String(s === sector)); b.addEventListener('click', () => { sector = s; limit = 10; [...F.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); drawJobs(); }); F.append(b); });
$('#q').addEventListener('input', e => { query = e.target.value.toLowerCase(); limit = 10; drawJobs(); });
function jobRow(j){
  const row = el('div', 'job'), fit = el('div', 'fit'), v = j.fit != null ? j.fit : j.score;
  fit.append(el('b', null, v != null ? String(Math.round(v)) : '–'), el('span', null, j.fit != null ? 'fit' : 'score'));
  const mid = el('div'), t = el('div', 'jt'); t.append(link(j.title, j.url));
  mid.append(t, el('div', 'sub', [j.company, j.location, money(j)].filter(Boolean).join(' · ')));
  if (j.why) mid.append(el('div', 'why', j.why));
  if (j.flag) mid.append(el('div', 'why flag', 'Watch out: ' + j.flag));
  if (j.matched.length) mid.append(el('div', 'skills', j.matched.slice(0, 6).join(' · ')));
  const cr = el('div', 'creds'), cred = (cls, glyph, text) => { const d = el('div', 'cred ' + cls); d.append(el('i', null, glyph), document.createTextNode(text)); return d; };
  const sc = el('span', 'code', SECT[j.sector] || j.sector.slice(0, 3).toUpperCase()); sc.title = SECTNAME[j.sector] || j.sector; cr.append(sc);
  cr.append(j.sponsor ? cred('c-green', '✓', 'Licensed sponsor') : cred('c-amber', '?', 'Sponsor not confirmed'));
  if (j.scaleup) cr.append(cred('c-blue', '↗', 'Scale-up licence'));
  if (j.posted_days != null && j.posted_days <= 2) cr.append(cred('c-blue', '•', j.posted_days ? 'Posted ' + j.posted_days + 'd ago' : 'Posted today'));
  const act = el('div', 'act'); act.append(el('span', 'mark ' + (j.status === 'packed' ? 'c-blue' : 'c-grey'), j.status === 'packed' ? 'Pack ready' : 'Shortlisted'), cmd('jobagent apply ' + short(j.uid)));
  row.append(fit, mid, cr, act); return row;
}
function drawJobs(){
  const J = $('#jobs'); J.textContent = '';
  const rows = D.shortlist.filter(j => (sector === 'all' || j.sector === sector) && (!query || (j.title + ' ' + j.company + ' ' + j.matched.join(' ')).toLowerCase().includes(query)));
  $('#jobcount').textContent = rows.length + (rows.length === 1 ? ' job' : ' jobs');
  if (!rows.length) J.append(el('p', 'empty pad', D.shortlist.length ? 'No jobs match that filter.' : 'No jobs yet. Run “jobagent run” to search.'));
  rows.slice(0, limit).forEach(j => J.append(jobRow(j)));
  if (rows.length > limit) { const m = el('button', 'more', 'Show ' + Math.min(15, rows.length - limit) + ' more'); m.type = 'button'; m.addEventListener('click', () => { limit += 15; drawJobs(); }); J.append(m); }
}
drawJobs();

// ---------- stamps: one per application
const ST = $('#stamps'), WORD = {applied: 'Applied', interview: 'Interview', offer: 'Offer', rejected: 'No', withdrawn: 'Withdrawn'};
D.applications.slice(0, 40).forEach((j, i) => { const slot = el('div', 'slot'), s = el('div', 'stamp ' + j.status);
  s.style.setProperty('--r', ((hash(j.uid) % 9) - 4) * 0.9 + 'deg'); s.style.setProperty('--i', String(i));
  s.append(el('span', 'w', WORD[j.status] || j.status), el('span', 'co', j.company), el('span', 'ro', j.title), el('span', 'd', docDate(j.applied_on)));
  s.title = j.title + ' at ' + j.company + (j.applied_days != null ? ' · applied ' + j.applied_days + ' days ago' : '');
  slot.append(s, cmd(j.status === 'interview' ? 'jobagent prep ' + short(j.uid) : 'jobagent show ' + short(j.uid))); ST.append(slot); });
if (!D.applications.length) { const slot = el('div', 'slot'), g = el('div', 'stamp ghost'); g.append(el('span', 'w', 'Applied'), el('span', 'ro', 'Your first stamp lands here when you send an application')); slot.append(g); ST.append(slot); }
const closed = n('rejected') + n('withdrawn');
$('#stampmeta').textContent = D.applications.length ? D.applications.length + ' sent · ' + (n('interview') + n('offer')) + ' interviews · ' + closed + ' closed' : 'none yet';

// ---------- what's working / filtered out
const L = $('#learn'), le = D.learn;
if (!le.total) L.append(el('p', 'empty', 'After about 20 applications with a result, this shows where your interviews come from.'));
else { le.findings.forEach(f => L.append(el('p', 'detail', f)));
  Object.entries(le.by).forEach(([dim, groups]) => { if (!groups.some(g => g.rate != null)) return; L.append(el('h3', null, 'Interview rate by ' + dim.toLowerCase())); const w = el('div', 'bars');
    groups.forEach(g => w.append(bar(g.label, g.rate != null ? g.rate : 0, 1, g.rate != null ? Math.round(100 * g.rate) + '%' : 'few', g.positive + ' interviews from ' + g.decided + ' decided applications'))); L.append(w); }); }
const B = $('#blockers'), bl = Object.entries(D.blockers).filter(([, v]) => v), bmax = Math.max(1, ...bl.map(([, v]) => v));
bl.forEach(([k, v]) => B.append(bar(k, v, bmax, String(v), v + ' jobs: ' + k.toLowerCase(), true)));
if (!bl.length) B.append(el('p', 'empty', 'Nothing filtered out yet.'));
$('#blockmeta').textContent = bl.length ? bl.reduce((t, [, v]) => t + v, 0) + ' jobs kept out of your way' : '';

// ---------- skills, sources, visa routes, radar
const G = $('#gaps');
if (!D.gaps.length) G.append(el('p', 'empty', 'Shows the skills your near-miss jobs ask for, once there are enough jobs.'));
else { const gm = Math.max(...D.gaps.map(g => g.share)), w = el('div', 'bars');
  D.gaps.forEach(g => w.append(bar(g.skill + (g.status ? ' (planned)' : ''), g.share, gm, Math.round(100 * g.share) + '%', 'Asked for by ' + g.employers.join(', ') + (g.unlocks ? ' · would unlock ' + g.unlocks + ' near-miss jobs' : ''))));
  G.append(w, el('p', 'cap', 'Share of ' + D.gap_pool + ' near-match jobs that ask for each skill you have not listed.')); const d = el('p'); d.style.marginTop = '10px'; d.append(cmd('jobagent grow --plan')); G.append(d); }
const H = $('#health'), STATE = {ok: ['OK', 'c-green'], new: ['First run', 'c-grey'], warn: ['Check', 'c-amber'], broken: ['Broken', 'c-red']};
if (!D.health.length) H.append(el('p', 'empty', 'No searches recorded yet.'));
D.health.forEach(s => { const r = el('div'), right = el('span', 'r'); right.append(el('span', null, (s.boards != null ? s.boards + ' boards · ' : '') + Number(s.seen).toLocaleString('en-GB') + ' postings'));
  const st = STATE[s.state] || STATE.ok; right.append(el('span', 'mark ' + st[1], st[0])); r.append(el('span', null, s.name), right); H.append(r);
  if (s.detail && (s.state === 'broken' || s.state === 'warn')) H.append(el('p', 'detail', s.detail)); });
const V = $('#routes'), RS = {likely: ['Likely', 'c-green'], possible: ['Possible', 'c-blue'], check: ['Worth checking', 'c-grey'], unlikely: ['Unlikely', 'c-grey'], not_eligible: ['Not eligible', 'c-grey']};
if (!D.routes.length) V.append(el('p', 'empty', 'Run “jobagent visa” to check which routes are open to you.'));
D.routes.forEach(r => { const d = el('div'), st = RS[r.status] || [r.status, 'c-grey']; d.append(link(r.name, r.link), el('span', 'mark ' + st[1], st[0])); V.append(d); });
const R = $('#radar'); R.append(el('p', 'big', String(D.radar.count)), el('p', 'cap', 'employers newly licensed to sponsor in the last 14 days. ' + D.radar.boards + ' company job boards are searched on every run.'));
if (D.radar.names.length) R.append(el('p', 'detail', D.radar.names.join(' · ')));
$('#colophon').textContent = D.title + ' · read-only · generated ' + D.generated;
"""

BODY = """
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><filter id="ink" x="-6%" y="-6%" width="112%" height="112%">
  <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="7" result="n"/><feDisplacementMap in="SourceGraphic" in2="n" scale="1.5"/></filter></svg>
<header class="cover">
  <div class="gut cover-in">
    <div>
      <p class="issuer" id="issuer"></p>
      <h1 class="wordmark" id="wordmark"></h1>
      <dl class="vignette" id="vignette"></dl>
    </div>
    <div class="sealbox"><canvas id="seal" role="img" aria-label="A seal drawn from your numbers; it changes as you progress"></canvas><span>Changes as you progress</span></div>
  </div>
  <div class="mrzband"><div class="gut"><div class="mrz" id="mrz"></div></div></div>
</header>
<div class="perf" aria-hidden="true"></div>
<main class="gut">
  <p class="notice" id="notice" hidden>Showing the example profile. Run <code>jobagent init</code> and fill in your details.</p>
  <section><div class="head"><h2>The route</h2><span class="meta" id="routemeta"></span></div>
    <div class="sheet"><ol class="route" id="route"></ol></div></section>
  <div class="split">
    <section><div class="head"><h2>Today</h2><span class="meta" id="todometa"></span></div><div class="sheet"><ol class="todo" id="todo"></ol></div></section>
    <section><div class="head"><h2>Notes from your agent</h2></div><div class="sheet pad"><ul class="notes" id="notes"></ul></div></section>
  </div>
  <section><div class="head"><h2>Shortlist</h2><div class="filters"><span class="filters" id="sectors"></span>
      <input type="search" id="q" placeholder="Title, company or skill" aria-label="Filter the shortlist"><span class="meta" id="jobcount"></span></div></div>
    <div class="sheet" id="jobs"></div></section>
  <section><div class="head"><h2>Stamps</h2><span class="meta" id="stampmeta"></span></div>
    <div class="sheet"><div class="stamps" id="stamps"></div></div></section>
  <div class="split">
    <section><div class="head"><h2>What's working</h2></div><div class="sheet pad" id="learn"></div></section>
    <section><div class="head"><h2>Filtered out for you</h2><span class="meta" id="blockmeta"></span></div><div class="sheet pad"><div class="bars" id="blockers"></div></div></section>
  </div>
  <div class="quad">
    <section><div class="head"><h2>Skills that open doors</h2></div><div class="sheet pad" id="gaps"></div></section>
    <section><div class="head"><h2>Job sources</h2></div><div class="sheet pad"><div class="rows" id="health"></div></div></section>
    <section><div class="head"><h2>Visa routes</h2></div><div class="sheet pad"><div class="rows" id="routes"></div></div></section>
    <section><div class="head"><h2>Sponsor radar</h2></div><div class="sheet pad" id="radar"></div></section>
  </div>
  <p class="colophon" id="colophon"></p>
</main>
"""
