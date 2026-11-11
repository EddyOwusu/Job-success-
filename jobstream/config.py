"""Loading the profile, master CV, agent settings and environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import MasterCV, Profile

ROOT = Path(os.environ.get("JOBSTREAM_HOME", Path(__file__).resolve().parent.parent))
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = ROOT / "output"
DB_PATH = DATA_DIR / "jobstream.db"


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (KEY=VALUE lines). Real environment variables win."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


DEFAULT_SETTINGS: dict[str, Any] = {
    "llm": {
        "model": "claude-opus-5-5",
        # Effort per task. Higher = better writing, more tokens.
        "assess_effort": "medium",
        "tailor_effort": "high",
        # How many of the best keyword-scored jobs per run get a deep Claude assessment
        "max_assessments_per_run": 25,
    },
    "sources": {
        "greenhouse": True,
        "lever": True,
        "ashby": True,
        "smartrecruiters": True,
        "reed": True,       # needs REED_API_KEY
        "adzuna": True,     # needs ADZUNA_APP_ID / ADZUNA_APP_KEY
        "workday": True,    # big non-tech employers (banks, pharma, insurers...)
        "nhs": True,        # NHS Jobs: all NHS trusts in England and Wales
        "jobsacuk": True,   # universities and research institutes
    },
    "search": {
        "country": "GB",
        "max_age_days": 30,
        "uk_only": True,
    },
    "scoring": {
        "shortlist_threshold": 60,    # keyword score needed to be considered
        "apply_threshold": 70,        # Claude fit score needed to prepare an application
        # Tune the score weights from your own results (needs 20+ applications with a result)
        "adaptive": True,
    },
    "sponsorship": {
        # Only keep jobs at employers on the Home Office sponsor register
        "require_licensed_sponsor": True,
        # UK Skilled Worker salary rules. CHECK THESE ON GOV.UK BEFORE RELYING ON THEM:
        # https://www.gov.uk/skilled-worker-visa/your-job
        "general_threshold_gbp": 41700,
        "new_entrant_threshold_gbp": 33400,
        # If you were first sponsored before 4 April 2024 and have held Skilled Worker visas ever since
        "transitional_threshold_gbp": 31300,
        "scaleup_threshold_gbp": 39100,     # Scale-up Worker visa minimum (or the going rate, if higher)
        # Employers that sponsor under a different legal name than their brand
        "aliases": {
            "Meta": "Facebook UK", "Coinbase": "CB Payments Ltd", "Elastic": "Elasticsearch Limited",
            "Lloyds Banking Group": "Lloyds Bank plc", "NewDay": "NewDay Cards Limited", "Oxa": "Oxa Autonomy Limited",
            "Paddle": "Paddle.com Market Limited", "Deliveroo": "Roofoods Ltd",
            "Lottie": "Lottie Organisation Ltd", "Birdie": "Birdie Care Services Limited",
        },
        # Going rates for common tech occupation codes. Fill in from the official
        # going-rates table (Appendix Skilled Occupations); 0 = not checked.
        "going_rates_gbp": {
            "2134 Programmers and software development professionals": 0,
            "2133 IT business analysts, architects and systems designers": 0,
            "2135 Cyber security professionals": 0,
            "2136 IT quality and testing professionals": 0,
            "2137 IT network professionals": 0,
            "2139 Information technology professionals n.e.c.": 0,
            "2433 Data scientists": 0,
        },
    },
    "apply": {
        # review: fill the form in a visible browser and let you press Submit
        # auto:   submit by itself when every required field has a confident answer
        # pack:   only build the application pack (CV, letter, answers) for you to submit
        "mode": "review",
        "max_applications_per_day": 10,
        "max_per_company_per_30_days": 2,
        "headless": False,
        "chromium_path": "",          # leave blank to use Playwright's own browser
    },
    "dashboard": {
        "title": "JobStream",         # the product name shown in the dashboard's sidebar
    },
    "speculative": {
        "max_per_week": 5,            # approach packs drafted per week (quality over volume)
    },
    "alerts": {
        "hot_fit": 85,                # Claude fit score that triggers an "apply today" push
        "hot_score": 75,              # keyword score used instead when Claude hasn't assessed the job
        "max_age_hours": 48,          # only jobs found (and posted) this recently
        "max_per_run": 5,
        "max_assess_per_watch": 8,    # Claude assessments per quick check
    },
    "radar": {
        "max_probes_per_run": 40,     # newly licensed sponsors to check for job boards each run
    },
    "inbox": {
        "days": 30,                   # how far back to read for replies
    },
    "followup": {
        "days": [4, 10, 18],          # follow-up reminders after applying
    },
    "discovery": {
        "max_probes_per_run": 400,    # sponsor-register companies to probe for job boards
        "name_keywords": [
            "tech", "software", "digital", "data", "labs", "ai", "systems", "technologies",
            "solutions", "cloud", "analytics", "cyber", "app", "platform", "fintech",
            "robotics", "computing", "network", "intelligence", "engineering", "studio",
            "health", "bank", "insurance", "energy", "media", "games", "pharma", "bio", "finance",
        ],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as f:      # tolerate a byte-order mark from Notepad
        return yaml.safe_load(f) or {}


def _pick(name: str) -> Path:
    """Prefer config/<name>.yaml, fall back to the example file."""
    real = CONFIG_DIR / f"{name}.yaml"
    if real.exists():
        return real
    example = CONFIG_DIR / f"{name}.example.yaml"
    if example.exists():
        return example
    raise FileNotFoundError(f"Missing {real}. Run `jobstream init` first.")


@dataclass
class Context:
    profile: Profile
    cv: MasterCV
    settings: dict
    using_examples: list[str] = field(default_factory=list)

    @property
    def llm_enabled(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def load_context() -> Context:
    load_dotenv()
    using_examples = []
    paths = {}
    for name in ("profile", "cv_master"):
        p = _pick(name)
        paths[name] = p
        if p.name.endswith(".example.yaml"):
            using_examples.append(name)
    settings_path = CONFIG_DIR / "settings.yaml"
    user_settings = _read_yaml(settings_path) if settings_path.exists() else {}
    return Context(
        profile=Profile.model_validate(_read_yaml(paths["profile"])),
        cv=MasterCV.model_validate(_read_yaml(paths["cv_master"])),
        settings=_deep_merge(DEFAULT_SETTINGS, user_settings),
        using_examples=using_examples,
    )


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
