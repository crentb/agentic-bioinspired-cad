"""
U-10: the repair step (abcad.agent.repair).

Stall guards (digest set seeded with the failing script, temperature ladder, sticky escalation),
error trail, attempt accounting, the repair base (the last executed script), the run-wide
refuted ledger, run-wide serial labels, and the debug copy written before execution.
"""

from __future__ import annotations

import os

from agent_fakes import FIXTURE_ERROR, ScriptedChat, ScriptedExecutor, fail, fenced, ok

from abcad.agent.chat import ChatError
from abcad.agent.repair import (
    ERROR_TRAIL_HEADER,
    ESCALATION_DEMAND,
    RESTRUCTURE_GUIDANCE,
    RepairStep,
    compose_repair_prompt,
)
from abcad.agent.scripttext import script_digest

BASE = "import bpy\nfiber = bpy.context.active_object\nfiber.splines.new('POLY')"
A = "import bpy\n# candidate A\nfiber.data.splines.new('POLY')"
B = "import bpy\n# candidate B: curve objects instead of mesh cylinders"
C = "import bpy\n# candidate C"


def state_after_failed_ingest(tmp_path, **extra):
    """State right after the entry script failed."""
    state = {
        "prompt": "a woven cubic lattice metamaterial",
        "run_dir": str(tmp_path / "run"),
        "entry_script": BASE,
        "last_script": BASE,
        "exec_status": "failed",
        "exec_error": FIXTURE_ERROR,
        "refuted_digests": [],
        "repair_serial": 0,
        "repair_attempts": 0,
    }
    state.update(extra)
    return state


def run_repair(settings, state, replies, outcomes, **executor_kwargs):
    chat = ScriptedChat(replies)
    executor = ScriptedExecutor(outcomes, **executor_kwargs)
    update = RepairStep(chat, executor, None, settings)(state)
    return update, chat, executor


def test_fixture_pattern_two_attempts(tmp_path, settings):
    update, chat, executor = run_repair(
        settings, state_after_failed_ingest(tmp_path), [fenced(A), fenced(B)], [fail(), ok()]
    )
    assert update["repair_ok"] is True and update["repair_attempts"] == 2
    assert executor.labels == ["fix_run_1", "fix_run_2"]
    assert update["repair_serial"] == 2
    assert update["last_script"] == B and update["last_good_script"] == B
    assert update["best_artifact"].endswith("geom_fix_run_2.stl")
    assert f"  after attempt 0: {FIXTURE_ERROR}" in chat.prompts[1]
    assert ERROR_TRAIL_HEADER not in chat.prompts[0]  # a trail needs two entries
    assert set(update["refuted_digests"]) == {script_digest(BASE), script_digest(A)}
    assert chat.temperatures == [0.1, 0.1]


def test_verbatim_repeats_escalate_the_temperature(tmp_path, settings):
    update, chat, executor = run_repair(
        settings,
        state_after_failed_ingest(tmp_path),
        [fenced(BASE), fenced("\n" + BASE + "\n"), fenced(C)],
        [ok()],
    )
    assert chat.temperatures == [0.1, 0.5, 0.8]
    assert ESCALATION_DEMAND not in chat.prompts[0]
    assert ESCALATION_DEMAND in chat.prompts[1] and ESCALATION_DEMAND in chat.prompts[2]
    assert executor.labels == ["fix_run_1"] and executor.calls[0]["script"] == C
    assert update["repair_attempts"] == 3 and update["repair_ok"] is True


def test_repeat_at_max_temperature_stops_without_rendering(tmp_path, settings):
    state = state_after_failed_ingest(tmp_path, repair_attempts=5)
    update, chat, executor = run_repair(
        settings, state, [fenced(BASE), fenced(BASE), fenced(BASE)], []
    )
    assert len(chat.calls) == 3 and executor.calls == []
    assert update["repair_ok"] is False
    assert "repair_attempts" not in update  # no attempt executed: the previous value stays


