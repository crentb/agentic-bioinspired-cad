"""
abcad.agent.console — logging setup, the run-log tee, and structured event lines.

PURPOSE
    * ``configure_logging`` attaches one stdout handler to the ``abcad.agent`` logger. The handler
      resolves ``sys.stdout`` at every emit, so records written while the run-log tee is active
      land in ``run.log`` as well as on the terminal.
    * ``tee_stdout(path)`` mirrors the whole process stdout into a file for the duration of a run.
      That captures the gate module's printed summary, the forwarded Phase-1 child output and the
      loop's own log lines, so a run can be reconstructed without the terminal.
    * ``event(name, **fields)`` writes one machine-greppable line ``event=<name> key=value ...``.
      Callers log a human-readable message separately.

INPUTS / OUTPUTS
    Plain-text, ASCII log lines of the tool itself (model-generated text such as critique comments
    is logged as returned). No emoji. Nothing is sent anywhere but stdout and the run log.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TextIO

LOGGER_NAME = "abcad.agent"
LOGGER = logging.getLogger(LOGGER_NAME)

# Timestamped, level-tagged, single-line records. Seconds resolution is enough for a loop whose
# steps take tens of seconds, and it keeps the run log compact.
_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
_DATEFMT = "%H:%M:%S"


class _CurrentStdoutHandler(logging.StreamHandler):
    """StreamHandler bound to whatever ``sys.stdout`` is at emit time (tee-aware).

    A plain ``StreamHandler(sys.stdout)`` captures the stream object once; after ``tee_stdout``
    swaps ``sys.stdout`` the records would bypass the run log. Resolving the stream per emit
    avoids that.
    """

    abcad_agent_handler = True  # marker used to keep configure_logging() idempotent

    def __init__(self) -> None:
        super().__init__(stream=sys.stdout)

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        """The current process stdout."""
        return sys.stdout

    @stream.setter
    def stream(self, value: TextIO) -> None:
        """Ignore assignments made by the base class; the stream is always the live stdout."""


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure and return the ``abcad.agent`` logger (idempotent).

    Args:
        level: logging level name (DEBUG, INFO, WARNING, ERROR or CRITICAL).

    Returns:
        The configured logger. Records still propagate to the root logger, which has no handler
        in the command-line tool, so nothing is printed twice there; test harnesses that capture
        through the root logger keep working.
    """
    LOGGER.setLevel(level.upper())
    if not any(getattr(h, "abcad_agent_handler", False) for h in LOGGER.handlers):
        handler = _CurrentStdoutHandler()
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        LOGGER.addHandler(handler)
    return LOGGER


class _TeeStream:
    """Text stream that writes to the original stdout and mirrors every write into a file."""

    def __init__(self, primary: TextIO, mirror: TextIO) -> None:
        self._primary = primary
        self._mirror = mirror

    def write(self, text: str) -> int:
        """Write to both streams; a closed mirror never breaks the primary output."""
        written = self._primary.write(text)
        try:
            self._mirror.write(text)
        except ValueError:  # mirror already closed (e.g. a late write during shutdown)
            pass
        return written

    def flush(self) -> None:
        """Flush both streams."""
        self._primary.flush()
        try:
            self._mirror.flush()
        except ValueError:
            pass

    def isatty(self) -> bool:
        """Report the terminal property of the original stream."""
        return self._primary.isatty()

    def fileno(self) -> int:
        """File descriptor of the original stream (libraries that need a real fd use it)."""
        return self._primary.fileno()

    @property
    def encoding(self) -> str | None:
        """Encoding of the original stream."""
        return getattr(self._primary, "encoding", None)

    def __getattr__(self, name: str) -> Any:
        """Delegate every other attribute to the original stream."""
        return getattr(self._primary, name)


@contextmanager
def tee_stdout(path: str) -> Iterator[str]:
    """Mirror ``sys.stdout`` into ``path`` (appended, UTF-8, line-buffered) inside the block.

    Args:
        path: log file to append to; its directory is created when missing.

    Yields:
        The path, for convenience.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    # buffering=1 selects line buffering in text mode, so the log is readable while a run is live.
    with open(path, "a", encoding="utf-8", errors="replace", buffering=1) as handle:
        original = sys.stdout
        tee = _TeeStream(original, handle)
        sys.stdout = tee  # type: ignore[assignment]
        try:
            yield path
        finally:
            try:
                tee.flush()
            finally:
                sys.stdout = original


def _format_value(value: Any) -> str:
    """Render one event field so the whole event stays on one greppable line."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, "g")
    if isinstance(value, str):
        simple = value and all(c.isprintable() and not c.isspace() and c not in '"=' for c in value)
        # Quote anything with spaces, quotes, "=" or line breaks; json.dumps escapes newlines, so
        # the line never breaks. ensure_ascii=False logs model text as returned.
        return value if simple else json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def event(name: str, **fields: Any) -> None:
    """Log one structured event line: ``event=<name> key=value ...`` at INFO level.

    Args:
        name: event name (see docs/AGENT.md for the vocabulary).
        **fields: event attributes, rendered in the given order.
    """
    parts = [f"event={name}"] + [f"{key}={_format_value(value)}" for key, value in fields.items()]
    LOGGER.info(" ".join(parts))
