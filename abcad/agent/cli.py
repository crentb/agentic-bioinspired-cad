"""
abcad.agent.cli — command line of the design loop (``python -m abcad.agent`` / ``abcad-agent``).

PURPOSE
    Maps the four modes onto the Phase-1 worker or the full two-phase loop:

      abcad-agent [PROMPT]                          full run: Phase-1 child, then Phase 2
      abcad-agent --emit-code PATH [PROMPT]         Phase-1 worker: generate, write PATH, exit
      abcad-agent --smoke [PROMPT]                  generate, print 1200 chars of the completion
      abcad-agent --smoke --emit-code PATH [PROMPT] both of the above
      abcad-agent --use-code PATH [PROMPT]          skip Phase 1; run Phase 2 on a saved script

    Flags may appear before or after the prompt; without a prompt the default Bouligand prompt
    is used. ``--use-code`` cannot be combined with ``--smoke`` or ``--emit-code``. Quote
    multi-word prompts: more than one positional argument is a usage error, so a prompt is never
    silently truncated to its first word.

EXIT CODES
    0 success (including honest non-approval), 1 run failure, 2 usage / settings / preflight.

INPUTS / OUTPUTS
    Configuration comes from ABCAD_* environment variables (see docs/AGENT.md). ``--help`` only
    imports the standard library and this package's light modules.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

import abcad
from abcad.agent.settings import DEFAULT_PROMPT, SettingsError, load_settings

_DESCRIPTION = (
    "Local agentic LLM-to-CAD loop: a design prompt becomes a Blender script (fine-tuned code "
    "emitter), a render judged by a local vision critic, repairs and refinements by a local text "
    "model, and an STL gated for single-material printability, with a run manifest."
)

_EPILOG = """\
modes:
  %(prog)s [PROMPT]                           full run (Phase-1 child process, then Phase 2)
  %(prog)s --emit-code PATH [PROMPT]          Phase 1 only: write the generated script to PATH
  %(prog)s --smoke [PROMPT]                   Phase 1 only: print the start of the completion
  %(prog)s --use-code PATH [PROMPT]           Phase 2 only, on a saved script (regression runs)

configuration:
  ABCAD_* environment variables (Blender path, models, endpoint, budgets, gate); see
  docs/AGENT.md. The chat endpoint must be a loopback address unless ABCAD_ALLOW_REMOTE_LLM=1.

exit codes:
  0 run completed (whatever the design outcome), 1 run failed, 2 usage/settings/preflight error
"""


@dataclass(frozen=True)
class CliArgs:
    """Parsed command line."""

    prompt: str
    smoke: bool
    emit_code: str | None
    use_code: str | None


def build_parser() -> argparse.ArgumentParser:
    """The argument parser (also used to render ``--help``)."""
    parser = argparse.ArgumentParser(
        prog="abcad-agent",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help=f'design request, quoted (default: "{DEFAULT_PROMPT}")',
    )
    parser.add_argument(
        "--emit-code",
        metavar="PATH",
        help="Phase-1 worker: generate a script and write it to PATH, then exit",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="generate and print the first 1200 characters of the model completion, then exit",
    )
    parser.add_argument(
        "--use-code",
        metavar="PATH",
        help="skip Phase 1 and run the loop on the saved script at PATH",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {abcad.__version__}")
    return parser


def parse_args(argv: Sequence[str]) -> CliArgs:
    """Parse the command line.

    Args:
        argv: arguments without the program name.

    Returns:
        The :class:`CliArgs`.

    Raises:
        SystemExit: code 0 for ``--help`` / ``--version``, code 2 for usage errors.
    """
    parser = build_parser()
    namespace = parser.parse_intermixed_args(list(argv))  # flags before or after the prompt
    if namespace.use_code is not None and (namespace.smoke or namespace.emit_code is not None):
        parser.error("--use-code cannot be combined with --smoke or --emit-code")
    words: list[str] = namespace.prompt
    if len(words) > 1:
        parser.error(
            f"expected one prompt argument, got {len(words)}; quote a multi-word prompt, "
            f'e.g. "{DEFAULT_PROMPT}"'
        )
    prompt = words[0] if words and words[0].strip() else DEFAULT_PROMPT
    return CliArgs(
        prompt=prompt,
        smoke=bool(namespace.smoke),
        emit_code=namespace.emit_code,
        use_code=namespace.use_code,
    )


def _status(code: object) -> int:
    """Normalize a SystemExit code (None, int or message) to an integer status."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of ``python -m abcad.agent`` and the ``abcad-agent`` console script.

    Args:
        argv: arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:  # argparse exits for --help, --version and usage errors
        return _status(exc.code)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"abcad-agent: settings error: {exc}", file=sys.stderr)
        return 2

    from abcad.agent.console import configure_logging

    configure_logging(settings.log_level)
    if args.emit_code is not None or args.smoke:
        from abcad.agent.phase_one import child_main  # Phase-1 worker (loads the LoRA)

        return child_main(args.prompt, settings, handoff_path=args.emit_code, smoke=args.smoke)

    from abcad.agent.runner import run_design_loop  # Phase-2 parent (never loads the LoRA)

    return run_design_loop(args.prompt, settings=settings, use_code=args.use_code).exit_code
