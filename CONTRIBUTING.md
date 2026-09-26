# Contributing

Thanks for your interest in `agentic-bioinspired-cad`. This guide covers the development setup, the host-side engines, and the checks CI enforces, so a contribution lands green on the first try.

## Development setup

```bash
git clone https://github.com/crentb/agentic-bioinspired-cad.git
cd agentic-bioinspired-cad
python -m pip install -e ".[dev]"     # core runtime + pinned dev tools (pytest, ruff, black, mypy, pre-commit)
pre-commit install                    # gitleaks, ruff, black and hygiene hooks on every commit
```

The default install and CI exercise the **pure-Python logic**: generator geometry math, the manufacturability gate, the agent-loop control flow (with test doubles), and the evidence-record checks. The heavy engines are optional and run on the host:

| Engine | Used by | How to install |
|---|---|---|
| Blender 4.2+ (headless) | helicoidal and woven builds, agent-loop renders | blender.org; set `ABCAD_BLENDER` if it is not on `PATH` |
| conda `cad_env` | woven Blender-free path, meshing, print audit, damage tolerance, agent loop | `conda env create -f env/cad_env.lock.yml`; set `ABCAD_CAD_PYTHON` |
| conda `sfepy_env` | linear and finite-strain FEA solves | `conda env create -f env/sfepy_env.lock.yml`; set `ABCAD_SFEPY_PYTHON` |
| MOOSE (combined module) | phase-field fracture decks | mooseframework.inl.gov; set `ABCAD_MOOSE_EXEC` |
| Ollama + model weights | agent-loop critic and repair agents; code emitter | ollama.com; see README "Models" |

Tests that need any of these are marked `slow` and skip cleanly when the engine is absent.

## Checks (what CI runs)

Run these before opening a pull request; CI runs the same on Python 3.10 to 3.14:

```bash
ruff check .                  # lint
black --check .               # formatting
mypy -p abcad                 # type-checking (advisory)
pytest -m "not slow" --cov    # fast tests with coverage
```

With the host-side engines installed, run everything:

```bash
pytest
```

CI additionally runs the security gate (gitleaks over the full history, bandit, pip-audit), builds and validates the distributions, and builds, scans (trivy), smoke-tests and SBOM-signs the container image. CodeQL analyzes both the Python code and the workflows. All of it must be green before a merge.

## Evidence discipline

Every number quoted in the README or `docs/` traces to a text evidence record in `results/` (produced by the instrument named in that record). A change that alters a documented result must update the record and the text together, and the gold tests in `tests/` re-verify the recorded values.

## Pull requests

1. Branch from `main`.
2. Keep changes focused; add or update tests for any behavior change.
3. Update `CHANGELOG.md` under `[Unreleased]`.
4. Never commit geometry, meshes or solver output (STL, MSH, VTK, Exodus, NPZ); they are regenerable and ignored by `.gitignore`.
5. Ensure all checks above pass locally.

## License

By contributing, you agree that your contributions are licensed under the project's **Apache-2.0** license (see `LICENSE` and `NOTICE`).
