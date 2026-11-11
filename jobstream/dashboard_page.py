"""The dashboard's look: a restrained product UI, in the manner of modern fintech dashboards.

Principles
  - Type: the platform's own UI face. San Francisco on Apple devices, Inter (its closest
    open relative) elsewhere, with tabular figures wherever numbers line up.
  - Colour: neutral surfaces, hairline borders, soft shadows. Colour is reserved for meaning
    (status badges, always with a word), and near-black ink is the primary action colour.
  - Layout: an app shell. A sidebar switches between five views (Overview, Shortlist,
    Applications, Insights, System); on a phone it becomes a top bar with scrolling tabs.
  - Data: real tables that sort and filter; one metric strip; thin single-series bars.
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">')

CSS = r"""
:root{
  --bg:#f6f7f9; --surface:#ffffff; --surface-2:#f9fafb; --hover:#f3f4f6; --border:#e4e7ec; --border-strong:#d0d5dd;
  --text:#0f1728; --text-2:#475467; --text-3:#667085; --ink:#0f1728; --on-ink:#ffffff; --accent:#2450d6;
  --green:#067647; --green-bg:#ecfdf3; --green-bd:#abefc6;
  --amber:#b54708; --amber-bg:#fffaeb; --amber-bd:#fedf89;
  --red:#b42318; --red-bg:#fef3f2; --red-bd:#fecdca;
  --blue:#175cd3; --blue-bg:#eff8ff; --blue-bd:#b2ddff;
  --grey:#344054; --grey-bg:#f2f4f7; --grey-bd:#e4e7ec;
  --shadow:0 1px 2px rgba(16,24,40,.05),0 1px 3px rgba(16,24,40,.04);
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","SF Pro Display","Inter","Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#0b0d12; --surface:#12151c; --surface-2:#171b24; --hover:#1b202b; --border:#222836; --border-strong:#2f3747;
  --text:#f2f4f7; --text-2:#b6bdc9; --text-3:#8d96a7; --ink:#f2f4f7; --on-ink:#0b0d12; --accent:#8aa6ff;
  --green:#6ce9a6; --green-bg:#0d2a1d; --green-bd:#17462f; --amber:#fdb022; --amber-bg:#2b1f07; --amber-bd:#4a3510;
  --red:#fda29b; --red-bg:#2d1210; --red-bd:#55201b; --blue:#84caff; --blue-bg:#0c2238; --blue-bd:#16385c;
  --grey:#cdd3dd; --grey-bg:#1b202b; --grey-bd:#2a3140; --shadow:0 1px 2px rgba(0,0,0,.4); color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0b0d12; --surface:#12151c; --surface-2:#171b24; --hover:#1b202b; --border:#222836; --border-strong:#2f3747;
  --text:#f2f4f7; --text-2:#b6bdc9; --text-3:#8d96a7; --ink:#f2f4f7; --on-ink:#0b0d12; --accent:#8aa6ff;
  --green:#6ce9a6; --green-bg:#0d2a1d; --green-bd:#17462f; --amber:#fdb022; --amber-bg:#2b1f07; --amber-bd:#4a3510;
  --red:#fda29b; --red-bg:#2d1210; --red-bd:#55201b; --blue:#84caff; --blue-bg:#0c2238; --blue-bd:#16385c;
  --grey:#cdd3dd; --grey-bg:#1b202b; --grey-bd:#2a3140; --shadow:0 1px 2px rgba(0,0,0,.4); color-scheme:dark}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.45;letter-spacing:-.006em;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;font-feature-settings:"cv11","calt"}
h1,h2,h3,p,ul,ol,dl,dd{margin:0;padding:0}ul,ol{list-style:none}
a{color:inherit}button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
.tn{font-variant-numeric:tabular-nums}

/* ---------- shell */
.app{display:grid;grid-template-columns:236px minmax(0,1fr);min-height:100%}
.side{border-right:1px solid var(--border);padding:20px 12px 16px;display:flex;flex-direction:column;gap:20px;position:sticky;top:0;height:100vh;
  padding-left:max(12px,env(safe-area-inset-left,0px))}
.brand{display:flex;align-items:center;gap:10px;padding:0 8px;font-weight:600;font-size:15px;letter-spacing:-.015em}
.logo{width:28px;height:28px;border-radius:8px;background:var(--ink);color:var(--on-ink);display:grid;place-items:center;font-size:14px;font-weight:700;flex:none}
.nav{display:grid;gap:2px}
.nav a{display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:8px;text-decoration:none;color:var(--text-2);font-weight:500}
.nav a:hover{background:var(--hover);color:var(--text)}
.nav a[aria-current="page"]{background:var(--surface);color:var(--text);font-weight:600;box-shadow:var(--shadow)}
.nav svg{width:16px;height:16px;flex:none;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
.nav .ct{margin-left:auto;font-size:12px;color:var(--text-3);font-variant-numeric:tabular-nums}
.side-foot{margin-top:auto;padding:12px 8px 0;border-top:1px solid var(--border);font-size:12px;color:var(--text-3);display:grid;gap:4px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:7px;vertical-align:1px}
.dot.warn{background:var(--amber)}.dot.broken{background:var(--red)}.dot.new{background:var(--text-3)}
main{min-width:0;padding:28px 32px 64px;padding-right:max(32px,env(safe-area-inset-right,0px))}
.view{max-width:1060px;margin:0 auto;display:grid;gap:20px}
.view[hidden]{display:none}
@media (max-width:900px){
  .app{display:block}
  .side{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;height:auto;flex-direction:column;gap:10px;border-right:0;border-bottom:1px solid var(--border);
    background:var(--bg);padding:12px 0 0}
  body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
  .brand{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
  .nav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;padding:0 max(12px,env(safe-area-inset-right,0px)) 0 max(12px,env(safe-area-inset-left,0px))}
  .nav::-webkit-scrollbar{display:none}
  .nav a{white-space:nowrap;padding:8px 10px;border-radius:0;border-bottom:2px solid transparent}
  .nav a[aria-current="page"]{background:none;box-shadow:none;border-bottom-color:var(--ink)}
  .nav a:hover{background:none}.nav svg{display:none}.nav .ct{margin-left:4px}
  .side-foot{display:none}
  main{padding:20px 0 56px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
}

/* ---------- page header */
.ph{display:flex;justify-content:space-between;align-items:flex-end;gap:12px 16px;flex-wrap:wrap}
h1{font-size:24px;line-height:1.2;font-weight:700;letter-spacing:-.022em}
.ph p{color:var(--text-2);margin-top:4px}
.notice{border:1px solid var(--amber-bd);background:var(--amber-bg);color:var(--amber);border-radius:10px;padding:10px 14px;font-size:13px}

/* ---------- cards */
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);min-width:0}
.ch{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;padding:14px 16px 12px}
h2{font-size:15px;font-weight:600;letter-spacing:-.012em}
.ch span{font-size:12px;color:var(--text-3)}
.cb{padding:0 16px 16px}
.cols{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:20px;align-items:start}
.cols.even{grid-template-columns:repeat(2,minmax(0,1fr))}
.stack{display:grid;gap:20px;min-width:0}
@media (max-width:1040px){.cols,.cols.even{grid-template-columns:minmax(0,1fr)}}
.empty{color:var(--text-3);padding:4px 16px 18px}
.cb .empty{padding:0}

/* ---------- metric strip */
.metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr))}
.metric{padding:16px;border-left:1px solid var(--border);min-width:0}
.metric:first-child{border-left:0}
.metric dt{font-size:12px;font-weight:500;color:var(--text-2)}
.metric dd{font-size:28px;line-height:1.15;font-weight:600;letter-spacing:-.025em;margin-top:6px;font-variant-numeric:tabular-nums}
.metric small{display:block;font-size:12px;color:var(--text-3);margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (max-width:760px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
  .metric{border-left:0;border-top:1px solid var(--border)}.metric:nth-child(-n+2){border-top:0}.metric:nth-child(even){border-left:1px solid var(--border)}
  .metric:last-child:nth-child(odd){grid-column:1/-1}}

/* ---------- badges, buttons */
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:500;line-height:18px;padding:1px 8px;border-radius:6px;border:1px solid var(--bd);
  background:var(--bgc);color:var(--fg);white-space:nowrap}
