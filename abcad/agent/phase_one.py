"""
abcad.agent.phase_one — Phase-1 process isolation: the LoRA emit runs in a child that exits.

PURPOSE
    A single process cannot hold the PyTorch generator and also drive the Ollama critic, the
    repair loop and Blender within 16 GB of unified memory: even after the adapter weights are
    dropped, the PyTorch/Metal runtime keeps gigabytes resident. Exiting the process is the only
    reliable way to return that memory, so Phase 1 runs in a child process:

      parent (emit_via_child)                     child (child_main)
      1. delete a stale hand-off file             1. build the embedder + exemplar index
      2. start `python -m abcad.agent             2. load the emitter, emit
         --emit-code <handoff> <prompt>`          3. write the script atomically to <handoff>
         in its own process group                 4. unload, exit 0 (any exception: exit 1)
      3. forward the child's output to the log
      4. wait (timeout -> kill the group)
      5. read and return the hand-off file

    The parent builds no Phase-2 component until the child has exited, so the two phases never
    overlap in memory.

INPUTS / OUTPUTS
    emit_via_child(prompt, settings, log=...) -> the script text, or EmitFailed / EmitEmpty.
    child_main(prompt, settings, handoff_path=..., smoke=...) -> process exit code.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from typing import IO, Any

from abcad.agent.console import event
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

# Characters of the completion printed by --smoke.
SMOKE_EXCERPT_CHARS = 1200


class EmitFailed(RuntimeError):
    """The Phase-1 child exited non-zero or timed out (message: "exit <code>" or "timeout")."""


class EmitEmpty(RuntimeError):
    """The hand-off script is missing, empty, or whitespace only."""


# --------------------------------------------------------------------------------------------------
# Parent side
# --------------------------------------------------------------------------------------------------
def child_command(prompt: str, handoff_path: str) -> list[str]:
    """Argument vector of the Phase-1 child (no shell is involved)."""
    return [sys.executable, "-m", "abcad.agent", "--emit-code", handoff_path, prompt]


def _kill_process_group(process: Any) -> None:
    """Kill the child's whole process group (the child is its group leader).

    Falls back to killing the single process where process groups are unavailable.
    """
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - non-POSIX hosts
            process.kill()
    except ProcessLookupError:  # already gone
        pass


class _ParentTerminated(SystemExit):
    """SIGTERM or SIGHUP delivered to the parent while it waits on the Phase-1 child.

    A SystemExit (exit status 128 + signal number, the shell convention), so it unwinds the
    wait, lets the child's process group be killed, and ends the process without a traceback.
    """


def _raise_terminated(signum: int, _frame: Any) -> None:
    """Signal handler installed during the wait: turn the signal into ``_ParentTerminated``."""
    raise _ParentTerminated(128 + signum)


def _pump_lines(stream: IO[str], log: Callable[[str], None]) -> None:
    """Forward each line of ``stream`` to ``log`` until the stream closes (reader thread)."""
    for line in stream:
        log(line.rstrip("\r\n"))


def emit_via_child(
    prompt: str,
    settings: AgentSettings,
    *,
    log: Callable[[str], None],
    popen: Callable[..., Any] = subprocess.Popen,
) -> str:
    """Run the Phase-1 emit in a child process and return the generated script.

    Args:
        prompt: the design request.
        settings: loop settings; the child receives them as ``ABCAD_*`` variables.
        log: receives every output line of the child (forwarded to the run log).
        popen: process factory (``subprocess.Popen``); injectable for tests.

    Returns:
        The script text written by the child.

    Raises:
        EmitFailed: non-zero exit (``"exit <code>"``) or timeout (``"timeout"``).
        EmitEmpty: the hand-off file is missing or blank after the child exited.
    """
    handoff = settings.paths.handoff_path
    # A stale file from an earlier run must never pass for fresh output.
    if os.path.exists(handoff):
        os.remove(handoff)
    os.makedirs(os.path.dirname(handoff), exist_ok=True)

    env = dict(os.environ)
    env.update(settings.to_env())  # the child sees exactly the parent's configuration
    env["PYTHONUNBUFFERED"] = "1"  # line-by-line forwarding needs an unbuffered child

    argv = child_command(prompt, handoff)
    started = time.perf_counter()
    event("phase1_start", prompt=prompt, handoff=handoff, timeout_s=settings.emit_timeout_s)
    process = popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # one ordered stream: tracebacks stay next to their context
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,  # own process group, so a timeout can kill everything it spawned
    )
    reader = threading.Thread(target=_pump_lines, args=(process.stdout, log), daemon=True)
    reader.start()
    # The child runs in its own session, so a signal sent to the parent's process group (a
    # supervisor, a watchdog, a closed terminal) never reaches it, and an orphaned emitter would
    # keep its model weights (about 8 GB) resident. While the parent waits, SIGTERM and SIGHUP
    # become an exception, and any exit from the wait other than a normal return or the timeout
    # path kills the child's group first. Signal handlers can only be set from the main thread.
    previous: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
            if signum is not None:
                previous[signum] = signal.signal(signum, _raise_terminated)
    try:
        return_code = process.wait(timeout=settings.emit_timeout_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL makes this unreachable
            pass
        reader.join(timeout=5)
        event("phase1_failed", reason="timeout", seconds=round(time.perf_counter() - started, 1))
        raise EmitFailed("timeout") from None
    except BaseException:  # Ctrl-C, SIGTERM/SIGHUP, or any other abort of the wait
        _kill_process_group(process)
        event("phase1_failed", reason="parent interrupted")
        raise
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    reader.join(timeout=5)
    if return_code != 0:
        event("phase1_failed", reason=f"exit {return_code}")
        raise EmitFailed(f"exit {return_code}")

    try:
        with open(handoff, encoding="utf-8") as handle:
            script = handle.read()
    except FileNotFoundError:
        event("phase1_failed", reason="no hand-off file")
        raise EmitEmpty(f"the child exited 0 but wrote no hand-off file: {handoff}") from None
    if not script.strip():
        event("phase1_failed", reason="empty script")
        raise EmitEmpty(f"the hand-off file is empty: {handoff}")
    seconds = time.perf_counter() - started
    event("phase1_done", chars=len(script), seconds=round(seconds, 1))
    LOGGER.info("Phase 1 produced %d characters in %.1f s", len(script), seconds)
    return script


# --------------------------------------------------------------------------------------------------
# Child side
# --------------------------------------------------------------------------------------------------
def _write_atomically(path: str, text: str) -> None:
    """Write ``text`` to ``path + '.partial'`` and rename it onto ``path`` (never half-written)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, path)


