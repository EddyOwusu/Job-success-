import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobagent.config import DEFAULT_SETTINGS  # noqa: E402
from jobagent.models import MasterCV, Profile  # noqa: E402


@pytest.fixture
def profile() -> Profile:
    return Profile.model_validate(yaml.safe_load((ROOT / "config/profile.example.yaml").read_text()))


@pytest.fixture
def cv() -> MasterCV:
    return MasterCV.model_validate(yaml.safe_load((ROOT / "config/cv_master.example.yaml").read_text()))


@pytest.fixture
def settings() -> dict:
    import copy
    return copy.deepcopy(DEFAULT_SETTINGS)
