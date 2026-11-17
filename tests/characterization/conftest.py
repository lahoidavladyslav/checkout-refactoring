from __future__ import annotations

import pytest

from tests.characterization.model import Runner
from tests.characterization.runners import legacy_module, legacy_runner, new_runner

__all__ = ["legacy_module", "legacy_runner", "new_runner", "runner"]


@pytest.fixture(params=["legacy_runner", "new_runner"])
def runner(request: pytest.FixtureRequest) -> Runner:
    """Every test using this fixture runs once against each implementation."""
    runner: Runner = request.getfixturevalue(request.param)
    return runner