def test_empty_reply_consumes_an_attempt(tmp_path, settings):
    update, chat, executor = run_repair(
        settings, state_after_failed_ingest(tmp_path), ["", fenced(B)], [ok()]
    )
    assert executor.labels == ["fix_run_1"] and update["repair_attempts"] == 2


def test_chat_error_consumes_an_attempt(tmp_path, settings):
    update, chat, executor = run_repair(
        settings,
        state_after_failed_ingest(tmp_path),
        [ChatError("HTTP 500"), fenced(B)],
        [ok()],
    )
    assert len(chat.calls) == 2 and executor.labels == ["fix_run_1"]
    assert update["repair_ok"] is True and update["repair_attempts"] == 2


def test_dev1_base_is_the_last_executed_script(tmp_path, settings):
    refine_output = "import bpy\n# refine output R that broke"
    refine_error = "NameError: name 'fibres' is not defined"
    state = state_after_failed_ingest(tmp_path, last_script=refine_output, exec_error=refine_error)
    update, chat, executor = run_repair(settings, state, [fenced(B)], [ok()])
    first = chat.prompts[0]
    assert refine_output in first and refine_error in first
    assert BASE not in first
    assert first.rstrip().endswith(refine_output)  # the code to fix comes last


def test_dev2_refuted_scripts_stay_refuted_across_visits(tmp_path, settings):
    state = state_after_failed_ingest(tmp_path, refuted_digests=[script_digest(A)])
    update, chat, executor = run_repair(settings, state, [fenced(A), fenced(B)], [ok()])
    assert chat.temperatures == [0.1, 0.5]  # A counted as a repeat: no render, escalation
    assert ESCALATION_DEMAND in chat.prompts[1]
    assert executor.labels == ["fix_run_1"] and executor.calls[0]["script"] == B


def test_serial_continues_across_visits(tmp_path, settings):
    state = state_after_failed_ingest(tmp_path, repair_serial=2)
    update, chat, executor = run_repair(settings, state, [fenced(C)], [ok()])
    assert executor.labels == ["fix_run_3"] and update["repair_serial"] == 3


def test_debug_copy_exists_before_execution(tmp_path, settings):
    seen = []

    def check(label, script, run_dir):
        serial = label.rsplit("_", 1)[-1]
        path = os.path.join(settings.paths.debug_dir, f"fix_attempt_{serial}_runfix.py")
        seen.append(os.path.isfile(path) and open(path, encoding="utf-8").read() == script)

    run_repair(
        settings,
        state_after_failed_ingest(tmp_path),
        [fenced(A), fenced(B)],
        [fail(), ok()],
        on_execute=check,
    )
    assert seen == [True, True]


def test_exhaustion_with_distinct_failures(tmp_path, settings):
    update, chat, executor = run_repair(
        settings,
        state_after_failed_ingest(tmp_path),
        [fenced(A), fenced(B), fenced(C)],
        [fail("E1"), fail("E2"), fail("E3")],
    )
    assert update["repair_ok"] is False and update["repair_attempts"] == 3
    assert update["exec_status"] == "failed" and update["exec_error"] == "E3"
    assert "  after attempt 1: E1" in chat.prompts[2]
    assert set(update["refuted_digests"]) == {script_digest(s) for s in (BASE, A, B, C)}


def test_prompt_sections_and_order():
    prompt = compose_repair_prompt(
        prompt="a woven cubic lattice metamaterial",
        script="import bpy\n# code",
        error="E_current",
        context="CTX-BLOCK",
        error_trail=["E0", "E1", "E_current"],
        escalate=True,
    )
    order = [
        "repair assistant",
        RESTRUCTURE_GUIDANCE,
        "CTX-BLOCK",
        ERROR_TRAIL_HEADER,
        "  after attempt 0: E0\n  after attempt 1: E1",
        ESCALATION_DEMAND,
        "E_current",
        "Output ONLY valid Python code.",
        "import bpy\n# code",
    ]
    positions = [prompt.index(fragment) for fragment in order]
    assert positions == sorted(positions)
    assert "after attempt 2" not in prompt  # the current error has its own section
    assert not any(line.startswith("        ") for line in prompt.splitlines())
