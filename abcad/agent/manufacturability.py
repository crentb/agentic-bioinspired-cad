"""
manufacturability.py — Single-material print manufacturability critic for the agentic design loop.

PURPOSE
    Implements the manufacturability agent of the design loop: after a design renders successfully,
    verify it can actually be printed in ONE material, and (if not) feed concrete suggestions to the
    Refinement agent so the loop converges on a fabricable design.

WHAT IT CHECKS (single material; all geometry-only)
    • minimum feature / wall thickness   ≥ the process resolution
    • overhang area fraction (FDM)        ≤ threshold, else supports/reorient
    • bounding box                        ≤ printer build volume
    • woven fiber interpenetration        chosen fiber radius ≤ ½·(min inter-fiber center distance)
                                          (woven tubes must not fuse — that destroys the woven compliance)

DESIGN
    The check itself (`check_manufacturability`) is pure Python operating on a small ``stats`` dict, so it is
    fully unit-testable without Blender. ``ManufacturabilityNode`` wraps it as a graph node (a plain
    callable on the shared DesignState — no langgraph import required here). Mesh stats are expected to be
    produced by the Blender validation step (min feature / overhang / bbox) and/or carried from the generator
    (woven clearance, fiber radius); if absent, the node is non-blocking (printable=True with a note) so it can
    be added to the graph without breaking existing runs.

    Graph wiring (see docs/WORKFLOWS.md): insert after the VLM approves — if not printable and
    iterations remain, route to the CodeDesigner with `suggestions` injected into the critique; else finish and
    surface the violations to the operator.

INPUTS / OUTPUTS
    check_manufacturability(stats, process, build_volume) -> verdict dict.
    ManufacturabilityNode()(state) -> the same state with ``manufacturability`` / ``manufacturable`` set
    (and, with an exported STL on the state, a deep print audit and an auto-scaled variant written next to it).
    Environment: ABCAD_TARGET_SIZE_MM (optional) rescales the exported STL to that largest dimension [mm]
    before the deep audit.

DEPENDENCIES
    Standard library only at import time. The deep audit lazily imports abcad.printing.print_audit and
    abcad.printing.fdm_variants (pyvista + scipy; conda cad_env). No other agent module is imported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _load_print_audit():
    """Import abcad.printing.print_audit on first use (the deep print-audit engine).

    Lazy: pyvista/scipy only load when the deep audit actually runs (post-VLM-approval), keeping this
    module import-light for the unit tests and the graph build. Python's module cache makes repeat calls
    free.
    """
    from abcad.printing import print_audit

    return print_audit


def _load_fdm_variants():
    """Import abcad.printing.fdm_variants on first use (same lazy pattern as _load_print_audit)."""
    from abcad.printing import fdm_variants

    return fdm_variants


# Process resolution limits in millimetres. Defaults are conservative desktop values; override per machine.
PROCESS_LIMITS: Dict[str, Dict[str, float]] = {
    # FDM: robust unsupported strand ≈ 2× a 0.4 mm nozzle; 45° overhang rule.
    "fdm": {"min_feature_mm": 0.8, "layer_mm": 0.2, "overhang_area_frac": 0.15},
    # Resin (SLA/DLP/LCD): finer features, steeper overhangs tolerable with light supports.
    "resin": {"min_feature_mm": 0.3, "layer_mm": 0.05, "overhang_area_frac": 0.45},
}


@dataclass
class BuildVolume:
    """Printer build volume in millimetres (default: a common 220×220×250 FDM bed)."""

    x: float = 220.0
    y: float = 220.0
    z: float = 250.0


def check_manufacturability(
    stats: Dict[str, Any],
    process: str = "fdm",
    build_volume: Optional[BuildVolume] = None,
) -> Dict[str, Any]:
    """
    Evaluate single-material printability from a stats dict and return a strict verdict.

    Recognised ``stats`` keys (all optional — unknown checks are skipped):
        min_feature_mm            : float  thinnest wall/strut in the mesh
        overhang_area_frac        : float  fraction of surface area exceeding the overhang rule
        bbox_mm                   : (x, y, z) overall bounding box
        woven_min_center_dist_mm  : float  min center distance between distinct woven fibers
        fiber_radius_mm           : float  chosen swept-tube radius (woven)

    Returns: {"printable": bool, "process": str, "violations": [...], "suggestions": [...]}.
    """
    limits = PROCESS_LIMITS.get(process, PROCESS_LIMITS["fdm"])
    bv = build_volume or BuildVolume()
    violations: List[Dict[str, Any]] = []
    suggestions: List[str] = []
    notes: List[str] = []

    # --- minimum feature / wall thickness ---
    mf = stats.get("min_feature_mm")
    if mf is None:
        notes.append("min_feature_mm not provided (skipped)")
    elif mf < limits["min_feature_mm"]:
        violations.append(
            {
                "type": "min_feature",
                "value_mm": round(float(mf), 3),
                "limit_mm": limits["min_feature_mm"],
            }
        )
        suggestions.append(
            f"thicken or scale up so the minimum feature is >= {limits['min_feature_mm']} mm "
            f"(currently {mf:.3f} mm)"
        )

    # --- overhang (FDM only; resin handled by supports) ---
    oa = stats.get("overhang_area_frac")
    if oa is not None and process == "fdm" and oa > limits["overhang_area_frac"]:
        violations.append(
            {
                "type": "overhang",
                "area_frac": round(float(oa), 3),
                "limit_frac": limits["overhang_area_frac"],
            }
        )
        suggestions.append(
            "add breakaway supports or reorient to reduce steep (>45°) overhang area"
        )

    # --- build volume ---
    bbox = stats.get("bbox_mm")
    if bbox is not None:
        over = [round(float(b), 1) for b, lim in zip(bbox, (bv.x, bv.y, bv.z)) if b > lim]
        if over:
            violations.append(
                {
                    "type": "build_volume",
                    "bbox_mm": [round(float(b), 1) for b in bbox],
                    "limit_mm": [bv.x, bv.y, bv.z],
                }
            )
            suggestions.append("scale down or split the model to fit the build volume")

    # --- woven fiber interpenetration (tubes must not fuse) ---
    mcd = stats.get("woven_min_center_dist_mm")
    fr = stats.get("fiber_radius_mm")
    if mcd is not None and fr is not None and fr > mcd / 2.0:
        violations.append(
            {
                "type": "fiber_fusion",
                "min_center_dist_mm": round(float(mcd), 3),
                "fiber_radius_mm": round(float(fr), 3),
                "max_radius_mm": round(mcd / 2.0, 3),
            }
        )
        suggestions.append(
            f"reduce fiber radius to <= {mcd/2.0:.3f} mm, raise R_eff/L, or lower n_rev "
            "so the woven tubes don't interpenetrate"
        )

    return {
        "printable": len(violations) == 0,
        "process": process,
        "violations": violations,
        "suggestions": suggestions,
        "notes": notes,
    }


class ManufacturabilityNode:
    """
    Graph node (a plain callable on DesignState). Reads ``state['mesh_stats']`` (populated by the
    Blender validation step and/or the generator), writes ``state['manufacturability']`` (the verdict) and
    ``state['manufacturable']`` (bool). Non-blocking: with no stats it returns printable=True plus a note, so
    adding it to the graph never breaks an existing run.
    """

    def __init__(
        self,
        process: str = "fdm",
        build_volume: Optional[BuildVolume] = None,
        deep_audit: bool = True,
    ):
        self.process = process
        self.build_volume = build_volume or BuildVolume()
        # Deep audit (2026-07-03): when the state carries an exported STL, run the FULL
        # quantitative print audit (abcad/printing/print_audit.py: EDT wall-thickness ladder, clearance/
        # fusion, enclosed voids, watertightness) on the geometry. This is what actually catches the
        # #1 print blocker (thin features) that render-time mesh_stats cannot see. It runs ONCE per
        # VLM-approved design (~30-90 s, memory-capped voxel grids), never inside the repair loop.
        self.deep_audit = deep_audit

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Grade the design on ``state``, optionally deep-audit its STL, and record the verdict."""
        state["last_node"] = "manufacturability"
        stats = state.get("mesh_stats") or {}
        verdict = check_manufacturability(stats, self.process, self.build_volume)
        if not stats:
            verdict["notes"].append("no mesh_stats on state — manufacturability not evaluated")

        # --- deep geometry audit on the exported STL (thin features, fusion, voids) ---
        stl = state.get("stl_path")

        # Target-size normalization (off by default): the LoRA emits arbitrary "mm" sizes and
        # print viability depends on ABSOLUTE size. If ABCAD_TARGET_SIZE_MM is set, deterministically
        # rescale the exported STL to that largest-bbox dimension BEFORE the deep gate audits it, so the
        # gate grades the size that will actually print. Architecture is unchanged (uniform scale).
        _target = os.environ.get("ABCAD_TARGET_SIZE_MM", "").strip()
        if self.deep_audit and stl and os.path.exists(stl) and _target:
            try:
                fv = _load_fdm_variants()
                norm_path = os.path.splitext(stl)[0] + "_sized.stl"
                rec = fv.normalize_to_target_size(stl, float(_target), norm_path)
                state["stl_path"] = stl = norm_path
                state["size_normalization"] = rec
                print(
                    f"[size-normalize] size-normalized to {rec['new_max_mm']} mm (was {rec['orig_max_mm']}, "
                    f"target {rec['target_max_mm']})"
                )
            except Exception as e:  # normalization is best-effort, never fatal
                verdict["notes"].append(f"target-size normalization failed: {e}")

        if self.deep_audit and stl and os.path.exists(stl):
            try:
                pa = _load_print_audit()
                s = pa.surface_checks(stl)
                vx = pa.voxel_checks(stl, s["bbox_mm"])  # auto voxel size, memory-capped grids
                deep = pa.grade(self.process, s, vx)
                verdict["deep_audit"] = {
                    "stl": stl,
                    "bbox_mm": s["bbox_mm"],
                    "volume_ml": s["volume_ml"],
                    "watertight": s["watertight"],
                    "manifold": s["manifold"],
                    "overhang_area_frac": s["overhang_area_frac"],
                    "voxel_mm": vx.get("voxel_mm"),
                    "max_formable_d_mm": vx.get("max_formable_d_mm"),
                    "lost_frac_at_d": vx.get("lost_frac_at_d"),
                    "enclosed_void_count": vx.get("enclosed_void_count"),
                    "verdict": deep["verdict"],
                    "issues": deep["issues"],
                    "recommendations": deep["recommendations"],
                }
                if deep["issues"]:
                    verdict["printable"] = False
                    verdict["violations"] = verdict["violations"] + [
                        {"type": "deep_audit", "detail": i} for i in deep["issues"]
                    ]
                    verdict["suggestions"] = verdict["suggestions"] + deep["recommendations"]

                    # --- Auto-scale (2026-07-03): a thin-feature failure has a DETERMINISTIC fix.
                    #     Uniform scaling preserves the architecture (and any FEA on it: E_eff/E is
                    #     scale-invariant), so instead of only ASKING the designer to thicken fibers,
                    #     emit the certified-scale variant right here and re-audit it. The run then
                    #     always ends with a printable artifact when geometry allows. Adds one extra
                    #     audit pass (~1-2 min), once per failing approved design. ---
                    import math

                    mf = vx.get("max_formable_d_mm")
                    lim = pa.PROCESS_LIMITS[self.process]["min_feature_mm"]
                    thin = any("thinner" in i for i in deep["issues"])
                    if thin and mf:
                        # one-decimal ceiling: never under-scale
                        k = math.ceil((lim / mf) * 10.0) / 10.0
                        fits = all(
                            b * k <= lv
                            for b, lv in zip(
                                s["bbox_mm"], pa.PROCESS_LIMITS[self.process]["build_mm"]
                            )
                        )
                        if k <= 4.0 and fits:  # x4 sanity cap: beyond that the part needs redesign
                            try:
                                import pyvista as pv

                                fv = _load_fdm_variants()
                                m = fv.scaled_about_base(pv.read(stl).triangulate(), k)
                                spath = os.path.splitext(stl)[0] + f"_autoscaled_x{k:g}.stl"
                                m.save(spath)
                                s2 = pa.surface_checks(spath)
                                vx2 = pa.voxel_checks(spath, s2["bbox_mm"])
                                d2 = pa.grade(self.process, s2, vx2)
                                verdict["deep_audit"]["autoscaled_variant"] = {
                                    "stl": spath,
                                    "scale": k,
                                    "verdict": d2["verdict"],
                                    "issues": d2["issues"],
                                    "max_formable_d_mm": vx2.get("max_formable_d_mm"),
                                }
                                state["stl_path_scaled"] = spath if not d2["issues"] else None
                                print(
                                    f"auto-scale x{k:g}: {os.path.basename(spath)} "
                                    f"-> {d2['verdict']}",
                                    flush=True,
                                )
                            except Exception as e:
                                verdict["notes"].append(f"auto-scale attempt failed: {e}")
                        else:
                            verdict["notes"].append(
                                f"auto-scale skipped (k={k:g}: exceeds x4 sanity cap or build volume)"
                            )
            except Exception as e:  # never let the audit kill an approved run
                verdict["notes"].append(f"deep print audit skipped (error: {e})")
        elif self.deep_audit and not stl:
            verdict["notes"].append("no stl_path on state — deep print audit skipped")

        state["manufacturability"] = verdict
        state["manufacturable"] = bool(verdict["printable"])
        # Surface suggestions to the Refinement agent via the same channel the VLM critique uses.
        if not verdict["printable"]:
            extra = " | MANUFACTURABILITY: " + "; ".join(verdict["suggestions"])
            state["vlm_feedback"] = (state.get("vlm_feedback") or "") + extra
        _deep = verdict.get("deep_audit")
        print(
            f"Manufacturability ({self.process}): printable={verdict['printable']} "
            f"violations={[v['type'] for v in verdict['violations']]}"
            + (
                f"  | deep: {_deep['verdict']} max_formable={_deep['max_formable_d_mm']}mm"
                if _deep
                else ""
            )
        )
        return state


def route_after_manufacturability(state: Dict[str, Any], max_iter: int = 3) -> str:
    """
    Pure routing decision for the agentic graph (NO langgraph import, so it is unit-testable here).
    Returns 'end' if the design is manufacturable (or iterations are exhausted), else 'refine' to send it to
    the CodeDesigner (which will act on the suggestions ManufacturabilityNode appended to vlm_feedback).
    """
    if state.get("manufacturable", True):
        return "end"
    if int(state.get("iteration_count", 0)) < max_iter:
        return "refine"
    return "end"
