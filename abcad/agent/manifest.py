"""
abcad.agent.manifest — the run manifest: a truthful, machine-readable record of every run.

PURPOSE
    Every run that has a run folder ends by writing ``<run folder>/run_manifest.json``, whatever
    the outcome (certified, honestly not approved, Phase-1 failure, or an internal error). The
    first block of keys keeps the names and meanings that downstream readers depend on (the
    mission-control dashboard reads ``approved``, ``ever_approved``,
    ``manufacturability.printable`` and ``manufacturability.deep_audit.autoscaled_variant.verdict``;
    a gold test asserts ``approved``, ``stl_path_scaled`` and the auto-scaled verdict). The second
    block is additive: schema version, terminal reason, certification summary, preflight, entry,
    counters, the router trace and the configuration snapshot.

SERIALIZATION
    JSON, indent 2, default ASCII escaping (an em dash is written as the six-character escape
    ``\\u2014``), values that are not JSON-serializable (e.g. ``pathlib.Path``) rendered with
    ``str()``, no trailing newline. Written atomically (temporary file + rename).

INPUTS / OUTPUTS
    build_manifest(state, settings=..., extras=...) -> ordered dict
    write_manifest(manifest, run_dir) -> path of run_manifest.json
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from abcad.agent.gate import classify_certification
from abcad.agent.settings import AgentSettings

MANIFEST_SCHEMA_VERSION = "abcad.agent.run-manifest/1"
MANIFEST_FILENAME = "run_manifest.json"


def build_manifest(
    state: Mapping[str, Any], *, settings: AgentSettings, extras: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble the manifest dict (keys in their documented order).

    Args:
        state: the final loop state.
        settings: the run's settings (for the configuration snapshot).
        extras: run facts that are not loop state: ``gate_preflight`` (dict), ``entry_chars``
            (int) and ``blender_version`` (str); missing entries are recorded as null.

    Returns:
        The manifest as an insertion-ordered dict.
    """
    manufacturability = state.get("manufacturability")
    best_artifact = state.get("best_artifact")
    config = settings.snapshot()
    config["blender_version"] = extras.get("blender_version")
    return {
        # ---- reference block (names and meanings are an external interface) -------------------
        "prompt": state.get("prompt"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),  # local time, no zone
        "use_code": state.get("entry_source"),
        "approved": bool(state.get("approved")),
        "ever_approved": bool(state.get("ever_approved")),
        "blender_status": state.get("exec_status"),
        "final_result": best_artifact,
        "stl_path": state.get("stl_path"),
        "stl_path_scaled": state.get("stl_path_scaled"),
        "mesh_stats": state.get("mesh_stats"),
        "manufacturability": manufacturability,
        "vlm_analysis": state.get("verdict"),
        "iteration_count": int(state.get("refine_count") or 0),
        "fix_attempts_used": int(state.get("repair_attempts") or 0),
        "stalled": bool(state.get("stalled")),
        # ---- additive block --------------------------------------------------------------------
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "terminal_reason": state.get("terminal_reason"),
        "terminal_detail": state.get("terminal_detail"),
        "critique_failed": bool(state.get("critique_failed")),
        "certification": classify_certification(
            manufacturability,
            gated_source_stl=state.get("gated_source_stl"),
            final_artifact=best_artifact,
        ),
        "size_normalization": state.get("size_normalization"),
        "gate_preflight": extras.get("gate_preflight"),
        "entry": {"origin": state.get("entry_origin"), "chars": extras.get("entry_chars")},
        "counters": {
            "critique_runs": int(state.get("critique_runs") or 0),
            "gate_runs": int(state.get("gate_runs") or 0),
            "repair_executions": int(state.get("repair_serial") or 0),
            "steps_taken": int(state.get("steps_taken") or 0),
        },
        "trace": list(state.get("trace") or []),
        "config": config,
    }


def write_manifest(manifest: Mapping[str, Any], run_dir: str) -> str:
    """Write ``run_manifest.json`` into ``run_dir`` atomically and return its path.

    Args:
        manifest: the manifest built by :func:`build_manifest`.
        run_dir: the run folder (created if missing).

    Returns:
        The absolute path of the written file.
    """
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(run_dir, MANIFEST_FILENAME))
    text = json.dumps(manifest, indent=2, default=str)  # ensure_ascii stays at its default (True)
    partial = path + ".partial"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, path)  # readers never see a half-written manifest
    return path
