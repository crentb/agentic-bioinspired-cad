"""
abcad.agent.runner — the state-machine executor and the two-phase run orchestration.

PURPOSE
    ``DesignLoop`` executes the loop's state machine explicitly (no graph framework): it calls the
    current step with a read-only copy of the state, merges the returned update, asks the step's
    pure router for the next step, records the decision in the trace, and stops at END, at the
    step limit, or on any exception. Every termination sets ``terminal_reason`` and writes the run
    manifest.

    ``run_design_loop`` is the end-to-end orchestration used by the command line:

      1. settings + logging
      2. preflight (no run folder yet; failures return exit code 2): Blender executable, primary
         reference-image corpus, chat URL loopback guard, gate preflight, --use-code file
      3. run folder + run.log tee
      4. Phase 1: --use-code file, or the LoRA emit in a child process that exits (emit_failed /
         emit_empty end the run with a manifest and exit code 1)
      5. Phase 2 components, built only now: one CPU embedder shared by both indexes, the chat
         endpoint, the Blender executor, the critic and the gate node
      6. DesignLoop from ingest; summary; LoopOutcome

EXIT CODES
    0  the run ended through a router decision (an honest non-approval is a successful run)
    1  error, emit_failed, emit_empty or step_limit
    2  usage, settings or preflight error (no run folder, no manifest)

INPUTS / OUTPUTS
    run_design_loop(prompt, settings=..., use_code=..., components=...) -> LoopOutcome(state,
    manifest_path, exit_code). The run folder holds the executed scripts, renders, STLs, Blender
    logs, run.log and run_manifest.json.
"""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from types import MappingProxyType
from typing import Any, Literal

from abcad.agent import phase_one, routing
from abcad.agent.blender import BlenderExecutor
from abcad.agent.chat import (
    ChatEndpoint,
    ChatTransport,
    release_resident_models,
    validate_base_url,
)
from abcad.agent.console import configure_logging, event, tee_stdout
from abcad.agent.critic import CritiqueStep, RenderCritic
from abcad.agent.gate import (
    GatePreflight,
    GateStep,
    classify_certification,
    make_gate_node,
    prepare_gate,
    run_gate_preflight,
)
from abcad.agent.ingest import IngestStep
from abcad.agent.loop_state import LoopState, initial_state, merge_update
from abcad.agent.manifest import build_manifest, write_manifest
from abcad.agent.refine import RefineStep
from abcad.agent.repair import RepairStep
from abcad.agent.retrieval import Embedder, ExemplarIndex, ReferenceGallery, SentenceEmbedder
from abcad.agent.settings import AgentSettings, SettingsError, load_settings

LOGGER = logging.getLogger("abcad.agent")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

# Terminal reasons that mean the TOOL did not complete normally (exit code 1).
FAILURE_REASONS = frozenset(
    {routing.ERROR, routing.EMIT_FAILED, routing.EMIT_EMPTY, routing.STEP_LIMIT}
)

Step = Callable[[Mapping[str, Any]], Mapping[str, Any]]
Router = Callable[[Mapping[str, Any]], routing.Decision]


def exit_code_for(reason: str | None) -> int:
    """Map a terminal reason to the process exit code (see EXIT CODES)."""
    return EXIT_FAILURE if reason in FAILURE_REASONS or reason is None else EXIT_OK


def default_routers(max_iter: int) -> dict[str, Router]:
    """The router of each step, with ``max_iter`` bound where the table needs it."""
    return {
        routing.INGEST: routing.after_ingest,
        routing.CRITIQUE: partial(routing.after_critique, max_iter=max_iter),
        routing.REPAIR: routing.after_repair,
        routing.REFINE: routing.after_refine,
        routing.GATE: partial(routing.after_gate, max_iter=max_iter),
    }


# --------------------------------------------------------------------------------------------------
# Manifest writing shared by the loop and the pre-loop terminations
# --------------------------------------------------------------------------------------------------
ExtrasSource = Callable[[], Mapping[str, Any]] | Mapping[str, Any] | None


