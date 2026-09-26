"""
U-11: the refine step (abcad.agent.refine).

Skip while approved (parity, L-1), no-code visits, successful and failing candidates, the stall
guard (a repeat is still executed once), and the prompt's exact RULES block and section order.
"""

from __future__ import annotations

import os

from agent_fakes import ScriptedChat, ScriptedExecutor, fail, fenced, ok

from abcad.agent.chat import ChatError
from abcad.agent.refine import REFINE_RULES, RefineStep, compose_refine_prompt
from abcad.agent.scripttext import script_digest

GOOD_SCRIPT = "import bpy\nFIBERS_PER_EDGE = 4"
EDIT = "import bpy\nFIBERS_PER_EDGE = 8"


def state_after_rejection(tmp_path, **extra):
    """State after a successful execution and a rejecting critique."""
    state = {
        "prompt": "a woven cubic lattice metamaterial",
        "run_dir": str(tmp_path / "run"),
        "entry_script": "import bpy\n# entry",
        "last_script": GOOD_SCRIPT,
        "last_good_script": GOOD_SCRIPT,
        "exec_status": "success",
        "exec_error": "",
        "render_png": "/r/render_fix_run_2.png",
        "stl_path": "/r/geom_fix_run_2.stl",
        "feedback": "{'match_quality': 'partial', 'approve': False}",
        "approved": False,
        "refine_count": 0,
        "design_digests": [],
        "stalled": False,
    }
    state.update(extra)
    return state


def test_skip_while_approved(tmp_path, settings):
    chat, executor = ScriptedChat([]), ScriptedExecutor([])
    update = RefineStep(chat, executor, None, settings)(
        state_after_rejection(tmp_path, approved=True, refine_count=1)
    )
    assert update == {"refine_count": 2}
    assert chat.calls == [] and executor.calls == []


def test_no_code_reply_changes_nothing_but_the_count(tmp_path, settings):
    for reply in ("", ChatError("down")):
        chat, executor = ScriptedChat([reply]), ScriptedExecutor([])
        update = RefineStep(chat, executor, None, settings)(state_after_rejection(tmp_path))
        assert update == {"refine_count": 1} and executor.calls == []


def test_successful_edit(tmp_path, settings):
    chat, executor = ScriptedChat([fenced(EDIT)]), ScriptedExecutor([ok()])
    update = RefineStep(chat, executor, None, settings)(state_after_rejection(tmp_path))
    assert executor.labels == ["design_iter_1"]
    assert update["refine_count"] == 1 and update["stalled"] is False
    assert update["design_digests"] == [script_digest(EDIT)]
    assert update["last_script"] == EDIT and update["last_good_script"] == EDIT
    assert update["best_artifact"].endswith("geom_design_iter_1.stl")
    assert update["exec_status"] == "success" and "approved" not in update
    debug_copy = os.path.join(settings.paths.debug_dir, "design_iter_1.py")
    assert open(debug_copy, encoding="utf-8").read() == EDIT
    assert chat.temperatures == [0.1] and chat.calls[0]["max_tokens"] == 5000


def test_repeat_sets_stalled_and_still_executes(tmp_path, settings):
    state = state_after_rejection(tmp_path, refine_count=1, design_digests=[script_digest(EDIT)])
    chat, executor = ScriptedChat([fenced(EDIT)]), ScriptedExecutor([ok()])
    update = RefineStep(chat, executor, None, settings)(state)
    assert update["stalled"] is True and executor.labels == ["design_iter_2"]
    assert update["design_digests"] == [script_digest(EDIT)] * 2


def test_failing_edit_unapproves_and_keeps_the_good_script(tmp_path, settings):
    chat, executor = ScriptedChat([fenced(EDIT)]), ScriptedExecutor([fail("boom")])
    update = RefineStep(chat, executor, None, settings)(state_after_rejection(tmp_path))
    assert update["approved"] is False and update["exec_status"] == "failed"
    assert update["last_script"] == EDIT and "last_good_script" not in update
    assert update["exec_error"] == "boom"


def test_prompt_contents_and_order(tmp_path, settings):
    chat, executor = ScriptedChat([fenced(EDIT)]), ScriptedExecutor([ok()])
    state = state_after_rejection(tmp_path, last_good_script="x = 1")  # normalized in the prompt
    RefineStep(chat, executor, None, settings)(state)
    prompt = chat.prompts[0]
    assert REFINE_RULES in prompt
    assert state["feedback"] in prompt
    assert prompt.rstrip().endswith("import bpy\nx = 1")
    order = ["design assistant", "RULES:", "Design concept:", "Critique:", "Output ONLY"]
    positions = [prompt.index(fragment) for fragment in order]
    assert positions == sorted(positions)


def test_rules_block_is_exact():
    assert REFINE_RULES == (
        "RULES:\n"
        "- Make the SMALLEST parameter-level change that addresses the critique (sizes, counts, "
        "angles, radii, spacing). Keep the existing WORKING construction pattern — do not "
        "switch APIs.\n"
        "- Do NOT append mesh-cleanup or cosmetic operators (remove_doubles, dissolve, "
        "shade_smooth, materials): they do not change the geometry and often break headless "
        "execution.\n"
        "- bpy.ops.object.join() destroys all selected objects except the active one — never "
        "use list references to the merged objects after a join()."
    )
    prompt = compose_refine_prompt(prompt="P", script="S", feedback="F", context="CTX")
    assert prompt.index("CTX") < prompt.index("Design concept:\nP") < prompt.index("Critique:\nF")
