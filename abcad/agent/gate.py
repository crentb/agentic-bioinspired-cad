"""
abcad.agent.gate — integration of the single-material manufacturability gate into the loop.

PURPOSE
    The gate itself lives in ``abcad.agent.manufacturability`` (the project's gate module, used
    unchanged). This module adapts it to the loop:

      * ``run_gate_preflight`` checks, before Phase 1 and WITHOUT importing anything heavy, that
        the deep-audit modules and their scientific dependencies can be imported. Otherwise the
        gate would silently fall back to its light check, and a light pass could be mistaken for
        a certification.
      * ``target_size_env`` bridges ``settings.target_size_mm`` to the ``ABCAD_TARGET_SIZE_MM``
        variable the gate reads, for exactly the duration of the gate call, so a keyword
        override works and a stale environment value can never resize a run whose settings say
        off.
      * ``GateStep`` never passes the loop state to the gate. It builds a fresh "gate view" dict
        with the key names the gate module expects, calls the node, and maps the results back.
      * ``classify_certification`` summarizes, for the manifest only, which artifact (if any) is
        certified and how. It is never used for routing.

INPUTS / OUTPUTS
    prepare_gate(settings) -> (ManufacturabilityNode, GatePreflight)
    GateStep(node, settings, preflight)(state) -> state update
    classify_certification(manufacturability, gated_source_stl=..., final_artifact=...) -> dict
"""

from __future__ import annotations

import copy
import importlib.util
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from abcad.agent import manufacturability
from abcad.agent.console import event
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

TARGET_SIZE_ENV = "ABCAD_TARGET_SIZE_MM"

# Modules the deep audit needs: the two audit helpers of this package and their scientific
# dependencies. They are only RESOLVED here (importlib.util.find_spec), never imported.
DEEP_AUDIT_MODULES: tuple[str, ...] = (
    "abcad.printing.print_audit",
    "abcad.printing.fdm_variants",
    "pyvista",
    "scipy",
    "vtk",
)


# --------------------------------------------------------------------------------------------------
# Preflight
# --------------------------------------------------------------------------------------------------
@dataclass
class GatePreflight:
    """Availability of the deep print audit, established before the run starts.

    Attributes:
        deep_audit_requested: the settings ask for the deep audit.
        deep_audit_available: every required module resolves.
        problems: one message per missing module.
    """

    deep_audit_requested: bool
    deep_audit_available: bool
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """The manifest's ``gate_preflight`` block."""
        return {
            "deep_audit_requested": self.deep_audit_requested,
            "deep_audit_available": self.deep_audit_available,
            "problems": list(self.problems),
        }


def run_gate_preflight(
    settings: AgentSettings, *, find_spec: Callable[[str], Any] | None = None
) -> GatePreflight:
    """Resolve (without importing) every module the deep audit needs.

    Args:
        settings: loop settings (``deep_audit`` decides whether the audit is requested).
        find_spec: resolver; defaults to ``importlib.util.find_spec`` (looked up at call time so
            tests can monkeypatch it).

    Returns:
        The :class:`GatePreflight`. A requested but unavailable audit is logged prominently.
    """
    resolve = find_spec or importlib.util.find_spec
    problems: list[str] = []
    for name in DEEP_AUDIT_MODULES:
        try:
            found = resolve(name) is not None
        except (ImportError, ValueError):  # a missing parent package raises instead of None
            found = False
        if not found:
            problems.append(f"missing module: {name}")
    preflight = GatePreflight(
        deep_audit_requested=settings.deep_audit,
        deep_audit_available=not problems,
        problems=problems,
    )
    event(
        "gate_preflight",
        requested=preflight.deep_audit_requested,
        available=preflight.deep_audit_available,
        problems=problems or None,
    )
    if preflight.deep_audit_requested and not preflight.deep_audit_available:
        LOGGER.warning(
            "DEEP PRINT AUDIT UNAVAILABLE (%s): approved designs would be judged by the light "
            "check only. Install the mesh dependencies or set ABCAD_REQUIRE_DEEP_AUDIT=1 to stop.",
            "; ".join(problems),
        )
    return preflight


def make_gate_node(settings: AgentSettings) -> manufacturability.ManufacturabilityNode:
    """The gate node for this run: process, build volume and deep-audit switch from settings."""
    return manufacturability.ManufacturabilityNode(
        process=settings.print_process,
        build_volume=manufacturability.BuildVolume(*settings.build_volume_mm),
        deep_audit=settings.deep_audit,
    )


def prepare_gate(
    settings: AgentSettings,
) -> tuple[manufacturability.ManufacturabilityNode, GatePreflight]:
    """Construct the gate node for this run and establish its preflight.

    Returns:
        ``(node, preflight)``.
    """
    return make_gate_node(settings), run_gate_preflight(settings)


