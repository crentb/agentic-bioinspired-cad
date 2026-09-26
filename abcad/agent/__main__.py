"""
abcad.agent.__main__ — ``python -m abcad.agent`` entry point.

PURPOSE
    Delegates to :func:`abcad.agent.cli.main` and exits with its return code. The Phase-1 child
    process is started through this entry point as well (``--emit-code``).

INPUTS / OUTPUTS
    Command-line arguments (see ``python -m abcad.agent --help``); the process exit code.
"""

from __future__ import annotations

from abcad.agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