def _resolve_extras(extras: ExtrasSource) -> Mapping[str, Any]:
    """Evaluate a lazily supplied extras mapping (so late facts such as the Blender version count)."""
    if extras is None:
        return {}
    return extras() if callable(extras) else extras


def finish_run(
    state: LoopState,
    reason: str,
    detail: str | None,
    *,
    settings: AgentSettings,
    extras: ExtrasSource = None,
) -> tuple[LoopState, str | None]:
    """Record the terminal reason, log it, and write the manifest.

    Args:
        state: the state as last written.
        reason: a member of ``routing.TERMINAL_REASONS``.
        detail: extra detail (exit code, "timeout", or "<ExceptionType>: <message>").
        settings: run settings (for the manifest's configuration snapshot).
        extras: manifest extras or a callable returning them.

    Returns:
        ``(final state, manifest path or None when the manifest could not be written)``.
    """
    state = merge_update(state, {"terminal_reason": reason, "terminal_detail": detail})
    event("terminal", reason=reason, detail=detail)
    if reason == routing.CERTIFIED:
        certification = classify_certification(
            state.get("manufacturability"),
            gated_source_stl=state.get("gated_source_stl"),
            final_artifact=state.get("best_artifact"),
        )
        if certification["status"] == "light_only_pass":
            LOGGER.warning(
                "run certified by the LIGHT check only: the deep print audit did not run"
            )
    run_dir = state.get("run_dir")
    if not run_dir:
        return state, None
    try:
        manifest = build_manifest(state, settings=settings, extras=_resolve_extras(extras))
        path = write_manifest(manifest, run_dir)
    except Exception:  # the record must never crash the run; the failure itself is logged
        LOGGER.error("could not write the run manifest", exc_info=True)
        return state, None
    event("manifest_written", path=path)
    return state, path


