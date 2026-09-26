"""
tests/agent/conftest.py — shared fixtures of the abcad.agent test suite.

PURPOSE
    Every test here runs on plain CPython 3.10+ with only numpy and pytest: no network, no Blender,
    no GPU and no model weights. The fixtures provide isolated settings (a temporary output root,
    an empty environment so the developer's own ABCAD_* variables never leak in, and the current
    Python interpreter standing in for an executable Blender so the run preflight passes) and the
    paths of the recorded-run fixtures.

INPUTS / OUTPUTS
    make_settings(**overrides) -> AgentSettings rooted in tmp_path.
    fixtures_dir / woven_fixture / recorded_runs -> test data under tests/agent/fixtures/.
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys

import pytest

from abcad.agent.settings import AgentSettings, load_settings

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _agent_logging(caplog):
    """Capture INFO records of the "abcad.agent" logger in every test (warnings are asserted)."""
    caplog.set_level(logging.INFO, logger="abcad.agent")
    yield


@pytest.fixture
def make_settings(tmp_path):
    """Factory of isolated settings: empty environment, output under tmp_path, fake Blender.

    ``blender_path`` is the running interpreter (an existing executable file), which satisfies
    the preflight; tests that execute anything inject a fake executor or process runner, so it is
    never run as Blender. The deep audit is off unless a test turns it on.
    """

    def factory(**overrides) -> AgentSettings:
        values = {
            "out_dir": str(tmp_path / "out"),
            "blender_path": sys.executable,
            "deep_audit": False,
        }
        values.update(overrides)
        return load_settings(env={}, **values)

    return factory


@pytest.fixture
def settings(make_settings) -> AgentSettings:
    """Default isolated settings."""
    return make_settings()


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    """Directory of the static test fixtures."""
    return FIXTURES


@pytest.fixture(scope="session")
def woven_fixture() -> pathlib.Path:
    """Stand-in for the saved failing woven emit (starts with ``import bpy``)."""
    return FIXTURES / "woven_failing_emit.py"


@pytest.fixture(scope="session")
def recorded_runs() -> dict:
    """Recorded-run numbers transcribed from the specification's evidence index."""
    with open(FIXTURES / "recorded_runs.json", encoding="utf-8") as handle:
        return json.load(handle)
