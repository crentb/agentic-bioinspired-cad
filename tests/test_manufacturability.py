"""
test_manufacturability.py — Unit tests for the single-material manufacturability critic.

Pure Python; runs anywhere (no Blender, no langgraph). Covers each violation type, process-specific limits,
the non-blocking no-stats path, and the LangGraph node's effect on DesignState. None of these states
carries an exported STL, so the deep print audit (pyvista / scipy) is never triggered here.

Run:  python -m pytest tests/test_manufacturability.py   (fast suite; standard library only)
"""

from __future__ import annotations

from abcad.agent import manufacturability as M


def vtypes(verdict):
    """Set of violation types in a verdict."""
    return {v["type"] for v in verdict["violations"]}


def test_clean_pass():
    stats = {"min_feature_mm": 1.2, "overhang_area_frac": 0.05, "bbox_mm": (40, 40, 8)}
    v = M.check_manufacturability(stats, process="fdm")
    assert v["printable"] is True and not v["violations"], "clean design is printable"


def test_min_feature():
    v = M.check_manufacturability({"min_feature_mm": 0.3}, process="fdm")
    assert "min_feature" in vtypes(v) and v["printable"] is False, "thin feature flagged on FDM"
    assert len(v["suggestions"]) >= 1, "a suggestion is offered"


def test_overhang():
    v = M.check_manufacturability({"overhang_area_frac": 0.40}, process="fdm")
    assert "overhang" in vtypes(v), "excess overhang flagged on FDM"


def test_build_volume():
    v = M.check_manufacturability({"bbox_mm": (300, 50, 50)}, process="fdm")
    assert "build_volume" in vtypes(v), "oversize bbox flagged"
    v2 = M.check_manufacturability(
        {"bbox_mm": (300, 50, 50)}, process="fdm", build_volume=M.BuildVolume(x=350, y=350, z=350)
    )
    assert "build_volume" not in vtypes(v2), "larger build volume accepts it"


def test_fiber_fusion():
    # fiber radius > half the min center distance → tubes interpenetrate.
    v = M.check_manufacturability(
        {"woven_min_center_dist_mm": 3.892, "fiber_radius_mm": 2.5}, process="resin"
    )
    assert "fiber_fusion" in vtypes(v), "woven fiber fusion flagged"
    v_ok = M.check_manufacturability(
        {"woven_min_center_dist_mm": 3.892, "fiber_radius_mm": 0.4}, process="resin"
    )
    assert "fiber_fusion" not in vtypes(v_ok), "safe fiber radius passes"


def test_process_specific_limits():
    # A 0.4 mm feature fails FDM (limit 0.8) but passes resin (limit 0.3).
    fdm = M.check_manufacturability({"min_feature_mm": 0.4}, process="fdm")
    resin = M.check_manufacturability({"min_feature_mm": 0.4}, process="resin")
    assert "min_feature" in vtypes(fdm), "0.4 mm feature fails FDM"
    assert "min_feature" not in vtypes(resin), "0.4 mm feature passes resin"


def test_no_stats_non_blocking():
    v = M.check_manufacturability({}, process="fdm")
    assert v["printable"] is True, "no stats → printable (non-blocking)"


def test_node_updates_state():
    node = M.ManufacturabilityNode(process="fdm")
    state = {"mesh_stats": {"min_feature_mm": 0.2}, "vlm_feedback": "looks good"}
    out = node(state)
    assert out["manufacturable"] is False, "node sets manufacturable=False on a violation"
    assert (
        "manufacturability" in out and out["manufacturability"]["violations"]
    ), "node writes the verdict dict"
    assert "MANUFACTURABILITY" in out["vlm_feedback"], "node appends suggestions to vlm_feedback"

    node_ok = M.ManufacturabilityNode(process="resin")
    out2 = node_ok({"mesh_stats": {"min_feature_mm": 0.5, "bbox_mm": (40, 40, 10)}})
    assert out2["manufacturable"] is True, "node sets manufacturable=True on a clean design"


def test_routing():
    # Pure routing helper used by the critic-enabled graph builder.
    assert M.route_after_manufacturability({"manufacturable": True}) == "end", "printable → end"
    assert (
        M.route_after_manufacturability({"manufacturable": False, "iteration_count": 1}, max_iter=3)
        == "refine"
    ), "not printable + iters remaining → refine"
    assert (
        M.route_after_manufacturability({"manufacturable": False, "iteration_count": 3}, max_iter=3)
        == "end"
    ), "not printable + out of iterations → end"
    assert (
        M.route_after_manufacturability({}) == "end"
    ), "missing flag defaults to end (non-blocking)"
