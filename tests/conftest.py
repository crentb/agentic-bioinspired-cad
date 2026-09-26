"""
tests/conftest.py — shared pytest configuration for the abcad test suite.

PURPOSE
    * Register the ``slow`` marker (mirrored in pyproject.toml) so ``-m "not slow"`` selects the fast
      suite: pure-Python / numpy / scipy checks that run anywhere on CPython 3.10+ without Blender,
      the conda CAD/FEA environments, MOOSE, network access or large binary artifacts.
    * Put the repository root on sys.path, so ``import abcad`` works from a fresh checkout without
      ``pip install -e .`` (an installed copy is found the same way, just earlier on the path).
    * Provide shared path fixtures: the repository root, the curated evidence records in results/,
      and the directory of large local artifacts (configurable, see ``artifacts_dir``).

INPUTS
    ABCAD_ARTIFACTS_DIR   directory holding large binary artifacts used by slow gold tests (e.g.
                          woven_fea_small.stl); default: $ABCAD_OUT, else ./out. Tests that need a
                          missing artifact skip cleanly.
OUTPUTS
    None (configuration and fixtures only).
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

# Repository root = the parent of tests/. Inserted first so the checkout under test wins.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    """Register custom markers so ``pytest --strict-markers`` accepts them."""
    config.addinivalue_line(
        "markers",
        "slow: needs the host-side stack (Blender, conda cad_env/sfepy_env, MOOSE, Ollama or large "
        "local artifacts); skipped in default CI",
    )


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    """Absolute path of the repository checkout under test."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def results_dir() -> pathlib.Path:
    """The curated evidence records (text only) that back the documented numbers."""
    return REPO_ROOT / "results"


@pytest.fixture(scope="session")
def artifacts_dir() -> pathlib.Path:
    """Directory of large local artifacts: $ABCAD_ARTIFACTS_DIR, else $ABCAD_OUT, else ./out."""
    return pathlib.Path(os.environ.get("ABCAD_ARTIFACTS_DIR") or os.environ.get("ABCAD_OUT", "out"))
