"""
abcad.agent.ingest — the entry step: execute the Phase-1 (or --use-code) script once.

PURPOSE
    Normalizes the entry script once at construction and, when called, executes it under the
    label ``initial``. The execution fields of the state are copied from the report; on success
    the script becomes the last good script and its STL (else its render) the best artifact. The
    step always sets ``approved = False``: nothing has been critiqued yet.

INPUTS / OUTPUTS
    IngestStep(script, executor)(state) -> state update (a new dict).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from abcad.agent.blender import BlenderExecutor, ExecutionReport
from abcad.agent.scripttext import normalize_script


def execution_fields(report: ExecutionReport) -> dict[str, Any]:
    """The state fields copied from every execution report (shared by ingest, repair, refine)."""
    return {
        "exec_status": report.status,
        "exec_error": report.error,
        "render_png": report.render_png,
        "mesh_stats": report.mesh_stats,
        "stl_path": report.stl_path,
    }


class IngestStep:
    """Loop step ``ingest``.

    Args:
        script: the entry script (emitted or read from --use-code); normalized once here.
        executor: the Blender executor.
    """

    LABEL = "initial"

    def __init__(self, script: str, executor: BlenderExecutor) -> None:
        self.script = normalize_script(script)
        self._executor = executor

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Execute the entry script and return the state update."""
        report = self._executor.execute(self.script, label=self.LABEL, run_dir=state["run_dir"])
        update: dict[str, Any] = {
            "entry_script": self.script,
            "last_script": self.script,
            "approved": False,
            **execution_fields(report),
        }
        if report.ok:
            update["last_good_script"] = self.script
            update["best_artifact"] = report.stl_path or report.render_png
        return update