.b-green{--fg:var(--green);--bgc:var(--green-bg);--bd:var(--green-bd)}.b-amber{--fg:var(--amber);--bgc:var(--amber-bg);--bd:var(--amber-bd)}
.b-red{--fg:var(--red);--bgc:var(--red-bg);--bd:var(--red-bd)}.b-blue{--fg:var(--blue);--bgc:var(--blue-bg);--bd:var(--blue-bd)}
.b-grey{--fg:var(--grey);--bgc:var(--grey-bg);--bd:var(--grey-bd)}
.cmd{display:inline-flex;align-items:center;gap:7px;max-width:100%;background:var(--surface);border:1px solid var(--border-strong);border-radius:8px;
  padding:5px 9px;font-family:var(--mono);font-size:12px;letter-spacing:0;color:var(--text-2);cursor:pointer;box-shadow:0 1px 2px rgba(16,24,40,.05);text-align:left}
.cmd span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.cmd svg{width:13px;height:13px;flex:none;stroke:currentColor;fill:none;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round;opacity:.7}
.cmd:hover{background:var(--hover);color:var(--text)}
.cmd.done{border-color:var(--green-bd);color:var(--green)}
code{font-family:var(--mono);font-size:.9em;background:var(--grey-bg);border-radius:4px;padding:1px 5px;overflow-wrap:anywhere;letter-spacing:0}

/* ---------- lists */
.list>li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:center;padding:12px 16px;border-top:1px solid var(--border)}
.list .t{display:grid;gap:5px;justify-items:start;min-width:0}
.list .t a{text-decoration:none}.list .t a:hover{text-decoration:underline;text-underline-offset:3px}
.list p{color:var(--text)}
@media (max-width:620px){.list>li{grid-template-columns:minmax(0,1fr)}}
.notes>li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px;align-items:start;padding:12px 16px;border-top:1px solid var(--border)}
.notes b{font-weight:600}.notes p{color:var(--text-2)}
.notes .badge{margin-top:1px;min-width:74px;justify-content:center}
@media (max-width:520px){.notes>li{grid-template-columns:minmax(0,1fr)}.notes .badge{justify-self:start}}