# --------------------------------------------------------------------------------------------------
# Environment bridge
# --------------------------------------------------------------------------------------------------
@contextmanager
def target_size_env(settings: AgentSettings) -> Iterator[None]:
    """Set (or remove) ``ABCAD_TARGET_SIZE_MM`` from the settings during the block, then restore."""
    previous = os.environ.get(TARGET_SIZE_ENV)
    if settings.target_size_mm is None:
        os.environ.pop(TARGET_SIZE_ENV, None)
    else:
        os.environ[TARGET_SIZE_ENV] = repr(float(settings.target_size_mm))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(TARGET_SIZE_ENV, None)
        else:
            os.environ[TARGET_SIZE_ENV] = previous


# --------------------------------------------------------------------------------------------------
# Certification summary (record only)
# --------------------------------------------------------------------------------------------------
def classify_certification(
    manufacturability_verdict: Mapping[str, Any] | None,
    *,
    gated_source_stl: str | None,
    final_artifact: str | None,
) -> dict[str, Any]:
    """Summarize what the gate certified, for the manifest (never used for routing).

    Status: ``deep_print`` (printable with a deep audit), ``autoscaled_print`` (not printable but
    the auto-scaled variant was re-audited to PRINT), ``light_only_pass`` (printable without a
    deep audit), ``not_certified`` (a verdict exists otherwise), ``not_gated`` (no verdict).

    Args:
        manufacturability_verdict: the gate verdict dict, or None.
        gated_source_stl: the STL the gate was entered with.
        final_artifact: the run's best artifact.

    Returns:
        ``{"status", "artifact", "gated_source_stl", "matches_final"}``; ``matches_final`` is
        None unless both paths are known.
    """
    status, artifact = "not_gated", None
    if manufacturability_verdict is not None:
        deep = manufacturability_verdict.get("deep_audit")
        deep = deep if isinstance(deep, Mapping) else None
        variant = deep.get("autoscaled_variant") if deep else None
        variant = variant if isinstance(variant, Mapping) else None
        printable = manufacturability_verdict.get("printable") is True
        if printable and deep is not None:
            status, artifact = "deep_print", deep.get("stl")
        elif not printable and variant is not None and variant.get("verdict") == "PRINT":
            status, artifact = "autoscaled_print", variant.get("stl")
        elif printable:
            status, artifact = "light_only_pass", gated_source_stl
        else:
            status = "not_certified"
    matches = (
        gated_source_stl == final_artifact
        if gated_source_stl is not None and final_artifact is not None
        else None
    )
    return {
        "status": status,
        "artifact": artifact,
        "gated_source_stl": gated_source_stl,
        "matches_final": matches,
    }


# --------------------------------------------------------------------------------------------------
# The loop step
# --------------------------------------------------------------------------------------------------
class GateStep:
    """Loop step ``gate``: run the manufacturability node on a fresh gate view.

    Args:
        node: the gate node (``ManufacturabilityNode`` or a compatible callable).
        settings: loop settings (target size).
        preflight: the run's gate preflight (kept for the record).
    """

    def __init__(
        self, node: Callable[[dict], dict], settings: AgentSettings, preflight: GatePreflight
    ) -> None:
        self._node = node
        self._settings = settings
        self.preflight = preflight

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Gate the approved design and return the state update."""
        source_stl = state.get("stl_path")
        # The gate view: exactly the keys the gate module reads (it mutates this dict in place).
        view: dict[str, Any] = {
            "mesh_stats": copy.deepcopy(state.get("mesh_stats")),
            "stl_path": source_stl,
            "vlm_feedback": state.get("feedback"),
            "iteration_count": int(state.get("refine_count") or 0),
        }
        with target_size_env(self._settings):
            result = self._node(view)  # prints a summary line; the run-log tee captures it
        result = view if result is None else result

        verdict = result.get("manufacturability")
        update: dict[str, Any] = {
            "gated_source_stl": source_stl,
            "manufacturability": verdict,
            "manufacturable": result.get("manufacturable"),
            "feedback": result.get("vlm_feedback"),
            "stl_path": result.get("stl_path"),
            "gate_runs": int(state.get("gate_runs") or 0) + 1,
        }
        for key in ("size_normalization", "stl_path_scaled"):
            if key in result:  # copied only when the gate wrote them
                update[key] = result[key]

        verdict = verdict or {}
        deep = verdict.get("deep_audit") or {}
        variant = deep.get("autoscaled_variant") or {}
        violations = [v.get("type") for v in verdict.get("violations", []) if isinstance(v, dict)]
        LOGGER.info(
            "gate: printable=%s violations=%s deep=%s max_formable=%s",
            verdict.get("printable"),
            violations,
            deep.get("verdict"),
            deep.get("max_formable_d_mm"),
        )
        event(
            "gate_done",
            printable=verdict.get("printable"),
            violations=violations,
            deep_verdict=deep.get("verdict"),
            max_formable_d_mm=deep.get("max_formable_d_mm"),
            scaled_variant=variant.get("stl"),
            scaled_verdict=variant.get("verdict"),
        )
        return update