# --------------------------------------------------------------------------------------------------
# The state-machine executor
# --------------------------------------------------------------------------------------------------
class DesignLoop:
    """Explicit executor of the loop's state machine.

    Args:
        steps: callables keyed by step name; each takes a read-only state and returns an update.
        settings: loop settings (``max_iter`` for the routers, ``step_limit``).
        entry: first step.
        routers: router per step; defaults to :func:`default_routers`.
        manifest_extras: extras for the manifest (mapping or zero-argument callable).

    Attributes:
        manifest_path: path of the manifest written by the last :meth:`run`, if any.
    """

    def __init__(
        self,
        steps: Mapping[str, Step],
        settings: AgentSettings,
        *,
        entry: str = routing.INGEST,
        routers: Mapping[str, Router] | None = None,
        manifest_extras: ExtrasSource = None,
    ) -> None:
        self._steps = dict(steps)
        self._settings = settings
        self._entry = entry
        self._routers = dict(routers) if routers is not None else default_routers(settings.max_iter)
        self._extras = manifest_extras
        self.manifest_path: str | None = None

    def _finish(self, state: LoopState, reason: str, detail: str | None) -> LoopState:
        """Terminate: record the reason and write the manifest."""
        state, self.manifest_path = finish_run(
            state, reason, detail, settings=self._settings, extras=self._extras
        )
        return state

    def run(self, state: LoopState) -> LoopState:
        """Execute steps from the entry step until a terminal condition; return the final state.

        Steps receive a read-only COPY of the state (they cannot mutate it, even through nested
        lists); routers receive a read-only view of the merged state.
        """
        step = self._entry
        try:
            while True:
                if int(state.get("steps_taken") or 0) >= self._settings.step_limit:
                    return self._finish(state, routing.STEP_LIMIT, None)
                if step not in self._steps:
                    raise KeyError(f"no step named {step!r}")
                update = self._steps[step](MappingProxyType(copy.deepcopy(dict(state))))
                bookkeeping = {
                    "last_step": step,
                    "steps_taken": int(state.get("steps_taken") or 0) + 1,
                }
                state = merge_update(state, {**dict(update or {}), **bookkeeping})
                decision = self._routers[step](MappingProxyType(state))
                entry = {"step": step, "next": decision.next, "reason": decision.reason}
                state = merge_update(state, {"trace": list(state.get("trace") or []) + [entry]})
                if decision.next == routing.END:
                    return self._finish(state, decision.reason or routing.ERROR, None)
                step = decision.next
        except Exception as exc:
            LOGGER.error("step %r failed: %s: %s", step, type(exc).__name__, exc, exc_info=True)
            return self._finish(state, routing.ERROR, f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------------------------------
# Phase-2 components (a factory seam, so tests can inject fakes)
# --------------------------------------------------------------------------------------------------
@dataclass
class Components:
    """Everything Phase 2 needs, built after Phase 1 has exited."""

    embedder: Embedder
    exemplars: ExemplarIndex
    gallery: ReferenceGallery
    chat: ChatEndpoint
    executor: BlenderExecutor
    critic: RenderCritic
    gate_node: Callable[[dict], dict]
    gate_preflight: GatePreflight


def build_components(
    settings: AgentSettings,
    *,
    gate_preflight: GatePreflight | None = None,
    embedder: Embedder | None = None,
    transport: ChatTransport | None = None,
    process_runner: Callable[..., Any] | None = None,
) -> Components:
    """Construct the Phase-2 components.

    Args:
        settings: loop settings.
        gate_preflight: the preflight already established for this run (re-resolved when None).
        embedder: shared embedder; defaults to one CPU ``SentenceEmbedder`` (lazy).
        transport: chat transport override (tests).
        process_runner: Blender process runner override (tests).

    Returns:
        The :class:`Components`.
    """
    shared = embedder or SentenceEmbedder(
        settings.embed_model, settings.embed_revision, settings.embed_device
    )
    exemplars = ExemplarIndex.from_corpora(
        settings.text_corpora, shared, enabled=settings.rag_enabled
    )
    gallery = ReferenceGallery.from_corpora(
        settings.vlm_corpora, shared, image_root=settings.reference_image_root
    )
    chat = ChatEndpoint(settings, transport)
    executor = (
        BlenderExecutor(settings, process_runner=process_runner)
        if process_runner is not None
        else BlenderExecutor(settings)
    )
    critic = RenderCritic(chat, gallery, settings)
    if gate_preflight is None:
        node, preflight = prepare_gate(settings)
    else:
        node, preflight = make_gate_node(settings), gate_preflight
    return Components(
        embedder=shared,
        exemplars=exemplars,
        gallery=gallery,
        chat=chat,
        executor=executor,
        critic=critic,
        gate_node=node,
        gate_preflight=preflight,
    )


def build_steps(script: str, components: Components, settings: AgentSettings) -> dict[str, Step]:
    """The five loop steps wired to the components."""
    return {
        routing.INGEST: IngestStep(script, components.executor),
        routing.CRITIQUE: CritiqueStep(components.critic, settings),
        routing.REPAIR: RepairStep(
            components.chat, components.executor, components.exemplars, settings
        ),
        routing.REFINE: RefineStep(
            components.chat, components.executor, components.exemplars, settings
        ),
        routing.GATE: GateStep(components.gate_node, settings, components.gate_preflight),
    }


# --------------------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------------------
@dataclass
class LoopOutcome:
    """Result of :func:`run_design_loop`.

    Attributes:
        state: the final loop state (empty when the run never started).
        manifest_path: the written manifest, or None (preflight failures write none).
        exit_code: 0, 1 or 2 (see EXIT CODES).
    """

    state: LoopState
    manifest_path: str | None
    exit_code: int


class PreflightError(RuntimeError):
    """A precondition of the run is not met (reported with exit code 2, before any run folder)."""


def preflight(settings: AgentSettings, *, use_code: str | None) -> GatePreflight:
    """Check the run's preconditions without creating anything.

    Raises:
        PreflightError: Blender missing, primary image corpus missing, chat URL refused, the
            --use-code file missing or not readable UTF-8, or a required deep audit unavailable.

    Returns:
        The gate preflight (recorded in the manifest).
    """
    blender = settings.blender_path
    if not (os.path.isfile(blender) and os.access(blender, os.X_OK)):
        raise PreflightError(
            f"Blender executable not found or not executable: {blender!r} (set ABCAD_BLENDER)"
        )
    if not settings.vlm_corpora or not os.path.isfile(settings.vlm_corpora[0]):
        primary = settings.vlm_corpora[0] if settings.vlm_corpora else "(none configured)"
        raise PreflightError(f"primary reference-image corpus not found: {primary}")
    try:
        validate_base_url(settings.llm_base_url, allow_remote=settings.allow_remote_llm)
    except SettingsError as exc:
        raise PreflightError(str(exc)) from exc
    if use_code is not None and not os.path.isfile(use_code):
        raise PreflightError(f"--use-code file not found: {use_code}")
    if use_code is not None:
        # Read it now, so an unreadable or non-UTF-8 file stops the run before a run folder
        # exists (exit 2) instead of crashing after it (no manifest).
        try:
            with open(use_code, encoding="utf-8") as handle:
                handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            raise PreflightError(
                f"--use-code file is not readable UTF-8 text: {use_code} ({exc})"
            ) from exc
    gate_preflight = run_gate_preflight(settings)
    if (
        settings.require_deep_audit
        and gate_preflight.deep_audit_requested
        and not gate_preflight.deep_audit_available
    ):
        raise PreflightError(
            "the deep print audit is required (ABCAD_REQUIRE_DEEP_AUDIT=1) but unavailable: "
            + "; ".join(gate_preflight.problems)
        )
    return gate_preflight


def create_run_dir(runs_dir: str) -> str:
    """Create ``<runs_dir>/<%Y-%m-%d_%H-%M-%S>`` (``_2``, ``_3``, ... when it already exists)."""
    os.makedirs(runs_dir, exist_ok=True)
    base = os.path.join(runs_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    candidate, suffix = base, 1
    while True:
        try:
            os.mkdir(candidate)  # atomic: two runs can never share a folder
            return candidate
        except FileExistsError:
            suffix += 1
            candidate = f"{base}_{suffix}"


def _log_summary(state: Mapping[str, Any], manifest_path: str | None) -> None:
    """Plain-ASCII end-of-run summary block."""
    certification = classify_certification(
        state.get("manufacturability"),
        gated_source_stl=state.get("gated_source_stl"),
        final_artifact=state.get("best_artifact"),
    )
    rows = [
        ("approved", state.get("approved")),
        ("ever_approved", state.get("ever_approved")),
        ("blender_status", state.get("exec_status")),
        ("final_result", state.get("best_artifact")),
        ("stl_path", state.get("stl_path")),
        ("stl_path_scaled", state.get("stl_path_scaled")),
        ("certification", certification["status"]),
        ("terminal_reason", state.get("terminal_reason")),
        ("manifest", manifest_path),
    ]
    lines = ["=" * 20 + " run summary " + "=" * 20]
    lines += [f"{name:<16}: {value}" for name, value in rows]
    lines.append("=" * 53)
    for line in lines:
        LOGGER.info(line)


def run_design_loop(
    prompt: str,
    *,
    settings: AgentSettings | None = None,
    use_code: str | None = None,
    components: Components | None = None,
) -> LoopOutcome:
    """Run the whole two-phase loop for one prompt (see the module docstring).

    Args:
        prompt: the design request.
        settings: loop settings; defaults to :func:`load_settings` of the environment.
        use_code: path of a saved script to use instead of the Phase-1 emit.
        components: pre-built Phase-2 components (tests); built after Phase 1 when None.

    Returns:
        The :class:`LoopOutcome`.
    """
    # ---- 1. settings and logging ----------------------------------------------------------------
    if settings is None:
        try:
            settings = load_settings()
        except SettingsError as exc:
            configure_logging()
            LOGGER.error("settings error: %s", exc)
            return LoopOutcome(state={}, manifest_path=None, exit_code=EXIT_USAGE)
    configure_logging(settings.log_level)

    # ---- 2. preflight: nothing is created before it passes -------------------------------------
    try:
        gate_preflight = preflight(settings, use_code=use_code)
    except PreflightError as exc:
        LOGGER.error("preflight failed: %s", exc)
        return LoopOutcome(state={}, manifest_path=None, exit_code=EXIT_USAGE)

    # ---- 3. run folder and run log --------------------------------------------------------------
    run_dir = create_run_dir(settings.paths.runs_dir)
    origin: Literal["lora", "use-code"] = "use-code" if use_code is not None else "lora"
    state = initial_state(prompt, run_dir, entry_origin=origin, entry_source=use_code)
    facts: dict[str, Any] = {"gate_preflight": gate_preflight.as_dict(), "entry_chars": None}
    live: dict[str, Any] = {"components": components}

    def manifest_extras() -> dict[str, Any]:
        """Late-bound manifest extras (the Blender version is known only after an execution)."""
        executor = getattr(live["components"], "executor", None)
        return {**facts, "blender_version": getattr(executor, "blender_version", None)}

    tee = tee_stdout(os.path.join(run_dir, "run.log")) if settings.run_log else nullcontext()
    with tee:
        event("run_start", prompt=prompt, run_dir=run_dir, mode=origin)
        LOGGER.info(
            "gate preflight: deep audit requested=%s available=%s%s",
            gate_preflight.deep_audit_requested,
            gate_preflight.deep_audit_available,
            f" ({'; '.join(gate_preflight.problems)})" if gate_preflight.problems else "",
        )

        # ---- 4. Phase 1 ------------------------------------------------------------------------
        try:
            if use_code is not None:
                with open(use_code, encoding="utf-8") as handle:
                    script = handle.read()
                if not script.strip():
                    raise phase_one.EmitEmpty(f"--use-code file is empty: {use_code}")
            else:
                # Free the chat daemon first: a model an earlier run left resident (keep-alive)
                # would otherwise share unified memory with the emitter.
                released = release_resident_models(settings.llm_base_url)
                if released:
                    event("chat_models_released", models=released)
                script = phase_one.emit_via_child(
                    prompt, settings, log=lambda line: LOGGER.info("[phase1] %s", line)
                )
            facts["entry_chars"] = len(script)
        except phase_one.EmitEmpty as exc:
            LOGGER.error("Phase 1 produced no script: %s", exc)
            state, path = finish_run(
                state, routing.EMIT_EMPTY, str(exc), settings=settings, extras=manifest_extras
            )
            _log_summary(state, path)
            return LoopOutcome(state, path, exit_code_for(routing.EMIT_EMPTY))
        except phase_one.EmitFailed as exc:
            LOGGER.error("Phase 1 failed: %s", exc)
            state, path = finish_run(
                state, routing.EMIT_FAILED, str(exc), settings=settings, extras=manifest_extras
            )
            _log_summary(state, path)
            return LoopOutcome(state, path, exit_code_for(routing.EMIT_FAILED))

        # ---- 5. Phase 2 components (only now that the Phase-1 child has exited) -----------------
        try:
            if live["components"] is None:
                live["components"] = build_components(settings, gate_preflight=gate_preflight)
            loop = DesignLoop(
                build_steps(script, live["components"], settings),
                settings,
                manifest_extras=manifest_extras,
            )
        except Exception as exc:
            LOGGER.error("could not build the Phase-2 components", exc_info=True)
            state, path = finish_run(
                state,
                routing.ERROR,
                f"{type(exc).__name__}: {exc}",
                settings=settings,
                extras=manifest_extras,
            )
            _log_summary(state, path)
            return LoopOutcome(state, path, exit_code_for(routing.ERROR))

        # ---- 6. the loop ------------------------------------------------------------------------
        state = loop.run(state)
        _log_summary(state, loop.manifest_path)
        return LoopOutcome(state, loop.manifest_path, exit_code_for(state.get("terminal_reason")))