/* ---------- funnel + bars */
.funnel{display:grid}
.frow{display:grid;grid-template-columns:104px 52px minmax(0,1fr);gap:12px;align-items:center;padding:9px 16px;border-top:1px solid var(--border)}
.frow .n{font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.frow .w{display:grid;gap:4px;min-width:0}
.frow small{font-size:12px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{height:6px;background:var(--grey-bg);border-radius:0 4px 4px 0;overflow:hidden}
.fill{height:100%;background:var(--ink);border-radius:0 4px 4px 0;min-width:2px}
.fill.soft{background:var(--text-3)}
.bars{display:grid;gap:10px}
.bar{display:grid;grid-template-columns:minmax(0,170px) minmax(0,1fr) 44px;gap:12px;align-items:center}
.bar .v{text-align:right;color:var(--text-2);font-variant-numeric:tabular-nums;font-size:13px}
.bar:hover .fill{background:var(--accent)}
.sub{font-size:12px;font-weight:500;color:var(--text-3);margin:16px 0 10px}
.sub:first-child{margin-top:0}
.cap{font-size:12px;color:var(--text-3);margin-top:12px}
.finding{color:var(--text-2);margin-bottom:8px}

/* ---------- toolbar + table */
.tools{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;min-width:0}
.tools>*{min-width:0}
.seg{display:flex;flex:0 1 auto;background:var(--grey-bg);border-radius:9px;padding:2px;gap:2px;max-width:100%;overflow-x:auto;scrollbar-width:none}
.seg::-webkit-scrollbar{display:none}
.seg button{border:0;background:transparent;border-radius:7px;padding:5px 12px;font-size:13px;font-weight:500;color:var(--text-2);cursor:pointer;white-space:nowrap}
.seg button[aria-pressed="true"]{background:var(--surface);color:var(--text);box-shadow:0 1px 2px rgba(16,24,40,.1)}
.seg .ct{color:var(--text-3);margin-left:5px;font-variant-numeric:tabular-nums}
.search{position:relative;flex:0 1 260px;min-width:160px}
.search svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);width:15px;height:15px;stroke:var(--text-3);fill:none;stroke-width:1.6;stroke-linecap:round}
.search input{width:100%;font:inherit;color:var(--text);background:var(--surface);border:1px solid var(--border-strong);border-radius:8px;padding:7px 10px 7px 32px;box-shadow:0 1px 2px rgba(16,24,40,.05)}
.search input::placeholder{color:var(--text-3)}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;table-layout:fixed}
col.w-sp{width:150px}col.w-sal{width:118px}col.w-post{width:88px}col.w-score{width:84px}col.w-st{width:112px}col.w-cmd{width:290px}
col.w-when{width:120px}col.w-next{width:230px}
th{font-size:12px;font-weight:500;color:var(--text-3);text-align:left;padding:10px 16px;background:var(--surface-2);border-bottom:1px solid var(--border);white-space:nowrap}
th:first-child{border-top-left-radius:12px}th:last-child{border-top-right-radius:12px}
th button{border:0;background:none;padding:0;font-size:12px;font-weight:500;color:inherit;cursor:pointer;display:inline-flex;gap:4px;align-items:center}
th button:hover{color:var(--text)}th[aria-sort] button{color:var(--text)}
td{padding:12px 16px;border-top:1px solid var(--border);vertical-align:middle}
tbody tr:first-child td{border-top:0}
tbody tr:hover td{background:var(--surface-2)}
.r{text-align:right}th.r button{flex-direction:row-reverse}
.role{min-width:0}
.role>div{overflow:hidden;text-overflow:ellipsis}.role .m,.role .x{white-space:nowrap}
.role a{font-weight:600;text-decoration:none;letter-spacing:-.01em}.role a:hover{text-decoration:underline;text-underline-offset:3px}
.role .m{color:var(--text-2);font-size:13px;margin-top:2px}
.role .x{color:var(--text-3);font-size:12px;margin-top:3px}
.role .flag{color:var(--amber)}
.score{display:inline-grid;gap:4px;justify-items:end}
.score b{font-weight:600;font-variant-numeric:tabular-nums}
.score .track{width:52px;height:4px;border-radius:2px}.score .fill{border-radius:2px}
.muted{color:var(--text-3)}.nowrap{white-space:nowrap}
.more{display:block;width:100%;border:0;border-top:1px solid var(--border);background:none;padding:12px 16px;text-align:center;font-weight:500;color:var(--text-2);cursor:pointer;border-radius:0 0 12px 12px}
.more:hover{background:var(--surface-2);color:var(--text)}
.more[hidden]{display:none}
.only-m{display:none}
@media (max-width:1180px){.hide-m{display:none}.only-m{display:inline-flex;vertical-align:1px;margin-left:2px}col.w-post,col.w-st,col.w-next{width:0;visibility:collapse}}
@media (max-width:760px){
  table{table-layout:auto}colgroup{display:none}
  thead{display:none}
  tbody tr{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 12px;padding:14px 16px;border-top:1px solid var(--border)}
  tbody tr:first-child{border-top:0}
  td{display:block;padding:0;border:0}tbody tr:hover td{background:none}
  td.role{grid-column:1/-1;min-width:0}td.hide-s,td.hide-m{display:none}td.r{text-align:left}
  .role .m,.role .x{white-space:normal}
  td.full{grid-column:1/-1}.score{justify-items:start;grid-auto-flow:column;align-items:center;gap:8px}
}

/* ---------- key/value rows */
.kv>div{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 16px;align-items:center;padding:11px 16px;border-top:1px solid var(--border)}
.kv .d{grid-column:1/-1;font-size:12px;color:var(--text-3)}
.kv .rt{display:flex;gap:12px;align-items:center;color:var(--text-2);font-size:13px;font-variant-numeric:tabular-nums}
.kv a{text-decoration:none;font-weight:500}.kv a:hover{text-decoration:underline;text-underline-offset:3px}
.big{font-size:28px;font-weight:600;letter-spacing:-.025em;line-height:1.15;font-variant-numeric:tabular-nums}
.foot{font-size:12px;color:var(--text-3)}
/* ---------- action buttons (live dashboard) */
.acts{display:inline-flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;max-width:100%}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;height:30px;padding:0 11px;border-radius:8px;border:1px solid var(--border-strong);
  background:var(--surface);color:var(--text);font-size:13px;font-weight:500;cursor:pointer;white-space:nowrap;box-shadow:0 1px 2px rgba(16,24,40,.05);text-decoration:none}
.btn:hover{background:var(--hover)}
.btn.primary{background:var(--ink);border-color:var(--ink);color:var(--on-ink)}
.btn.primary:hover{opacity:.88;background:var(--ink)}
.btn.quiet{border-color:transparent;box-shadow:none;color:var(--text-2)}
.btn.quiet:hover{color:var(--text);background:var(--hover)}
.btn[disabled]{opacity:.55;cursor:progress}
.btn .spin{width:12px;height:12px;border-radius:50%;border:2px solid currentColor;border-right-color:transparent;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.btn .spin{animation:none}}
@media (max-width:760px){.acts{justify-content:flex-start}}
.needs>li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:center;padding:12px 16px;border-top:1px solid var(--border)}
.needs .t{display:grid;gap:3px;min-width:0}
.needs b{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.needs .why{grid-column:1/-1;color:var(--amber);font-size:13px;margin-top:-2px}
.needs .m{color:var(--text-2);font-size:13px}
@media (max-width:620px){.needs>li{grid-template-columns:minmax(0,1fr)}.needs .acts{justify-content:flex-start}}
.toasts{position:fixed;right:max(16px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px));display:grid;gap:8px;z-index:50;
  width:min(380px,calc(100vw - 32px))}
.toast{background:var(--surface);border:1px solid var(--border-strong);border-radius:12px;box-shadow:0 8px 24px rgba(16,24,40,.12);padding:12px 14px;
  display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 10px;align-items:start;font-size:13px}