def _default_emitter_factory(settings: AgentSettings) -> Any:
    """Build the production emitter with its own embedder and exemplar index (child only)."""
    from abcad.agent.emitter import LoraCodeEmitter  # imported in the child only
    from abcad.agent.retrieval import ExemplarIndex, SentenceEmbedder

    embedder = SentenceEmbedder(
        settings.embed_model, settings.embed_revision, settings.embed_device
    )
    exemplars = ExemplarIndex.from_corpora(
        settings.text_corpora, embedder, enabled=settings.rag_enabled
    )
    return LoraCodeEmitter(settings, exemplars)


def child_main(
    prompt: str,
    settings: AgentSettings,
    *,
    handoff_path: str | None,
    smoke: bool,
    emitter_factory: Callable[[AgentSettings], Any] | None = None,
) -> int:
    """Phase-1 worker: emit one script, optionally write it and/or print a smoke excerpt.

    Args:
        prompt: the design request.
        settings: loop settings.
        handoff_path: file to write the script to (atomically), or None.
        smoke: print the first 1200 characters of the raw completion.
        emitter_factory: builds the emitter (injectable for tests).

    Returns:
        0 on success, 1 on any exception (the traceback is printed).
    """
    emitter = None
    try:
        factory = emitter_factory or _default_emitter_factory
        emitter = factory(settings)
        emitter.load()
        result = emitter.emit(prompt, mode=settings.emit_mode)
        if handoff_path:
            _write_atomically(handoff_path, result.script)
            LOGGER.info("wrote %d characters to %s", len(result.script), handoff_path)
        else:
            LOGGER.info("emitted %d characters", len(result.script))
        if smoke:
            print(result.completion[:SMOKE_EXCERPT_CHARS], flush=True)
        return 0
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if emitter is not None:
            try:
                emitter.unload()  # release order: references, garbage, MPS cache, then exit
            except Exception:  # unloading must never mask the emit outcome
                LOGGER.warning("emitter unload failed", exc_info=True)
