"""Fill job application forms in a real browser with Playwright.

Works on Greenhouse, Lever and Ashby forms, and makes a best effort on other
sites. From a job board's link it finds the form (past "Apply now" buttons, new tabs and cookie
banners), reads every field's label, fills the ones it knows (name, email, CV upload...), asks
Claude to answer the rest, steps through multi-page forms, and then either:
  - review mode: leaves the browser open for you to check and press Submit, or
  - auto mode:   presses Submit itself, if every required field has a confident answer.
It never solves CAPTCHAs, never creates accounts and never signs in for you: when a site needs any of
those, it stops and the job goes on your "Needs you" list.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .answers import classify, pick_option, value_for

COLLECT_JS = r"""
() => {
  const out = [];
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const txt = el => (el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : '');
  const labelFor = el => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && txt(l)) return txt(l);
    }
    const wrap = el.closest('label');
    if (wrap && txt(wrap)) return txt(wrap);
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(' ').map(id => txt(document.getElementById(id))).join(' ').trim(); if (t) return t; }
    let node = el.parentElement;
    for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
      const l = node.querySelector('label, legend, .application-label, [class*="label"], [class*="Label"]');
      if (l && txt(l) && !l.contains(el)) return txt(l);
    }
    return el.getAttribute('placeholder') || el.name || el.id || '';
  };
  const els = document.querySelectorAll('input, textarea, select, [role="combobox"]');
  const groups = {};
  let i = window.__jaN || 0;            // unique across the steps of a multi-page form
  for (const el of els) {
    if (el.hasAttribute('data-ja')) continue;   // filled on an earlier step
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'search'].includes(type)) continue;
    if (type !== 'file' && !visible(el)) continue;
    if (type !== 'file' && (el.tabIndex === -1 || el.getAttribute('aria-hidden') === 'true')) continue;
    if (el.tagName === 'INPUT' && el.getAttribute('role') === 'combobox' && el.closest('[data-ja]')) continue;
    el.setAttribute('data-ja', String(i));
    const required = el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(labelFor(el));
    if (type === 'radio' || type === 'checkbox') {
      const optLabel = labelFor(el);
      // find the question text: nearest ancestor holding a label-like element that is not an option label
      let qLabel = '', qNode = null, node = el.parentElement;
      const isOptionLabel = l => {
        if (l.querySelector('input')) return true;
        const f = l.getAttribute('for');
        if (f) { const t = document.getElementById(f); if (t && ['radio', 'checkbox'].includes(t.type)) return true; }
        return false;
      };
      for (let k = 0; k < 7 && node && !qLabel; k++, node = node.parentElement) {
        for (const l of node.querySelectorAll('legend, .application-label, label, [class*="label"], [class*="Label"], [class*="title"], h3, h4')) {
          if (!l.contains(el) && !isOptionLabel(l) && txt(l) && txt(l) !== optLabel) { qLabel = txt(l); qNode = node; break; }
        }
      }
      if (qNode && !qNode.hasAttribute('data-ja-g')) qNode.setAttribute('data-ja-g', String(i));
      const gkey = (el.name || '') + '|' + (qNode ? qNode.getAttribute('data-ja-g') : String(i));
      if (!groups[gkey]) { groups[gkey] = {idx: String(i), kind: type, label: qLabel || optLabel, required, options: [], option_idx: []}; out.push(groups[gkey]); }
      groups[gkey].options.push(optLabel);
      groups[gkey].option_idx.push(String(i));
      groups[gkey].required = groups[gkey].required || required;
    } else {
      const item = {idx: String(i), kind: el.tagName === 'SELECT' ? 'select' : (el.getAttribute('role') === 'combobox' ? 'combobox' : type),
                    label: labelFor(el), name: el.name || el.id || '', required, options: []};
      if (el.tagName === 'SELECT') item.options = Array.from(el.options).map(o => o.text.trim()).filter(t => t && !/^select|^--/i.test(t));
      out.push(item);
    }
    i++;
  }
  window.__jaN = i;
  return out;
}
"""

# Finding the form behind job-board links: "Apply now" buttons, cookie banners, login walls
FORM_STATE_JS = r"""
() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const inputs = Array.from(document.querySelectorAll('input, textarea, select')).filter(el => {
    const t = (el.getAttribute('type') || el.tagName).toLowerCase();
    return !['hidden', 'submit', 'button', 'reset', 'image', 'search', 'checkbox', 'radio'].includes(t) && (t === 'file' || visible(el));
  });
  const file = inputs.some(el => (el.getAttribute('type') || '').toLowerCase() === 'file');
  const email = inputs.some(el => /email/i.test((el.getAttribute('type') || '') + ' ' + (el.name || '') + ' ' + (el.id || '') +
                                               ' ' + (el.getAttribute('autocomplete') || '') + ' ' + (el.getAttribute('placeholder') || '')));
  const password = Array.from(document.querySelectorAll('input[type=password]')).some(visible);
  return {fields: inputs.length, file, email, password, text: (document.body.innerText || '').slice(0, 6000)};
}
"""

APPLY_TEXT = re.compile(r"^\s*(apply( now| online| here| for this (job|role|position|vacancy)| on (the )?(company|employer'?s?) "
                        r"(site|website))?|start (your |my )?application|continue to (the )?application|apply via .{2,30}|"
                        r"i'?m interested)\s*[>→]?\s*$", re.I)
NEXT_TEXT = re.compile(r"^\s*(next( step| page)?|continue|save (and|&) continue|proceed|next: .{2,40})\s*[>→]?\s*$", re.I)
FINAL_TEXT = re.compile(r"^\s*(submit( (my |your )?application)?|send( my)? application|complete application|"
                        r"finish( and submit)?|apply)\s*$", re.I)
LOGIN_TEXT = re.compile(r"sign in to apply|log ?in to apply|create (an |your )?account|register to apply|"
                        r"already have an account|sign in to continue|log in to continue", re.I)
COOKIE_TEXT = re.compile(r"^\s*(reject all|reject( all)? (non-essential|optional)|necessary (cookies )?only|"
                         r"only (necessary|essential)|decline( all)?|accept all( cookies)?|accept( cookies)?|allow all( cookies)?|"
                         r"i agree|agree|got it|ok)\s*$", re.I)

CAPTCHA_SELECTORS = ["iframe[src*='recaptcha'][title*='challenge']", "iframe[src*='hcaptcha']",
                     "iframe[src*='challenges.cloudflare.com']", ".h-captcha", ".cf-turnstile"]
SUCCESS_TEXT = re.compile(r"thank you for applying|application (has been )?(received|submitted)|thanks for applying|"
                          r"we('|’)ve received your application|successfully submitted", re.I)


@dataclass
class FillResult:
    # why it was not submitted: login | captcha | unanswered | unsure | no_form | no_confirmation | "" (it was)
    blocked: str = ""
    final_url: str = ""
    filled: list[str] = field(default_factory=list)
    unanswered_required: list[str] = field(default_factory=list)
    low_confidence: list[str] = field(default_factory=list)
    submitted: bool = False
    captcha: bool = False
    screenshot: Optional[Path] = None
    notes: list[str] = field(default_factory=list)


def _is_resume(f: dict) -> bool:
    return bool(re.search(r"resume|\bcv\b|curriculum", f["label"] + " " + f.get("name", ""), re.I))


def _is_cover(f: dict) -> bool:
    return bool(re.search(r"cover", f["label"] + " " + f.get("name", ""), re.I))


def _clickables(page, pattern: re.Pattern):
    """Visible links and buttons whose text matches, best first (exact matches before partial)."""
    out = []
    loc = page.locator("a, button, input[type=submit], input[type=button], [role=button]")
    for k in range(min(loc.count(), 400)):
        el = loc.nth(k)
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text(timeout=500) or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip()
        except Exception:
            continue
        if text and len(text) < 60 and pattern.search(text):
            out.append(el)
    return out


def _dismiss_cookies(page) -> None:
    """Close a cookie banner, preferring 'reject' / 'necessary only' over 'accept'."""
    found = _clickables(page, COOKIE_TEXT)
    if not found:
        return
    def rank(el):
        t = (el.inner_text() or "").lower()
        return 0 if ("reject" in t or "necessary" in t or "essential" in t or "decline" in t) else 1
    try:
        sorted(found, key=rank)[0].click(timeout=2000)
        page.wait_for_timeout(700)
    except Exception:
        pass


def _state(page) -> dict:
    try:
        return page.evaluate(FORM_STATE_JS)
    except Exception:
        return {"fields": 0, "file": False, "email": False, "password": False, "text": ""}


def _form_ready(st: dict) -> bool:
    return st["file"] or (st["email"] and st["fields"] >= 3)


def _login_wall(st: dict) -> bool:
    return st["password"] or (not st["file"] and bool(LOGIN_TEXT.search(st["text"])))


def open_form(page, res: FillResult, hops: int = 4):
    """From a job advert (or a job board's redirect) to the application form itself. Returns the page."""
    for _ in range(hops):
        _dismiss_cookies(page)
        st = _state(page)
        if _form_ready(st):
            return page
        if _login_wall(st):
            res.blocked = "login"
            return page
        buttons = _clickables(page, APPLY_TEXT)
        if not buttons:
            res.blocked = "no_form"
            return page
        context, before = page.context, len(page.context.pages)
        try:
            buttons[0].click(timeout=5000)
        except Exception:
            res.blocked = "no_form"
            return page
        page.wait_for_timeout(3000)
        if len(context.pages) > before:          # opened in a new tab
            page = context.pages[-1]
        try:
            page.wait_for_load_state("domcontentloaded", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
    st = _state(page)
    if not _form_ready(st):
        res.blocked = "login" if _login_wall(st) else "no_form"
    return page


def _fill_step(page, ctx, pack, answer_fn, res: FillResult) -> None:
    """Fill every field visible on the current page (one step of the form)."""
    fields = page.evaluate(COLLECT_JS)
    open_questions = []
    for f in fields:
        loc = page.locator(f'[data-ja="{f["idx"]}"]')
        try:
            if f["kind"] == "file":
                if _is_cover(f):
                    loc.set_input_files(str(pack.letter_pdf))
                    res.filled.append("Cover letter (file)")
                elif _is_resume(f) or "resume" not in " ".join(res.filled).lower():
                    loc.set_input_files(str(pack.cv_pdf))
                    res.filled.append("Resume/CV (file)")
                continue
            if f["kind"] == "textarea" and _is_cover(f):
                loc.fill(pack.cover_letter_text)
                res.filled.append("Cover letter (text)")
                continue
            key = classify(f["label"])
            val = value_for(key, ctx) if key else None
            if val and f.get("options"):
                val = pick_option(val, f["options"])
            if val and _set(page, loc, f, val):
                res.filled.append(f"{f['label'][:60]} = {val[:40]}")
            else:
                open_questions.append(f)
        except Exception as exc:  # one odd field must not stop the rest
            res.notes.append(f"Could not fill '{f['label'][:60]}': {exc.__class__.__name__}")
            open_questions.append(f)

    if not open_questions:
        return
    qs = [{"label": f["label"], "required": f["required"], "type": f["kind"], "options": f.get("options", [])}
          for f in open_questions]
    answers = answer_fn(qs)
    for f in open_questions:
        ans, conf = answers.get(f["label"], ("", "low"))
        if not ans:
            if f["required"]:
                res.unanswered_required.append(f["label"])
            continue
        if f.get("options"):
            ans = pick_option(ans, f["options"]) or ""
        try:
            if ans and _set(page, page.locator(f'[data-ja="{f["idx"]}"]'), f, ans):
                res.filled.append(f"{f['label'][:60]} = {ans[:40]}")
                if conf == "low":
                    res.low_confidence.append(f["label"])
            elif f["required"]:
                res.unanswered_required.append(f["label"])
        except Exception:
            if f["required"]:
                res.unanswered_required.append(f["label"])


def _next_button(page):
    """A 'Next' / 'Continue' button on a multi-page form, unless the page already shows its final Submit."""
    if _clickables(page, FINAL_TEXT):
        return None
    nxt = _clickables(page, NEXT_TEXT)
    return nxt[0] if nxt else None


def fill_form(url: str, ctx, pack, answer_fn: Callable[[list[dict]], dict[str, tuple[str, str]]],
              mode: str = "review", headless: bool = False, chromium_path: str = "",
              confirm: Callable[[str], bool] = lambda msg: input(msg).strip().lower().startswith("y")) -> FillResult:
    """answer_fn(questions) -> {label: (answer, confidence)} for fields we can't fill from the profile.

    auto: submits only when every required field has a confident, truthful answer, there is no CAPTCHA
    and no login wall; otherwise it stops and says why (res.blocked), so you can finish it yourself."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Install Playwright for form filling: pip install playwright && playwright install chromium") from e

    res = FillResult()
    with sync_playwright() as pw:
        # dry: fill in a hidden browser and screenshot, never submit (for testing)
        launch = {"headless": (headless and mode == "auto") or mode == "dry"}
        chromium_path = chromium_path or os.environ.get("JOBSTREAM_CHROMIUM_PATH", "")
        if chromium_path:
            launch["executable_path"] = chromium_path
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            launch["args"] = ["--no-sandbox"]  # Chromium refuses to start as root otherwise (containers)
        browser = pw.chromium.launch(**launch)
        page = browser.new_context(viewport={"width": 1280, "height": 1600}, locale="en-GB").new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        page = open_form(page, res)

        if not res.blocked:
            for _step in range(8):                 # multi-page forms: fill, Next, fill...
                _fill_step(page, ctx, pack, answer_fn, res)
                if res.unanswered_required or res.low_confidence:
                    break
                nxt = _next_button(page)
                if nxt is None:
                    break
                try:
                    nxt.click(timeout=5000)
                    page.wait_for_timeout(2500)
                except Exception:
                    break
                _dismiss_cookies(page)

        res.captcha = any(page.locator(s).count() for s in CAPTCHA_SELECTORS)
        res.screenshot = pack.dir / "form-filled.png"
        try:
            page.screenshot(path=str(res.screenshot), full_page=True)
        except Exception:
            res.screenshot = None
        if not res.blocked:
            res.blocked = ("captcha" if res.captcha else "unanswered" if res.unanswered_required
                           else "unsure" if res.low_confidence else "")

        if mode == "auto" and not res.blocked:
            res.submitted = _submit(page)
            if not res.submitted:
                res.blocked = "no_confirmation"
                res.notes.append("Pressed Submit but saw no confirmation. Check the page and your email.")
            try:
                page.screenshot(path=str(pack.dir / "after-submit.png"), full_page=True)
            except Exception:
                pass
        res.final_url = page.url
        if not res.submitted and mode == "review":
            print("\n  The form is filled in the browser window.")
            if res.blocked == "login":
                print("  - This site needs you to sign in or create an account first.")
            for q in res.unanswered_required:
                print(f"  - NEEDS YOU: {q[:100]}")
            for q in res.low_confidence:
                print(f"  - CHECK:     {q[:100]}")
            if res.captcha:
                print("  - A CAPTCHA is on the page: solve it yourself.")
            res.submitted = confirm("  Check everything, press Submit in the browser, then type 'y' here once it is sent (n to skip): ")
        page.wait_for_timeout(500)
        browser.close()
    return res


def _set(page, loc, f: dict, value: str) -> bool:
    kind = f["kind"]
    if kind in ("text", "email", "tel", "url", "number", "input", "textarea", "date"):
        loc.fill(value)
        return True
    if kind == "select":
        loc.select_option(label=value)
        return True
    if kind == "combobox":
        loc.click()
        page.keyboard.type(value[:60], delay=15)
        page.wait_for_timeout(600)
        page.keyboard.press("Enter")
        return True
    if kind in ("radio", "checkbox"):
        targets = [value] if kind == "radio" else [v.strip() for v in value.split(";")]
        done = False
        for t in targets:
            for opt, idx in zip(f["options"], f["option_idx"]):
                if opt.strip().lower() == t.strip().lower() or (len(f["options"]) == 1 and t.lower() in ("yes", "true", opt.lower())):
                    page.locator(f'[data-ja="{idx}"]').check(force=True)
                    done = True
        return done
    return False


def _submit(page) -> bool:
    for sel in ("button[type=submit]", "button:has-text('Submit application')", "button:has-text('Submit Application')",
                "button:has-text('Submit')", "input[type=submit]"):
        btn = page.locator(sel).first
        try:
            if btn.is_visible(timeout=1000):
                btn.click()
                break
        except Exception:
            continue
    else:
        return False
    deadline = time.time() + 25
    while time.time() < deadline:
        page.wait_for_timeout(1000)
        try:
            for p in page.context.pages:
                if SUCCESS_TEXT.search(p.inner_text("body")[:5000]) or \
                        re.search(r"/(thank-?you|thanks|confirmation|application-?(submitted|complete|received))", p.url, re.I):
                    return True
        except Exception:
            pass
    return False
