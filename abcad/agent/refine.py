"""
abcad.agent.refine — the refine step: one parameter-level design edit in response to a critique.

PURPOSE
    When the critic rejects a design, the text model receives the last good script, the critique
    (and, after a gate verdict, the appended manufacturability suggestions) and a strict RULES
    block, and returns an edited script, which is executed once. The RULES encode the observed
    refine failures: cosmetic no-op edits, cleanup operators that break headless execution, and
    dead object references after ``join()``.

    Bookkeeping:
      * ``refine_count`` is incremented at the START of every visit, including visits that skip or
        receive no code, so the iteration cap counts visits;
      * a visit entered while ``approved`` is still true (the gate-to-refine edge) skips without
        calling the model: known limitation L-1, documented in docs/AGENT.md;
      * a candidate identical to an earlier refine output sets ``stalled`` but is still executed
        and critiqued once; the router then ends the run unless that critique approves;
      * a candidate that fails to execute sets ``approved = False`` and the router sends it to the
        repair step.

INPUTS / OUTPUTS
    RefineStep(chat, executor, exemplars, settings)(state) -> state update.
    compose_refine_prompt(...) -> the prompt text.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from abcad.agent.blender import BlenderExecutor
from abcad.agent.chat import ChatEndpoint, ChatError
from abcad.agent.console import event
from abcad.agent.ingest import execution_fields
from abcad.agent.retrieval import ExemplarIndex
from abcad.agent.scripttext import extract_script, normalize_script, script_digest
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

# Exact RULES block given to the refine model.
REFINE_RULES = (
    "RULES:\n"
    "- Make the SMALLEST parameter-level change that addresses the critique (sizes, counts, "
    "angles, radii, spacing). Keep the existing WORKING construction pattern — do not switch "
    "APIs.\n"
    "- Do NOT append mesh-cleanup or cosmetic operators (remove_doubles, dissolve, shade_smooth, "
    "materials): they do not change the geometry and often break headless execution.\n"
    "- bpy.ops.object.join() destroys all selected objects except the active one — never use "
    "list references to the merged objects after a join()."
)


def compose_refine_prompt(*, prompt: str, script: str, feedback: str, context: str) -> str:
    """Build the refine prompt.

    Sections, in order: role; the RULES block; retrieved examples; the design concept; the
    critique; the output instruction; and the code to improve, last.

    Args:
        prompt: the design request (the design concept section).
        script: the normalized base script (last good script).
        feedback: critique text, possibly with appended ``| MANUFACTURABILITY: ...`` suggestions.
        context: the retrieval context block.

    Returns:
        The prompt text.
    """
    sections = [
        "You are a Blender Python code design assistant. The script below already runs without "
        "errors. Your task is to carefully adjust its geometry so that the design satisfies the "
        "critique.",
        REFINE_RULES,
        "Here are some potentially useful base code examples retrieved from a database:\n\n"
        + context,
        "Design concept:\n" + prompt,
        "Critique:\n" + feedback,
        "Output ONLY valid Python code.",
        "Code to improve:\n" + script,
    ]
    return "\n\n".join(sections)


class RefineStep:
    """Loop step ``refine`` (see the module docstring).

    Args:
        chat: chat endpoint for the text model.
        executor: Blender executor.
        exemplars: code-exemplar index, or None for no retrieval context.
        settings: loop settings (temperature, token budget, debug folder).
    """

    def __init__(
        self,
        chat: ChatEndpoint,
        executor: BlenderExecutor,
        exemplars: ExemplarIndex | None,
        settings: AgentSettings,
    ) -> None:
        self._chat = chat
        self._executor = executor
        self._exemplars = exemplars
        self._settings = settings

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Run one refine visit and return the state update."""
        settings = self._settings
        k = int(state.get("refine_count") or 0) + 1
        update: dict[str, Any] = {"refine_count": k}
        LOGGER.info("refine iteration %d", k)
        event("refine_iteration", k=k)

        if state.get("approved"):
            # Parity (L-1): the gate-to-refine edge arrives here with approved still true.
            LOGGER.info("already approved, skipping refine")
            event("refine_skip", k=k)
            return update

        prompt = state.get("prompt") or ""
        base = state.get("last_good_script") or state.get("entry_script") or ""
        context = (
            self._exemplars.context_block(prompt, settings.text_top_k) if self._exemplars else ""
        )
        try:
            reply = self._chat.text(
                compose_refine_prompt(
                    prompt=prompt,
                    script=normalize_script(base),
                    feedback=state.get("feedback") or "",
                    context=context,
                ),
                temperature=settings.refine_temperature,
                max_tokens=settings.text_max_tokens,
            )
        except ChatError as exc:
            LOGGER.warning("refine chat call failed: %s", exc)
            reply = ""
        block = extract_script(reply)
        if not block.strip():
            LOGGER.info("no code in response; the same render will be critiqued again")
            return update

        candidate = normalize_script(block)
        digest = script_digest(candidate)
        previous = list(state.get("design_digests") or [])
        stalled = digest in previous
        update.update(stalled=stalled, design_digests=previous + [digest])
        if stalled:
            LOGGER.info("refine reproduced a previous iteration (stall)")
            event("refine_stall", k=k)

        debug_dir = settings.paths.debug_dir
        os.makedirs(debug_dir, exist_ok=True)
        with open(os.path.join(debug_dir, f"design_iter_{k}.py"), "w", encoding="utf-8") as handle:
            handle.write(candidate)
        report = self._executor.execute(
            candidate, label=f"design_iter_{k}", run_dir=state["run_dir"]
        )
        update.update(execution_fields(report))
        update["last_script"] = candidate
        if report.ok:
            update["last_good_script"] = candidate
            update["best_artifact"] = report.stl_path or report.render_png
        else:
            update["approved"] = False  # the router sends the broken design to repair
        return update
