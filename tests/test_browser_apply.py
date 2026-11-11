"""Auto-apply against a small local job site: board link -> employer page -> two-step form -> thank you."""
import functools
import http.server
import threading
import types
from pathlib import Path

import pytest

SITE = Path(__file__).parent / "fixtures" / "site"


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        import os
        extra = {"executable_path": os.environ["JOBSTREAM_CHROMIUM_PATH"]} if os.environ.get("JOBSTREAM_CHROMIUM_PATH") else {}
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True, args=["--no-sandbox"], **extra).close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _chromium_ok(), reason="Playwright Chromium not available")


@pytest.fixture(scope="module")
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def pack(tmp_path):
    for name in ("cv.pdf", "letter.pdf"):
        (tmp_path / name).write_bytes(b"%PDF-1.4\n%%EOF\n")
    return types.SimpleNamespace(dir=tmp_path, cv_pdf=tmp_path / "cv.pdf", letter_pdf=tmp_path / "letter.pdf",
                                 cover_letter_text="Dear Hiring Team, ...")


def _ctx(profile, cv, settings):
    from jobstream.config import Context
    return Context(profile, cv, settings)


def test_auto_apply_through_board_link_and_two_step_form(site, pack, profile, cv, settings):
    from jobstream.apply.browser import fill_form
    asked = []

    def answers(qs):
        asked.extend(q["label"] for q in qs)
        return {q["label"]: ("Yes" if "sponsorship" in q["label"] else "I run IT for a 48-person company.", "high")
                for q in qs}

    res = fill_form(f"{site}/board.html", _ctx(profile, cv, settings), pack, answers, mode="auto", headless=True)
    assert res.submitted and res.blocked == "" and "thanks" in res.final_url
    assert any("Resume/CV" in f for f in res.filled)
    assert "spons=yes" in res.final_url                     # visa answer from the profile (example needs sponsorship)
    assert "why=I+run+IT" in res.final_url and any("Why do you want" in q for q in asked)
    assert (pack.dir / "after-submit.png").exists()


def test_auto_apply_stops_when_unsure(site, pack, profile, cv, settings):
    from jobstream.apply.browser import fill_form
    res = fill_form(f"{site}/form.html", _ctx(profile, cv, settings), pack,
                    lambda qs: {q["label"]: ("Yes", "low") for q in qs}, mode="auto", headless=True)
    assert not res.submitted and res.blocked == "unsure"


def test_auto_apply_stops_at_login_wall(site, pack, profile, cv, settings):
    from jobstream.apply.browser import fill_form
    res = fill_form(f"{site}/login.html", _ctx(profile, cv, settings), pack, lambda qs: {}, mode="auto", headless=True)
    assert not res.submitted and res.blocked == "login"