.toast .ic{margin-top:3px}.toast b{font-weight:600}.toast p{color:var(--text-2);grid-column:2}
.toast .ic.spin{width:12px;height:12px;border-radius:50%;border:2px solid var(--text-3);border-right-color:transparent;animation:spin .8s linear infinite}
.toast .ic.ok{width:8px;height:8px;border-radius:50%;background:var(--green);margin:5px 2px 0}
.toast .ic.warn{width:8px;height:8px;border-radius:50%;background:var(--amber);margin:5px 2px 0}
.toast .ic.bad{width:8px;height:8px;border-radius:50%;background:var(--red);margin:5px 2px 0}
.livepill{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--text-3)}
"""

JS = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s, r=document) => r.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const c = D.counts, n = k => c[k] || 0;
const num = v => Number(v).toLocaleString('en-GB');
const safeUrl = u => (typeof u === 'string' && /^https?:\/\//.test(u)) ? u : null;
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const day = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ''); return m ? (+m[3]) + ' ' + MON[+m[2]-1] : ''; };
const money = j => (j.salary_min || j.salary_max) ? '£' + Math.round((j.salary_min || j.salary_max)/1000) + 'k – £' + Math.round((j.salary_max || j.salary_min)/1000) + 'k' : '';
const short = uid => { const id = String(uid).split(':').pop(); return id.length > 12 ? id.slice(0, 8) : id; };

// ---------- live actions (only when the dashboard is served by `jobstream dashboard`)
const LIVE = D.live;
const tracked = new Map();
let polling = null;
function toastBox(){ let b = $('#toasts'); if (!b) { b = el('div', 'toasts'); b.id = 'toasts'; b.setAttribute('role', 'status'); b.setAttribute('aria-live', 'polite'); document.body.append(b); } return b; }
function toast(title, detail, kind, id){
  const box = toastBox(); let t = id != null ? box.querySelector('[data-id="' + id + '"]') : null;
  if (!t) { t = el('div', 'toast'); if (id != null) t.dataset.id = id; box.append(t); }
  t.textContent = ''; t.append(el('i', 'ic ' + kind), el('b', null, title)); if (detail) t.append(el('p', null, detail));
  if (kind !== 'spin') setTimeout(() => t.remove(), kind === 'ok' ? 5000 : 12000);
}
async function call(action, uid, value){
  const r = await fetch(LIVE.api + '/' + action, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-JobStream': LIVE.csrf},
                                                  body: JSON.stringify({uid, value: value || ''})});
  let data = {}; try { data = await r.json(); } catch (e) {}
  if (!r.ok || !data.ok) throw new Error(data.error || ('Error ' + r.status));
  return data;
}
const VERB = {apply: 'Applying', pack: 'Building the pack', interview: 'Building interview prep'};
function track(task){ tracked.set(task.id, task); toast(VERB[task.action] + '…', task.label, 'spin', task.id); if (!polling) polling = setInterval(poll, 2500); }
async function poll(){
  let data; try { const r = await fetch(LIVE.api + '/tasks', {headers: {'X-JobStream': LIVE.csrf}}); data = await r.json(); } catch (e) { return; }
  let finished = 0;
  (data.tasks || []).forEach(t => {
    if (!tracked.has(t.id) && (t.state === 'queued' || t.state === 'running')) { track(t); return; }
    if (!tracked.has(t.id) || t.state === 'queued' || t.state === 'running') return;
    tracked.delete(t.id); finished++;
    const good = t.state === 'done' && !/^Not sent/.test(t.result);
    toast(t.state === 'failed' ? 'Something went wrong' : t.result, t.label + (t.state === 'failed' ? ': ' + t.result : ''), t.state === 'failed' ? 'bad' : good ? 'ok' : 'warn', t.id);
  });
  if (!tracked.size) { if (polling) clearInterval(polling); polling = null; if (finished) setTimeout(() => location.reload(), 2500); }
}
function act(label, cls, fn, title){
  const b = el('button', 'btn' + (cls ? ' ' + cls : ''), label); b.type = 'button'; if (title) b.title = title;
  b.addEventListener('click', async () => { b.disabled = true; const keep = b.textContent; b.textContent = ''; b.append(el('i', 'spin'), document.createTextNode(keep));
    try { await fn(); } catch (e) { toast("Couldn't do that", e.message, 'bad'); } finally { b.disabled = false; b.textContent = keep; } });
  return b;
}
function linkBtn(label, url, cls){ const u = safeUrl(url); if (!u) return null; const a = el('a', 'btn' + (cls ? ' ' + cls : ''), label); a.href = u; a.target = '_blank'; a.rel = 'noopener'; return a; }
async function quick(action, uid, value, reload){ const d = await call(action, uid, value); if (d.task) { track(d.task); return; }
  toast(d.message || 'Done', null, 'ok'); if (reload !== false) setTimeout(() => location.reload(), 900); }
function applyNow(j, force){ return () => { if (!confirm('Apply to ' + j.title + ' at ' + j.company + ' now?\n\nJobStream tailors your CV and cover letter, fills in the form and sends it. ' +
                                                  'It stops without sending if the site needs a login, has a CAPTCHA, or asks something it can\'t answer truthfully.')) return Promise.resolve();
                                     return quick('apply', j.uid, force ? 'force' : ''); }; }
function jobButtons(j){
  const w = el('div', 'acts');
  w.append(act('Apply', 'primary', applyNow(j), 'Fill in and send the application'));
  if (j.status === 'packed' && LIVE.local) w.append(act('Open pack', '', () => quick('open_pack', j.uid, '', false), 'Open the folder with the CV and cover letter'));
  else if (j.status !== 'packed') w.append(act('Pack', '', () => quick('pack', j.uid), 'Build the CV, cover letter and answers without sending'));
  w.append(act('Skip', 'quiet', () => confirm('Skip ' + j.title + ' at ' + j.company + '? It leaves your shortlist.') ? quick('skip', j.uid) : null));
  return w;
}
function appButtons(j){
  const w = el('div', 'acts');
  if (j.status === 'applied') { w.append(act('Interview', '', () => quick('status', j.uid, 'interview'), 'Got an interview: builds your prep pack'),
                                         act('Rejected', 'quiet', () => quick('status', j.uid, 'rejected'))); }
  else if (j.status === 'interview') { w.append(act('Offer', '', () => quick('status', j.uid, 'offer')), act('Rejected', 'quiet', () => quick('status', j.uid, 'rejected'))); }
  if (LIVE.local) w.append(act('Pack', 'quiet', () => quick('open_pack', j.uid, '', false), 'Open the application pack'));
  return w;
}
const NS = 'http://www.w3.org/2000/svg';
function icon(paths){ const s = document.createElementNS(NS, 'svg'); s.setAttribute('viewBox', '0 0 16 16'); s.setAttribute('aria-hidden', 'true');
  paths.forEach(d => { const p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); s.append(p); }); return s; }
const IC = {
  overview: ['M2.5 7 8 2.5 13.5 7v6a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5z', 'M6.5 13.5v-4h3v4'],
  shortlist: ['M3 4h10', 'M3 8h10', 'M3 12h6'],
  applications: ['M14 2 7.5 8.5', 'M14 2 9.5 14l-2-5.5L2 6.5z'],
  insights: ['M2.5 13.5h11', 'M4.5 11V8', 'M8 11V4', 'M11.5 11V6.5'],
  system: ['M3 3.5h10v4H3z', 'M3 8.5h10v4H3z', 'M5.5 5.5h.01', 'M5.5 10.5h.01'],
  copy: ['M5.5 5.5h7v7h-7z', 'M3.5 10.5v-7h7'],
};
function rich(text){ const f = document.createDocumentFragment();
  String(text).split('`').forEach((part, i) => f.append(i % 2 ? el('code', null, part) : document.createTextNode(part))); return f; }
function badge(text, tone){ return el('span', 'badge b-' + tone, text); }
function cmd(text){
  const b = el('button', 'cmd'); b.type = 'button'; b.title = 'Copy command'; const label = el('span', null, text); b.append(icon(IC.copy), label);
  b.addEventListener('click', () => {
    const ok = () => { b.classList.add('done'); label.textContent = 'Copied'; setTimeout(() => { label.textContent = text; b.classList.remove('done'); }, 1200); };
    const fallback = () => { const r = document.createRange(); r.selectNodeContents(label); const s = getSelection(); s.removeAllRanges(); s.addRange(r); };
    try { navigator.clipboard.writeText(text).then(ok, fallback); } catch (e) { fallback(); }
  });
  return b;
}
function link(text, url){ const u = safeUrl(url); if (!u) return el('span', null, text); const a = el('a', null, text); a.href = u; a.target = '_blank'; a.rel = 'noopener'; return a; }
function bar(label, value, max, right, tip, soft){
  const row = el('div', 'bar'); if (tip) row.title = tip; row.append(el('span', null, label));
  const t = el('div', 'track'), f = el('div', 'fill' + (soft ? ' soft' : '')); f.style.width = (max ? 100 * value / max : 0) + '%'; t.append(f);
  row.append(t, el('span', 'v', right != null ? right : String(value))); return row;
}
const apps = D.applications, sent = apps.length, closed = n('rejected') + n('withdrawn');

// ---------- shell: brand, navigation, views
$('#brand').textContent = D.title; $('#logo').textContent = (D.title.trim()[0] || 'J').toUpperCase();
const VIEWS = [['overview', 'Overview', D.todo.length || ''], ['shortlist', 'Shortlist', D.shortlist.length || ''], ['applications', 'Applications', sent || ''],
  ['insights', 'Insights', ''], ['system', 'System', '']];
const NAV = $('#nav');
VIEWS.forEach(([id, label, ct]) => { const a = el('a'); a.href = '#' + id; a.dataset.view = id; a.append(icon(IC[id]), el('span', null, label)); if (ct !== '') a.append(el('span', 'ct', String(ct))); NAV.append(a); });
function show(){
  const want = (location.hash || '').slice(1), id = VIEWS.some(v => v[0] === want) ? want : 'overview';
  VIEWS.forEach(([v]) => { $('#v-' + v).hidden = v !== id; });
  [...NAV.children].forEach(a => a.dataset.view === id ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'));
  document.title = VIEWS.find(v => v[0] === id)[1] + ' · ' + D.title;
  const cur = NAV.querySelector('[aria-current]'); if (cur && cur.scrollIntoView && NAV.scrollWidth > NAV.clientWidth) cur.scrollIntoView({block: 'nearest', inline: 'center'});
}
window.addEventListener('hashchange', () => { show(); window.scrollTo(0, 0); });
const worst = D.health.some(s => s.state === 'broken') ? 'broken' : D.health.some(s => s.state === 'warn') ? 'warn' : D.health.length ? 'ok' : 'new';
const healthText = {broken: D.health.filter(s => s.state === 'broken').length + ' source(s) not working', warn: 'A source needs checking', ok: 'All sources working', new: 'No searches yet'}[worst];
{ const f = $('#sidefoot'), l = el('div'); l.append(el('i', 'dot ' + (worst === 'ok' ? '' : worst)), document.createTextNode(healthText)); f.append(l, el('div', null, D.last_run ? 'Last search ' + day(D.last_run) + ', ' + D.last_run.slice(11, 16) + ' UTC' : 'Not searched yet')); }

// ---------- overview
$('#ov-sub').textContent = D.generated.replace(/,.*/, '') + (D.last_run ? ' · last search ' + D.last_run.slice(11, 16) + ' UTC' : '');
$('#ov-health').append(badge(healthText, {broken: 'red', warn: 'amber', ok: 'green', new: 'grey'}[worst]));
if (D.example) $('#notice').hidden = false;
const decided = (n('interview') + n('offer')) + closed;
[['New today', n('new_today'), num(D.found) + ' found in total'], ['Shortlisted', n('shortlisted') + n('packed'), n('packed') + ' packs ready to send'],
 ['Applied', sent, n('applied') + ' awaiting a reply'], ['Interviews', n('interview') + n('offer'), decided ? Math.round(100 * (n('interview') + n('offer')) / sent) + '% of applications' : 'none yet'],
 ['Offers', n('offer'), n('offer') ? 'Congratulations' : (closed ? closed + ' closed' : 'none yet')]]
 .forEach(([k, v, s]) => { const d = el('div', 'metric'); d.append(el('dt', null, k), el('dd', null, num(v)), el('small', null, s)); $('#metrics').append(d); });

const T = $('#todo'), KIND = {apply: ['Apply', 'blue'], follow: ['Follow up', 'amber'], interview: ['Interview', 'green'], send: ['Send', 'grey']};
$('#todo-ct').textContent = D.todo.length ? D.todo.length + ' to do' : '';
if (!D.todo.length) T.replaceWith(el('p', 'empty', 'Nothing urgent. Run “jobstream watch” to check for fresh jobs.'));
D.todo.forEach(t => { const li = el('li'), w = el('div', 't'), k = KIND[t.kind] || [t.kind, 'grey'];
  const p = el('p'); p.append(link(t.text.replace(/^(Apply today|Follow up|Interview): /, ''), t.url)); w.append(badge(k[0], k[1]), p);
  const job = LIVE && t.uid ? D.shortlist.find(j => j.uid === t.uid) : null;
  li.append(w, job ? act('Apply', 'primary', applyNow(job)) : LIVE && t.kind === 'apply' && !t.uid ? el('span', 'muted', 'Use Apply on the Shortlist') : cmd(t.cmd)); T.append(li); });

const reach = [['Found', D.found], ['Shortlisted', n('shortlisted') + n('packed') + sent], ['Applied', sent], ['Interview', n('interview') + n('offer')], ['Offer', n('offer')]];
reach.forEach(([label, v], i) => { const row = el('div', 'frow'), prev = i ? reach[i - 1][1] : 0, rate = i && prev ? v / prev : (i ? 0 : 1);
  const w = el('div', 'w'), t = el('div', 'track'), f = el('div', 'fill'); f.style.width = (100 * rate) + '%'; t.append(f);
  w.append(t, el('small', null, i ? (prev ? Math.round(100 * rate) + '% of ' + reach[i - 1][0].toLowerCase() : '–') : 'every relevant job seen'));
  row.title = label + ': ' + num(v); row.append(el('span', null, label), el('span', 'n', num(v)), w); $('#funnel').append(row); });

const N = $('#notes'), PR = {1: ['Action', 'red'], 2: ['This week', 'amber'], 3: ['FYI', 'grey']};
if (!D.insights.length) N.replaceWith(el('p', 'empty', 'No notes right now.'));
D.insights.forEach(i => { const li = el('li'), d = el('div'), p = el('p'); p.append(rich(i.detail)); d.append(el('b', null, i.title), p); li.append(badge(PR[i.p][0], PR[i.p][1]), d); N.append(li); });

const B = $('#blockers'), bl = Object.entries(D.blockers).filter(([, v]) => v), bmax = Math.max(1, ...bl.map(([, v]) => v));
bl.forEach(([k, v]) => B.append(bar(k, v, bmax, num(v), v + ' jobs', true)));
if (!bl.length) B.append(el('p', 'empty', 'Nothing filtered out yet.'));
$('#block-ct').textContent = bl.length ? num(bl.reduce((t, [, v]) => t + v, 0)) + ' jobs' : '';

// ---------- shortlist
const SECT = {tech: 'Tech', nhs: 'NHS', university: 'University', corporate: 'Corporate'};
let sector = 'all', query = '', limit = 15, sortKey = 'score', sortDir = -1;
const val = { score: j => j.fit != null ? j.fit : (j.score || 0), salary: j => j.salary_max || j.salary_min || 0, posted: j => j.posted_days == null ? 9999 : j.posted_days };
const SEG = $('#sl-seg'), present = ['all', ...Object.keys(SECT).filter(s => D.shortlist.some(j => j.sector === s))];
present.forEach(s => { const b = el('button', null, s === 'all' ? 'All' : SECT[s]); b.type = 'button'; b.append(el('span', 'ct', String(s === 'all' ? D.shortlist.length : D.shortlist.filter(j => j.sector === s).length)));
  b.setAttribute('aria-pressed', String(s === sector)); b.addEventListener('click', () => { sector = s; limit = 15; [...SEG.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); drawJobs(); }); SEG.append(b); });
$('#q').addEventListener('input', e => { query = e.target.value.toLowerCase(); limit = 15; drawJobs(); });
document.querySelectorAll('#sl-table th[data-sort]').forEach(th => { const b = th.querySelector('button'); b.addEventListener('click', () => {
  const k = th.dataset.sort; if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === 'posted' ? 1 : -1; } drawJobs(); }); });
function drawJobs(){
  document.querySelectorAll('#sl-table th[data-sort]').forEach(th => { const on = th.dataset.sort === sortKey;
    on ? th.setAttribute('aria-sort', sortDir < 0 ? 'descending' : 'ascending') : th.removeAttribute('aria-sort'); th.querySelector('i').textContent = on ? (sortDir < 0 ? '↓' : '↑') : ''; });
  const body = $('#sl-body'); body.textContent = '';
  const rows = D.shortlist.filter(j => (sector === 'all' || j.sector === sector) && (!query || (j.title + ' ' + j.company + ' ' + j.matched.join(' ')).toLowerCase().includes(query)))
    .sort((a, b) => sortDir * (val[sortKey](a) - val[sortKey](b)));
  $('#sl-sub').textContent = rows.length + (rows.length === 1 ? ' job' : ' jobs') + ' at employers that can sponsor you, best match first';
  $('#sl-empty').hidden = rows.length > 0; $('#sl-empty').textContent = D.shortlist.length ? 'No jobs match that filter.' : 'No jobs yet. Run “jobstream run” to search.';
  rows.slice(0, limit).forEach(j => { const tr = el('tr');
    const role = el('td', 'role'), t = el('div'); t.append(link(j.title, j.url)); role.append(t, el('div', 'm', [j.company, SECT[j.sector] || j.sector, j.location].filter(Boolean).join(' · ')));
    role.title = [j.company, j.location].filter(Boolean).join(' · ');
    if (j.flag) role.append(el('div', 'x flag', 'Watch out: ' + j.flag)); else if (j.why) role.append(el('div', 'x', j.why)); else if (j.matched.length) role.append(el('div', 'x', 'Matches ' + j.matched.slice(0, 5).join(', ')));
    const sp = el('td'); sp.append(j.scaleup ? badge('Scale-up sponsor', 'blue') : j.sponsor ? badge('Licensed sponsor', 'green') : badge('Not confirmed', 'amber'));
    const sal = el('td', 'nowrap tn', money(j) || '–'); if (!money(j)) sal.classList.add('muted', 'hide-s');
    const posted = el('td', 'nowrap hide-m', j.posted_days == null ? '–' : j.posted_days === 0 ? 'Today' : j.posted_days + 'd ago'); if (j.posted_days == null) posted.classList.add('muted');
    const scv = Math.round(val.score(j)), sc = el('td', 'r'), box = el('div', 'score'), tk = el('div', 'track'), fl = el('div', 'fill'); fl.style.width = scv + '%'; tk.append(fl);
    box.append(el('b', null, String(scv)), tk); box.title = (j.fit != null ? 'Claude fit ' : 'Keyword score ') + scv + ' out of 100'; sc.append(box);
    const st = el('td', 'hide-m'); st.append(j.status === 'packed' ? badge('Pack ready', 'blue') : badge('Shortlisted', 'grey'));
    if (j.status === 'packed') { const b2 = badge('Pack ready', 'blue'); b2.classList.add('only-m'); role.querySelector('div').append(document.createTextNode(' '), b2); }
    const act = el('td', 'r full'); act.append(LIVE ? jobButtons(j) : cmd('jobstream apply ' + short(j.uid)));
    tr.append(role, sp, sal, posted, sc, st, act); body.append(tr); });
  const more = $('#sl-more'); more.hidden = rows.length <= limit; more.textContent = 'Show ' + Math.min(20, rows.length - limit) + ' more';
}
$('#sl-more').addEventListener('click', () => { limit += 20; drawJobs(); });
drawJobs();

// ---------- applications
const STATUS = {applied: ['Applied', 'blue'], interview: ['Interview', 'green'], offer: ['Offer', 'green'], rejected: ['Not selected', 'red'], withdrawn: ['Withdrawn', 'grey']};
let afilter = 'all';
const ASEG = $('#ap-seg'), groups = [['all', 'All', sent], ['applied', 'Awaiting reply', n('applied')], ['interview', 'Interview', n('interview')], ['offer', 'Offer', n('offer')], ['closed', 'Closed', closed]];
groups.forEach(([k, label, ct]) => { const b = el('button', null, label); b.type = 'button'; b.append(el('span', 'ct', String(ct))); b.setAttribute('aria-pressed', String(k === afilter));
  b.addEventListener('click', () => { afilter = k; [...ASEG.children].forEach(x => x.setAttribute('aria-pressed', String(x === b))); drawApps(); }); ASEG.append(b); });
function drawApps(){
  const body = $('#ap-body'); body.textContent = '';
  const rows = apps.filter(j => afilter === 'all' || j.status === afilter || (afilter === 'closed' && (j.status === 'rejected' || j.status === 'withdrawn')));
  $('#ap-empty').hidden = rows.length > 0; $('#ap-empty').textContent = sent ? 'Nothing in this group.' : 'No applications yet. When you apply, each one appears here with its status and next step.';
  rows.forEach(j => { const tr = el('tr'), role = el('td', 'role'), t = el('div'); t.append(link(j.title, j.url)); role.append(t, el('div', 'm', [j.company, SECT[j.sector] || j.sector].join(' · ')));
    const when = el('td', 'nowrap'); when.append(el('div', null, day(j.applied_on) || '–'), el('div', 'muted', j.applied_days == null ? '' : j.applied_days === 0 ? 'today' : j.applied_days + ' days ago'));
    const s = STATUS[j.status] || [j.status, 'grey'], st = el('td'); st.append(badge(s[0], s[1]));
    const next = el('td', 'hide-m', j.status === 'interview' ? 'Read your prep pack' : j.status === 'offer' ? 'Confirm sponsorship route and salary' : j.status === 'applied' ? (j.applied_days >= 4 ? 'Send a follow-up' : 'Wait, and send the networking messages') : '–');
    if (next.textContent === '–') next.classList.add('muted');
    const act = el('td', 'r full'); act.append(LIVE ? appButtons(j) : cmd(j.status === 'interview' ? 'jobstream prep ' + short(j.uid) : 'jobstream show ' + short(j.uid)));
    tr.append(role, when, st, next, act); body.append(tr); });
}
drawApps();
$('#ap-sub').textContent = sent ? sent + ' sent · ' + (n('interview') + n('offer')) + ' reached interview · ' + closed + ' closed' : 'Nothing sent yet';

// ---------- insights
const L = $('#learn'), le = D.learn;
if (!le.total) L.append(el('p', 'empty', 'After about 20 applications with a result, this shows where your interviews come from.'));
else { le.findings.forEach(f => L.append(el('p', 'finding', f)));
  Object.entries(le.by).forEach(([dim, gs]) => { if (!gs.some(g => g.rate != null)) return; L.append(el('p', 'sub', 'Interview rate by ' + dim.toLowerCase().replace('claude', 'Claude'))); const w = el('div', 'bars');
    gs.forEach(g => w.append(bar(g.label === g.label.toUpperCase() && g.label.length > 3 ? g.label[0] + g.label.slice(1).toLowerCase() : g.label, g.rate != null ? g.rate : 0, 1, g.rate != null ? Math.round(100 * g.rate) + '%' : 'few', g.positive + ' interviews from ' + g.decided + ' decided applications'))); L.append(w); }); }
const G = $('#gaps');
if (!D.gaps.length) G.append(el('p', 'empty', 'Shows the skills your near-miss jobs ask for, once there are enough jobs.'));
else { const gm = Math.max(...D.gaps.map(g => g.share)), w = el('div', 'bars');
  D.gaps.forEach(g => w.append(bar(g.skill + (g.status ? ' (planned)' : ''), g.share, gm, Math.round(100 * g.share) + '%', 'Asked for by ' + g.employers.join(', ') + (g.unlocks ? ' · would unlock ' + g.unlocks + ' near-miss jobs' : ''))));
  G.append(w, el('p', 'cap', 'Share of ' + D.gap_pool + ' near-match jobs asking for a skill you have not listed.')); const d = el('p'); d.style.marginTop = '12px'; d.append(cmd('jobstream grow --plan')); G.append(d); }
const B2 = $('#blockers2'); bl.forEach(([k, v]) => B2.append(bar(k, v, bmax, num(v), v + ' jobs', true))); if (!bl.length) B2.append(el('p', 'empty', 'Nothing filtered out yet.'));

// ---------- system
const H = $('#health'), STATE = {ok: ['Working', 'green'], new: ['First run', 'grey'], warn: ['Check', 'amber'], broken: ['Not working', 'red']};
if (!D.health.length) H.append(el('p', 'empty', 'No searches recorded yet.'));
D.health.forEach(s => { const r = el('div'), right = el('span', 'rt'), st = STATE[s.state] || STATE.ok;
  right.append(el('span', null, (s.boards != null ? s.boards + ' boards · ' : '') + num(s.seen) + ' postings'), badge(st[0], st[1])); r.append(el('span', null, s.name), right);
  if (s.detail && (s.state === 'broken' || s.state === 'warn')) r.append(el('span', 'd', s.detail)); H.append(r); });
const V = $('#routes'), RS = {likely: ['Likely', 'green'], possible: ['Possible', 'blue'], check: ['Worth checking', 'grey'], unlikely: ['Unlikely', 'grey'], not_eligible: ['Not eligible', 'grey']};
if (!D.routes.length) V.append(el('p', 'empty', 'Run “jobstream visa” to check which routes are open to you.'));
D.routes.forEach(r => { const d = el('div'), st = RS[r.status] || [r.status, 'grey']; d.append(link(r.name, r.link), badge(st[0], st[1])); V.append(d); });
[['Visa route', D.visa_route], ['Salary floor', '£' + num(D.threshold)], ['Licensed sponsors on the register', D.sponsor_count ? num(D.sponsor_count) : 'not loaded'],
 ['Newly licensed in the last 14 days', num(D.radar.count)], ['Company job boards searched', num(D.radar.boards)]]
 .forEach(([k, v]) => { const d = el('div'); d.append(el('span', null, k), el('span', 'rt', v)); $('#facts').append(d); });
if (D.radar.names.length) { const d = el('div'); d.append(el('span', 'd', 'New sponsors: ' + D.radar.names.join(', '))); $('#facts').append(d); }
$('#foot').textContent = LIVE ? 'Live. Updated ' + D.generated + '. Buttons work while `jobstream dashboard` is running on your computer.'
                               : 'Read-only. Generated ' + D.generated + '. Run `jobstream dashboard` for the version with buttons.';

// ---------- needs you: applications that stopped before sending
{ const NL = $('#needs'), needs = D.needs || [];
  $('#needs-card').hidden = !needs.length;
  needs.forEach(j => { const li = el('li'), t = el('div', 't'), a = j.attempt || {};
    t.append(el('b', null, j.title), el('span', 'm', j.company));
    const why = el('p', 'why', a.why ? a.why.charAt(0).toUpperCase() + a.why.slice(1) + (a.detail ? ': ' + a.detail : '') : '');
    if (LIVE) { const w = el('div', 'acts'), form = linkBtn('Open form', a.url || j.apply_url, 'primary');
      if (form) w.append(form);
      w.append(act('Mark applied', '', () => quick('applied', j.uid), 'You sent it yourself'));
      if (a.blocked !== 'agency' && a.blocked !== 'not_sponsor') w.append(act('Try again', 'quiet', applyNow(j)));
      else w.append(act('Apply anyway', 'quiet', applyNow(j, true), 'Send it although sponsorship is unconfirmed'));
      w.append(act('Dismiss', 'quiet', () => quick('dismiss', j.uid)));
      li.append(t, w, why);
    } else li.append(t, cmd('jobstream mark-applied ' + short(j.uid)), why);
    NL.append(li); }); }
if (LIVE) { $('#sl-act-h').textContent = 'Actions'; $('#ap-act-h').textContent = 'Actions'; poll(); }
show();
"""

