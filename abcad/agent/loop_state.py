"""
abcad.agent.loop_state — the shared state of one design-loop run and its update discipline.

PURPOSE
    ``LoopState`` is a flat mapping of JSON-serializable values (str, int, float, bool, None and
    lists / dicts of those) that the runner threads through the steps. Two rules keep the record
    truthful:

    * Steps never mutate their input. Each step receives a read-only view (or a copy) and returns
      an *update*, a mapping of the fields it changed; the runner merges it with ``merge_update``
      (last writer wins).
    * Routers are pure: they read the merged state and decide the next step, but never write.
      Every field that the run manifest reports is therefore maintained by a step.

INPUTS / OUTPUTS
    ``initial_state(prompt, run_dir, entry_origin=..., entry_source=...)`` -> a complete state with
    every boolean and counter set explicitly and every optional field set to None.
    ``merge_update(state, update)`` -> a NEW dict; an unknown key raises KeyError (catches typos
    in step updates before they silently create stray fields).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict


class LoopState(TypedDict, total=False):
    """Fields of the loop state. The manifest key of each reported field is given in docs/AGENT.md."""

    # ---- identity of the run (written once by the runner) ----------------------------------------
    prompt: str  # the design request
    run_dir: str  # absolute run folder; every execution writes its files here
    entry_origin: Literal["lora", "use-code"]  # where the entry script came from
    entry_source: str | None  # the --use-code path exactly as given (None for "lora")

    # ---- scripts ---------------------------------------------------------------------------------
    entry_script: str | None  # the normalized entry script (ingest)
    last_script: str | None  # the most recently EXECUTED script (the base of the next repair)
    last_good_script: str | None  # the most recent script that executed successfully (refine base)

    # ---- latest execution (copied from each ExecutionReport) -------------------------------------
    exec_status: Literal["success", "failed"] | None
    exec_error: str | None  # error excerpt shown verbatim to the repair model
    render_png: str | None
    mesh_stats: dict[str, Any] | None  # {"bbox_mm": [x, y, z], "overhang_area_frac": f}
    stl_path: str | None  # may be replaced by the gate's "<stem>_sized.stl"
    best_artifact: str | None  # latest good geometry, STL preferred over the render

    # ---- critique --------------------------------------------------------------------------------
    verdict: dict[str, Any] | None  # last parsed verdict (kept when a later critique fails)
    feedback: str | None  # verdict text or failure text, plus appended gate suggestions
    critique_failed: bool
    approved: bool  # verdict of the most recent critique
    ever_approved: bool  # latch: true once any critique approved; never reset

    # ---- repair ----------------------------------------------------------------------------------
    repair_ok: bool
    repair_attempts: int  # index of the latest executed attempt in the latest repair visit
    repair_serial: int  # run-wide count of executed repair candidates (labels fix_run_<n>)
    refuted_digests: list[str]  # run-wide ledger of scripts known to fail

    # ---- refine ----------------------------------------------------------------------------------
    refine_count: int  # incremented at the start of every refine visit (skips included)
    design_digests: list[str]  # digests of every refine candidate, in order
    stalled: bool  # the latest refine candidate repeated an earlier one verbatim

    # ---- manufacturability gate ------------------------------------------------------------------
    manufacturability: dict[str, Any] | None  # the gate verdict, verbatim
    manufacturable: bool | None
    stl_path_scaled: str | None  # certified auto-scaled variant (None when absent or failing)
    size_normalization: dict[str, Any] | None
    gated_source_stl: str | None  # stl_path at gate entry, before any normalization
    gate_runs: int
    critique_runs: int

    # ---- runner bookkeeping ----------------------------------------------------------------------
    last_step: str | None
    steps_taken: int
    trace: list[dict[str, Any]]  # [{"step", "next", "reason"}] one entry per executed step
    terminal_reason: str | None
    terminal_detail: str | None


# Every legal key; merge_update() rejects anything else.
STATE_KEYS: frozenset[str] = frozenset(LoopState.__annotations__)

# Optional fields start as None (nothing is left absent, so the manifest never has to
# guess between "missing" and "null").
_OPTIONAL_FIELDS: tuple[str, ...] = (
    "entry_script",
    "last_script",
    "last_good_script",
    "exec_status",
    "exec_error",
    "render_png",
    "mesh_stats",
    "stl_path",
    "best_artifact",
    "verdict",
    "feedback",
    "manufacturability",
    "manufacturable",
    "stl_path_scaled",
    "size_normalization",
    "gated_source_stl",
    "last_step",
    "terminal_reason",
    "terminal_detail",
)


def initial_state(
    prompt: str,
    run_dir: str,
    *,
    entry_origin: Literal["lora", "use-code"],
    entry_source: str | None,
) -> LoopState:
    """Create the state a run starts from.

    Args:
        prompt: the design request.
        run_dir: absolute path of the run folder.
        entry_origin: ``"lora"`` for a Phase-1 emit, ``"use-code"`` for a saved script.
        entry_source: the ``--use-code`` path exactly as given, or None.

    Returns:
        A complete ``LoopState``: booleans False, counters 0, lists empty, optional fields None.
    """
    if entry_origin not in ("lora", "use-code"):
        raise ValueError(f"entry_origin must be 'lora' or 'use-code', got {entry_origin!r}")
    state: dict[str, Any] = {name: None for name in _OPTIONAL_FIELDS}
    state.update(
        prompt=prompt,
        run_dir=run_dir,
        entry_origin=entry_origin,
        entry_source=entry_source,
        approved=False,
        ever_approved=False,
        critique_failed=False,
        repair_ok=False,
        repair_attempts=0,
        repair_serial=0,
        refine_count=0,
        stalled=False,
        refuted_digests=[],
        design_digests=[],
        gate_runs=0,
        critique_runs=0,
        steps_taken=0,
        trace=[],
    )
    return state  # type: ignore[return-value]


def merge_update(state: Mapping[str, Any], update: Mapping[str, Any]) -> LoopState:
    """Return a new state with ``update`` applied on top of ``state`` (last writer wins).

    Args:
        state: the current state (not modified).
        update: fields to overwrite.

    Returns:
        A new dict.

    Raises:
        KeyError: ``update`` contains a key that is not a ``LoopState`` field.
    """
    unknown = sorted(key for key in update if key not in STATE_KEYS)
    if unknown:
        raise KeyError(f"unknown LoopState field(s): {', '.join(unknown)}")
    merged: dict[str, Any] = dict(state)
    merged.update(update)
    return merged  # type: ignore[return-value]
