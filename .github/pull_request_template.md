## Summary

<!-- What changes, and why. Link the issue it resolves, if any. -->

## Verification

<!-- How the change was verified: tests added or updated, commands run, and for
numerical changes the evidence record in results/ that backs the new numbers. -->

## Checklist

- [ ] `ruff check .`, `black --check .` and `pytest -m "not slow"` pass locally
- [ ] Tests added or updated for any behavior change
- [ ] Numbers quoted in docs or the README trace to a record in `results/`
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] No secrets, credentials, personal paths, or large binaries (STL, meshes, solver output) committed
