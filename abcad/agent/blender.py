"""
abcad.agent.blender — run candidate scripts in headless Blender and parse the harness protocol.

PURPOSE
    ``BlenderExecutor.execute(script, label, run_dir)`` is the only place where model-generated
    code runs, and it runs in a separate Blender process:

      1. write ``<run_dir>/<label>_generated.py`` (kept: the exact script that ran)
      2. write the job file ``<tmp_dir>/<label>_job.json`` (paths, output names, render settings)
      3. run ``[blender, "-b", "--python", <blender_harness.py>, "--", <job>]`` in its own process
         group with a hard timeout (on timeout the whole group is killed)
      4. write stdout + stderr to ``<run_dir>/<label>_blender.log``
      5. parse the stdout protocol (see blender_harness.py) into an ``ExecutionReport``

    Success is decided by the ``ABCAD_EXEC: OK`` marker, not by the exit code (which is recorded).
    The executor never raises for script, Blender or timeout failures: they become
    ``status="failed"`` reports with an error excerpt the repair model can act on.

INPUTS / OUTPUTS
    Input: a script (str), a label (``initial``, ``fix_run_<n>``, ``design_iter_<k>``), a run folder.
    Output: ``ExecutionReport``; files in the run folder: ``<label>_generated.py``,
    ``render_<label>.png`` (on success), ``geom_<label>.stl`` (on export) and
    ``<label>_blender.log``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from abcad.agent.console import event
from abcad.agent.scripttext import first_line
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

JOB_SCHEMA = "abcad.agent.blender-job/1"
HARNESS_PATH = str(Path(__file__).resolve().with_name("blender_harness.py"))

# Protocol patterns (one marker per line, at the start of the line).
_MESH_STATS = re.compile(r"^MESH_STATS:\s*(\{.*\})")
_STL_PATH = re.compile(r"^STL_PATH:\s*(.+)")
_EXEC_OK = "ABCAD_EXEC: OK"
_EXEC_FAIL = "ABCAD_EXEC: FAIL "
_BLENDER_VERSION = "ABCAD_BLENDER: "
# Lines that end the multi-line exception text after an ABCAD_EXEC: FAIL marker.
_STOP_PREFIXES = ("ABCAD_", "MESH_STATS:", "STL_PATH:", "Blender quit")

_EXCERPT_MAX_LINES = 15  # exception text lines kept after the FAIL marker
_TAIL_LINES = 20  # output tail used when no FAIL marker exists


# --------------------------------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------------------------------
@dataclass
class HarnessOutput:
    """What the stdout protocol says about one execution."""

    ok: bool
    fail_message: str | None
    mesh_stats: dict[str, Any] | None
    stl_path: str | None
    blender_version: str | None


@dataclass
class ExecutionReport:
    """Outcome of one Blender execution.

    Attributes:
        label: execution label (``initial``, ``fix_run_<n>``, ``design_iter_<k>``).
        ok: True exactly when ``status == "success"``.
        status: ``"success"`` or ``"failed"``.
        render_png: the render, set only when the file exists.
        stl_path: the exported STL, set only when the harness reported it and it exists.
        mesh_stats: parsed MESH_STATS payload, or None.
        error: error excerpt ("" on success).
        exit_code: Blender's exit code (None when it never ran or timed out).
        timed_out: True when the hard timeout killed the run.
        seconds: wall time of the Blender process.
        script_copy: path of the executed ``<label>_generated.py``.
        blender_log: path of ``<label>_blender.log``.
        blender_version: version reported by the harness, if any.
    """

    label: str
    ok: bool
    status: Literal["success", "failed"]
    render_png: str | None
    stl_path: str | None
    mesh_stats: dict[str, Any] | None
    error: str
    exit_code: int | None
    timed_out: bool
    seconds: float
    script_copy: str
    blender_log: str
    blender_version: str | None


# --------------------------------------------------------------------------------------------------
# Protocol parsing
# --------------------------------------------------------------------------------------------------
def parse_harness_output(stdout: str, stderr: str) -> HarnessOutput:
    """Parse the harness's stdout protocol.

    Rules: the first ``MESH_STATS:`` line is parsed as JSON (a parse error gives None); the first
    ``STL_PATH:`` line is accepted only if that file exists; ``ABCAD_EXEC: OK`` means success
    unless a FAIL marker is also present.

    Args:
        stdout: harness standard output.
        stderr: harness standard error (not used for markers; kept for symmetry).

    Returns:
        The parsed :class:`HarnessOutput`.
    """
    mesh_stats: dict[str, Any] | None = None
    stl_path: str | None = None
    version: str | None = None
    ok_seen = False
    fail_message: str | None = None
    stats_seen = stl_seen = False
    for line in stdout.splitlines():
        if not stats_seen:
            match = _MESH_STATS.match(line)
            if match:
                stats_seen = True
                try:
                    parsed = json.loads(match.group(1))
                    mesh_stats = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    mesh_stats = None
                continue
        if not stl_seen:
            match = _STL_PATH.match(line)
            if match:
                stl_seen = True
                candidate = match.group(1).strip()
                stl_path = candidate if os.path.isfile(candidate) else None
                continue
        if line.rstrip() == _EXEC_OK:
            ok_seen = True
        elif line.startswith(_EXEC_FAIL) and fail_message is None:
            fail_message = line[len(_EXEC_FAIL) :]
        elif line.startswith(_BLENDER_VERSION) and version is None:
            version = line[len(_BLENDER_VERSION) :].strip() or None
    return HarnessOutput(
        ok=ok_seen and fail_message is None,
        fail_message=fail_message,
        mesh_stats=mesh_stats,
        stl_path=stl_path,
        blender_version=version,
    )


def error_excerpt(stdout: str, stderr: str) -> str:
    """The error text shown verbatim to the repair model.

    With an ``ABCAD_EXEC: FAIL `` marker: the text after the marker up to the next protocol
    marker line (``ABCAD_``, ``MESH_STATS:``, ``STL_PATH:``) or a ``Blender quit`` line, at most 15
    lines, stripped (in practice the exception message). Otherwise the last 20 lines of stdout,
    or of stderr when stdout is empty.

    Args:
        stdout: harness standard output.
        stderr: harness standard error.

    Returns:
        The excerpt (possibly empty).
    """
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(_EXEC_FAIL):
            collected = [line[len(_EXEC_FAIL) :]]
            for following in lines[index + 1 :]:
                if following.startswith(_STOP_PREFIXES):
                    break
                collected.append(following)
            return "\n".join(collected[:_EXCERPT_MAX_LINES]).strip()
    source = stdout if stdout.strip() else stderr
    return "\n".join(source.splitlines()[-_TAIL_LINES:]).strip()


# --------------------------------------------------------------------------------------------------
# Process runner (default): subprocess with its own process group and a group kill on timeout
# --------------------------------------------------------------------------------------------------
def _as_text(value: Any) -> str:
    """Partial output of a timed-out process may arrive as bytes even in text mode."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_in_process_group(
    args: list[str],
    *,
    timeout: float,
    capture_output: bool = True,
    text: bool = True,
    encoding: str = "utf-8",
    errors: str = "replace",
    start_new_session: bool = True,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` look-alike that kills the whole process group on timeout.

    Blender may spawn helper processes; killing only the direct child could leave them holding
    memory. The child is started as a session and group leader, so ``killpg`` reaches everything
    it spawned.

    Raises:
        subprocess.TimeoutExpired: after the group was killed, carrying any partial output.
    """
    pipe = subprocess.PIPE if capture_output else None
    with subprocess.Popen(
        args,
        stdout=pipe,
        stderr=pipe,
        text=text,
        encoding=encoding,
        errors=errors,
        start_new_session=start_new_session,
    ) as process:
        try:
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                if hasattr(os, "killpg") and start_new_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover - non-POSIX hosts
                    process.kill()
            except ProcessLookupError:
                pass
            try:
                out, err = process.communicate(timeout=30)  # collect output written so far
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL makes this unreachable
                out, err = "", ""
            raise subprocess.TimeoutExpired(args, timeout, output=out, stderr=err) from None
        return subprocess.CompletedProcess(args, process.returncode, out, err)


# --------------------------------------------------------------------------------------------------
# The executor
# --------------------------------------------------------------------------------------------------
class BlenderExecutor:
    """Executes candidate scripts in headless Blender (see the module docstring).

    Args:
        settings: loop settings (Blender path, timeout, render settings, output folders).
        process_runner: callable with ``subprocess.run``'s calling convention; the default kills
            the whole process group on timeout. Tests inject a fake.

    Attributes:
        blender_version: the last version string the harness reported (for the manifest).
    """

    def __init__(
        self,
        settings: AgentSettings,
        *,
        process_runner: Callable[..., Any] = run_in_process_group,
    ) -> None:
        self._settings = settings
        self._run = process_runner
        self.blender_version: str | None = None

    def command(self, job_path: str) -> list[str]:
        """The Blender argument vector for one job (no shell; no --factory-startup)."""
        return [self._settings.blender_path, "-b", "--python", HARNESS_PATH, "--", job_path]

    def execute(self, script: str, *, label: str, run_dir: str) -> ExecutionReport:
        """Execute ``script`` under ``label`` and return the report (never raises for failures).

        Args:
            script: the (normalized) candidate script.
            label: execution label; names every file of this execution.
            run_dir: run folder receiving the script copy, render, STL and log.

        Returns:
            The :class:`ExecutionReport`.
        """
        settings = self._settings
        tmp_dir = settings.paths.tmp_dir
        run_dir = os.path.abspath(run_dir)
        os.makedirs(run_dir, exist_ok=True)
        os.makedirs(tmp_dir, exist_ok=True)

        # ---- 1-2: the executed copy of the script and the job file -----------------------------
        script_copy = os.path.join(run_dir, f"{label}_generated.py")
        with open(script_copy, "w", encoding="utf-8") as handle:
            handle.write(script)
        job_path = os.path.join(tmp_dir, f"{label}_job.json")
        job = {
            "schema": JOB_SCHEMA,
            "label": label,
            "script_path": script_copy,
            "output_dir": run_dir,
            "render_filename": f"render_{label}.png",
            "stl_filename": f"geom_{label}.stl",
            "resolution": list(settings.render_resolution),
            "samples": settings.render_samples,
        }
        with open(job_path, "w", encoding="utf-8") as handle:
            json.dump(job, handle, indent=2)

        # ---- 3: run Blender --------------------------------------------------------------------
        event("exec_start", label=label)
        stdout = stderr = ""
        exit_code: int | None = None
        timed_out = False
        launch_error: str | None = None
        started = time.perf_counter()
        try:
            completed = self._run(
                self.command(job_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=settings.blender_timeout_s,
                start_new_session=True,
            )
            stdout, stderr = _as_text(completed.stdout), _as_text(completed.stderr)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout, stderr = _as_text(exc.output), _as_text(exc.stderr)
        except OSError as exc:  # Blender missing or not executable
            launch_error = f"could not start Blender ({settings.blender_path}): {exc}"
        seconds = time.perf_counter() - started

        # ---- 4: the per-execution Blender log --------------------------------------------------
        blender_log = os.path.join(run_dir, f"{label}_blender.log")
        with open(blender_log, "w", encoding="utf-8") as handle:
            handle.write(stdout)
            handle.write("\n----- stderr -----\n")
            handle.write(stderr)

        # ---- 5: parse ---------------------------------------------------------------------------
        parsed = parse_harness_output(stdout, stderr)
        if parsed.blender_version:
            self.blender_version = parsed.blender_version
        render_png = os.path.join(run_dir, f"render_{label}.png")
        ok = parsed.ok and not timed_out and launch_error is None
        if timed_out:
            error = f"Blender timed out after {settings.blender_timeout_s:g} s"
        elif launch_error is not None:
            error = launch_error
        elif not ok:
            error = error_excerpt(stdout, stderr) or f"Blender exited with code {exit_code}"
        else:
            error = ""

        if not settings.keep_temp:
            try:
                os.remove(job_path)
            except FileNotFoundError:
                pass

        report = ExecutionReport(
            label=label,
            ok=ok,
            status="success" if ok else "failed",
            render_png=render_png if os.path.isfile(render_png) else None,
            stl_path=parsed.stl_path,
            mesh_stats=parsed.mesh_stats,
            error=error,
            exit_code=exit_code,
            timed_out=timed_out,
            seconds=seconds,
            script_copy=script_copy,
            blender_log=blender_log,
            blender_version=parsed.blender_version,
        )
        event(
            "exec_done",
            label=label,
            status=report.status,
            seconds=round(seconds, 1),
            error=first_line(error) if error else None,
        )
        if not ok:
            LOGGER.info("execution %s failed: %s", label, first_line(error))
        return report
