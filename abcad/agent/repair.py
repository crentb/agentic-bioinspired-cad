"""
abcad.agent.repair — the repair step: make a failing script execute, with stall guards.

PURPOSE
    Up to ``repair_attempts`` attempts per visit to turn the failing script into one that runs.
    The guards exist because of observed failure modes:

      * byte-identical "fixes" (the same patch three times at temperature 0.1 burned a whole
        budget): every candidate is digested; a digest already known to fail is NOT rendered,
        consumes the attempt, and escalates the temperature along the ladder (0.1 -> 0.5 -> 0.8)
        together with a sticky escalation demand in the prompt; a repeat at the top of the ladder
        ends the visit;
      * superficial patching of a structural API error: the prompt carries the error trail of the
        visit and restructure guidance that points at the retrieved working exemplars;
      * reintroducing an already refuted script in a later visit: a run-wide ledger of refuted
        digests seeds every visit, and the base of a visit is the script whose execution
        produced the current error (``last_script``).

    A chat failure or a reply without code consumes the attempt without rendering. Labels use a
    run-wide serial (``fix_run_<n>``) so later visits never overwrite earlier files.

INPUTS / OUTPUTS
    RepairStep(chat, executor, exemplars, settings)(state) -> state update.
    compose_repair_prompt(...) -> the prompt text (also used by the tests).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from abcad.agent.blender import BlenderExecutor
from abcad.agent.chat import ChatEndpoint, ChatError
from abcad.agent.console import event
from abcad.agent.ingest import execution_fields
from abcad.agent.retrieval import ExemplarIndex
from abcad.agent.scripttext import extract_script, first_line, normalize_script, script_digest
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

# ---- exact prompt text (fixed wording the loop's behavior was validated with) ---------------------
RESTRUCTURE_GUIDANCE = (
    "They are WORKING reference patterns for this design family — if the same error persists "
    "across attempts, RESTRUCTURE the failing block to follow the reference pattern instead of "
    "making a minimal attribute/typo patch."
)
ERROR_TRAIL_HEADER = "Errors from PREVIOUS failed attempts (attempt 0 = the original code):"
ESCALATION_DEMAND = (
    "IMPORTANT: a previous fix you produced was IDENTICAL to an earlier failed attempt. Do NOT "
    "emit that code again. The error is structural, not a typo: REBUILD the failing block so it "
    "follows the WORKING construction pattern shown in the reference examples above."
)


def compose_repair_prompt(
    *,
    prompt: str,
    script: str,
    error: str,
    context: str,
    error_trail: Sequence[str],
    escalate: bool,
) -> str:
    """Build the repair prompt.

    Sections, in order: role and task; retrieved examples with the restructure guidance; the
    error trail (only when it holds two or more entries: every entry except the current error,
    which has its own section); the escalation demand (only when ``escalate``); the current error
    in full; the output instruction; and the code to fix, last.

    Args:
        prompt: the design request. The retrieval context is computed by the caller from it; the
            text itself is not repeated here, matching the validated prompt layout.
        script: the code to fix.
        error: the current Blender error excerpt.
        context: the retrieval context block.
        error_trail: errors of this visit, oldest first (entry 0 = the original code's error).
        escalate: whether a verbatim repeat was seen in this visit.

    Returns:
        The prompt text.
    """
    sections = [
        "You are a Blender Python code repair assistant. The Blender Python script below fails "
        "when it runs. Fix it and return a complete, working Blender Python script and nothing "
        "else.",
        "Here are some potentially useful base code examples retrieved from a database. "
        + RESTRUCTURE_GUIDANCE
        + "\n\n"
        + context,
    ]
    if len(error_trail) >= 2:
        lines = [ERROR_TRAIL_HEADER]
        lines += [
            f"  after attempt {index}: {first_line(entry)}"
            for index, entry in enumerate(error_trail[:-1])
        ]
        sections.append("\n".join(lines))
    if escalate:
        sections.append(ESCALATION_DEMAND)
    sections.append("Blender error message:\n" + error)
    sections.append("Output ONLY valid Python code.")
    sections.append("Code to fix:\n" + script)
    return "\n\n".join(sections)


def _union(*groups: Sequence[str]) -> list[str]:
    """Order-preserving union of digest lists (the ledger stays readable in the manifest)."""
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged


class RepairStep:
    """Loop step ``repair`` (see the module docstring).

    Args:
        chat: chat endpoint for the text model.
        executor: Blender executor.
        exemplars: code-exemplar index, or None for no retrieval context.
        settings: loop settings (attempts, temperature ladder, token budget, debug folder).
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

    def _ask(self, prompt_text: str, temperature: float) -> str:
        """One chat call; a ChatError is logged and treated as an empty reply."""
        try:
            return self._chat.text(
                prompt_text, temperature=temperature, max_tokens=self._settings.text_max_tokens
            )
        except ChatError as exc:
            LOGGER.warning("repair chat call failed: %s", exc)
            return ""

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Run one repair visit and return the state update."""
        settings = self._settings
        prompt = state.get("prompt") or ""
        # The base is the script whose execution produced the current error.
        base = state.get("last_script")
        if base is None:
            base = state.get("entry_script") or ""
        error = state.get("exec_error") or ""
        context = (
            self._exemplars.context_block(prompt, settings.text_top_k) if self._exemplars else ""
        )
        base_digest = script_digest(base)

        tried = set(state.get("refuted_digests") or []) | {base_digest}  # the base counts as tried
        trail: list[str] = [error] if error.strip() else []
        ladder = settings.repair_temperature_ladder
        ladder_index = 0
        temperature = ladder[0]
        escalate = False
        current = base
        executed_failures: list[str] = []
        serial = int(state.get("repair_serial") or 0)
        update: dict[str, Any] = {}
        attempt = 0

        while attempt < settings.repair_attempts:
            attempt += 1
            if error.strip():
                LOGGER.info("fixing: %s", first_line(error, 160))
            event(
                "repair_attempt",
                n=attempt,
                temperature=temperature,
                fixing=first_line(error, 160) if error.strip() else None,
            )
            reply = self._ask(
                compose_repair_prompt(
                    prompt=prompt,
                    script=current,
                    error=error,
                    context=context,
                    error_trail=trail,
                    escalate=escalate,
                ),
                temperature,
            )
            block = extract_script(reply)
            if not block.strip():
                LOGGER.info("no code in response (attempt %d consumed, no render)", attempt)
                continue
            candidate = normalize_script(block)
            digest = script_digest(candidate)
            if digest in tried:
                if temperature >= ladder[-1] or ladder_index >= len(ladder) - 1:
                    LOGGER.info("repeat at max temperature, stopping")
                    break
                ladder_index += 1
                temperature = ladder[ladder_index]
                escalate = True  # sticky for the rest of the visit
                LOGGER.info("repeat of a failed attempt, no render, temperature -> %s", temperature)
                event("repair_repeat", temperature=temperature)
                continue

            # ---- a new candidate: keep a debug copy, then execute it --------------------------
            tried.add(digest)
            current = candidate
            serial += 1
            label = f"fix_run_{serial}"
            debug_dir = settings.paths.debug_dir
            os.makedirs(debug_dir, exist_ok=True)
            with open(
                os.path.join(debug_dir, f"fix_attempt_{serial}_runfix.py"), "w", encoding="utf-8"
            ) as handle:
                handle.write(candidate)
            report = self._executor.execute(candidate, label=label, run_dir=state["run_dir"])
            update.update(execution_fields(report))
            update.update(last_script=candidate, repair_attempts=attempt, repair_serial=serial)
            if report.ok:
                update.update(
                    last_good_script=candidate,
                    best_artifact=report.stl_path or report.render_png,
                    repair_ok=True,
                    refuted_digests=_union(
                        state.get("refuted_digests") or [], [base_digest], executed_failures
                    ),
                )
                event("repair_done", ok=True, attempts=attempt)
                return update
            executed_failures.append(digest)
            error = report.error
            trail.append(error)

        update.update(
            repair_ok=False,
            refuted_digests=_union(
                state.get("refuted_digests") or [], [base_digest], executed_failures
            ),
        )
        LOGGER.info("repair failed all attempts")
        event("repair_done", ok=False, attempts=attempt)
        return update
