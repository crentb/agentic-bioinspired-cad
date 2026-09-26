"""
abcad.agent.routing — pure routing functions of the design-loop state machine.

PURPOSE
    After every step the runner asks the step's router where to go next. Routers are PURE: they
    read the merged state and return a ``Decision``; they never write state (writes made during
    routing were silently discarded by an earlier graph framework, which once ended a run with no
    final artifact despite four good renders). Each table below is evaluated top to bottom and the
    first matching row wins.

    after_ingest     exec failed -> repair | otherwise -> critique
    after_repair     repair_ok -> critique | otherwise -> END repair_failed
    after_refine     exec failed -> repair | otherwise (ok, skip, no code) -> critique
    after_critique   approved + gate verdict exists -> END approved_gated (the gate runs once)
                     approved -> gate
                     exec failed -> repair (defensive; unreachable in practice)
                     critique_failed -> END critique_failed
                     stalled -> END stalled
                     refine_count >= max_iter -> END iteration_cap
                     otherwise -> refine
    after_gate       printable -> END certified
                     auto-scaled variant verdict PRINT -> END certified
                     gate module says "end" (budget spent) -> END iteration_cap_after_gate
                     otherwise -> refine

INPUTS / OUTPUTS
    Each router takes the (read-only) state mapping, plus ``max_iter`` where relevant, and returns
    a ``Decision(next, reason)``; ``reason`` is set exactly when ``next == END``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from abcad.agent.manufacturability import route_after_manufacturability

# ---- step names and the terminal sentinel --------------------------------------------------------
INGEST = "ingest"
CRITIQUE = "critique"
REPAIR = "repair"
REFINE = "refine"
GATE = "gate"
STEP_NAMES: tuple[str, ...] = (INGEST, CRITIQUE, REPAIR, REFINE, GATE)
END = "__end__"

# ---- terminal-reason vocabulary ------------------------------------------------------------------
# Router decisions (the run of the tool succeeded, whatever the design outcome):
CERTIFIED = "certified"
APPROVED_GATED = "approved_gated"
ITERATION_CAP_AFTER_GATE = "iteration_cap_after_gate"
CRITIQUE_FAILED = "critique_failed"
STALLED = "stalled"
ITERATION_CAP = "iteration_cap"
REPAIR_FAILED = "repair_failed"
# Runner and Phase-1 outcomes (the tool itself did not complete normally):
STEP_LIMIT = "step_limit"
EMIT_FAILED = "emit_failed"
EMIT_EMPTY = "emit_empty"
ERROR = "error"

TERMINAL_REASONS: frozenset[str] = frozenset(
    {
        CERTIFIED,
        APPROVED_GATED,
        ITERATION_CAP_AFTER_GATE,
        CRITIQUE_FAILED,
        STALLED,
        ITERATION_CAP,
        REPAIR_FAILED,
        STEP_LIMIT,
        EMIT_FAILED,
        EMIT_EMPTY,
        ERROR,
    }
)


@dataclass(frozen=True)
class Decision:
    """Routing decision: the next step name, or ``END`` with a terminal reason."""

    next: str
    reason: str | None = None

    def __post_init__(self) -> None:
        """Enforce the invariant: a reason is given exactly when the run ends."""
        if (self.next == END) != (self.reason is not None):
            raise ValueError(f"invalid decision: next={self.next!r} reason={self.reason!r}")
        if self.reason is not None and self.reason not in TERMINAL_REASONS:
            raise ValueError(f"unknown terminal reason {self.reason!r}")


def _succeeded(state: Mapping[str, Any]) -> bool:
    """True when the latest execution succeeded."""
    return state.get("exec_status") == "success"


def after_ingest(state: Mapping[str, Any]) -> Decision:
    """A failed initial execution has no render, so it goes to repair, never to the critic."""
    return Decision(CRITIQUE) if _succeeded(state) else Decision(REPAIR)


def after_repair(state: Mapping[str, Any]) -> Decision:
    """A successful repair is critiqued; an exhausted repair ends the run."""
    if state.get("repair_ok") is True:
        return Decision(CRITIQUE)
    return Decision(END, REPAIR_FAILED)


def after_refine(state: Mapping[str, Any]) -> Decision:
    """A broken refine goes to repair; everything else (including skips) is critiqued."""
    return Decision(CRITIQUE) if _succeeded(state) else Decision(REPAIR)


def after_critique(state: Mapping[str, Any], *, max_iter: int) -> Decision:
    """Route after a critique (see the module table)."""
    approved = bool(state.get("approved"))
    if approved and state.get("manufacturability") is not None:
        return Decision(END, APPROVED_GATED)
    if approved:
        return Decision(GATE)
    if not _succeeded(state):
        return Decision(REPAIR)
    if state.get("critique_failed"):
        return Decision(END, CRITIQUE_FAILED)
    if state.get("stalled"):
        return Decision(END, STALLED)
    if int(state.get("refine_count") or 0) >= max_iter:
        return Decision(END, ITERATION_CAP)
    return Decision(REFINE)


def _autoscaled_verdict(verdict: Mapping[str, Any] | None) -> Any:
    """``verdict["deep_audit"]["autoscaled_variant"]["verdict"]`` with every level optional."""
    deep = verdict.get("deep_audit") if isinstance(verdict, Mapping) else None
    variant = deep.get("autoscaled_variant") if isinstance(deep, Mapping) else None
    return variant.get("verdict") if isinstance(variant, Mapping) else None


def after_gate(state: Mapping[str, Any], *, max_iter: int) -> Decision:
    """Route after the gate: a certified artifact ends the run (see the module table)."""
    verdict = state.get("manufacturability")
    if isinstance(verdict, Mapping) and verdict.get("printable") is True:
        return Decision(END, CERTIFIED)
    if _autoscaled_verdict(verdict) == "PRINT":
        return Decision(END, CERTIFIED)
    # The gate module's own tested helper keeps the refine-or-end rule in one place.
    gate_view = {
        "manufacturable": state.get("manufacturable"),
        "iteration_count": int(state.get("refine_count") or 0),
    }
    if route_after_manufacturability(gate_view, max_iter) == "end":
        return Decision(END, ITERATION_CAP_AFTER_GATE)
    return Decision(REFINE)