BODY = """
<div class="app">
  <aside class="side">
    <div class="brand"><span class="logo" id="logo"></span><span id="brand"></span></div>
    <nav class="nav" id="nav" aria-label="Sections"></nav>
    <div class="side-foot" id="sidefoot"></div>
  </aside>
  <main>
    <section class="view" id="v-overview">
      <div class="ph"><div><h1>Overview</h1><p id="ov-sub"></p></div><div id="ov-health"></div></div>
      <p class="notice" id="notice" hidden>Showing the example profile. Run <code>jobstream init</code> and fill in your details.</p>
      <dl class="card metrics" id="metrics"></dl>
      <div class="cols">
        <div class="stack">
          <section class="card" id="needs-card" hidden><div class="ch"><h2>Needs you</h2><span>applications JobStream couldn't send by itself</span></div><ul class="needs" id="needs"></ul></section>
          <section class="card"><div class="ch"><h2>Today</h2><span id="todo-ct"></span></div><ul class="list" id="todo"></ul></section>
          <section class="card"><div class="ch"><h2>Notes from your agent</h2></div><ul class="notes" id="notes"></ul></section>
        </div>
        <div class="stack">
          <section class="card"><div class="ch"><h2>Pipeline</h2><span>conversion from the stage before</span></div><div class="funnel" id="funnel"></div></section>
          <section class="card"><div class="ch"><h2>Filtered out for you</h2><span id="block-ct"></span></div><div class="cb"><div class="bars" id="blockers"></div></div></section>
        </div>
      </div>
    </section>

    <section class="view" id="v-shortlist" hidden>
      <div class="ph"><div><h1>Shortlist</h1><p id="sl-sub"></p></div></div>
      <div class="tools"><div class="seg" id="sl-seg" role="group" aria-label="Sector"></div>
        <label class="search"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5 14 14"/></svg>
          <input type="search" id="q" placeholder="Search title, company or skill" aria-label="Search the shortlist"></label></div>
      <div class="card"><div class="tw"><table id="sl-table">
        <colgroup><col><col class="w-sp"><col class="w-sal"><col class="w-post"><col class="w-score"><col class="w-st"><col class="w-cmd"></colgroup><thead><tr>
        <th>Role</th><th>Sponsor</th>
        <th data-sort="salary"><button type="button">Salary <i></i></button></th><th class="hide-m" data-sort="posted"><button type="button">Posted <i></i></button></th>
        <th class="r" data-sort="score"><button type="button">Score <i></i></button></th><th class="hide-m">Status</th><th class="r" id="sl-act-h">Apply</th></tr></thead>
        <tbody id="sl-body"></tbody></table></div>
        <p class="empty" id="sl-empty" hidden style="padding-top:16px"></p><button class="more" id="sl-more" type="button" hidden></button></div>
    </section>

    <section class="view" id="v-applications" hidden>
      <div class="ph"><div><h1>Applications</h1><p id="ap-sub"></p></div></div>
      <div class="tools"><div class="seg" id="ap-seg" role="group" aria-label="Status"></div></div>
      <div class="card"><div class="tw"><table>
        <colgroup><col><col class="w-when"><col class="w-st"><col class="w-next"><col class="w-cmd"></colgroup>
        <thead><tr><th>Role</th><th>Applied</th><th>Status</th><th class="hide-m">Next step</th><th class="r" id="ap-act-h">Command</th></tr></thead>
        <tbody id="ap-body"></tbody></table></div><p class="empty" id="ap-empty" hidden style="padding-top:16px"></p></div>
    </section>

    <section class="view" id="v-insights" hidden>
      <div class="ph"><div><h1>Insights</h1><p>What is working, what is holding you back, and what was kept out of your way.</p></div></div>
      <div class="cols even">
        <section class="card"><div class="ch"><h2>What's working</h2></div><div class="cb" id="learn"></div></section>
        <section class="card"><div class="ch"><h2>Skills that would open more doors</h2></div><div class="cb" id="gaps"></div></section>
      </div>
      <section class="card"><div class="ch"><h2>Filtered out for you</h2><span>jobs that cannot sponsor you, by reason</span></div><div class="cb"><div class="bars" id="blockers2"></div></div></section>
    </section>

    <section class="view" id="v-system" hidden>
      <div class="ph"><div><h1>System</h1><p>Where jobs come from, and the visa facts the agent checks against.</p></div></div>
      <section class="card"><div class="ch"><h2>Job sources</h2><span>compared with previous runs</span></div><div class="kv" id="health"></div></section>
      <div class="cols even">
        <section class="card"><div class="ch"><h2>Visa routes</h2><span>checked on gov.uk</span></div><div class="kv" id="routes"></div></section>
        <section class="card"><div class="ch"><h2>Sponsorship facts</h2></div><div class="kv" id="facts"></div></section>
      </div>
      <p class="foot" id="foot"></p>
    </section>
  </main>
</div>
"""
