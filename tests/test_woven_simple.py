"""
test_woven_simple.py — Tests for the Tier-2 self-contained woven generator (no Blender, no scipy).

Covers the pure-Python lattice + helix-bundle math (which fully defines the geometry) and the Blender sweep
path via a mock bpy (injected per test with monkeypatch).

Run:  python -m pytest tests/test_woven_simple.py   (fast suite; standard library only)
"""

from __future__ import annotations

import math
import types

import pytest

from abcad.generators.woven import woven_simple as W


# --------------------------------------- lattice ---------------------------------------
def test_lattice_cubic_single():
    nodes, edges = W.lattice_nodes_edges(W.Params(topology="cubic", cells=(1, 1, 1), unitcell=40))
    assert len(nodes) == 8, "cubic 1×1×1 → 8 nodes"
    assert len(edges) == 12, "cubic 1×1×1 → 12 edges"


def test_lattice_bcc_single():
    nodes, edges = W.lattice_nodes_edges(W.Params(topology="bcc", cells=(1, 1, 1), unitcell=40))
    assert len(nodes) == 9, "bcc 1×1×1 → 9 nodes (8 corners + centre)"
    assert len(edges) == 8, "bcc 1×1×1 → 8 edges"


def test_lattice_dedup_across_cells():
    # Two cubic cells sharing a face: 8+8-4 nodes, 12+12-4 edges.
    nodes, edges = W.lattice_nodes_edges(W.Params(topology="cubic", cells=(2, 1, 1), unitcell=40))
    assert len(nodes) == 12, "shared face de-duplicates nodes (12)"
    assert len(edges) == 20, "shared face de-duplicates edges (20)"


# --------------------------------------- helix bundle ---------------------------------------
def test_helix_radius_and_count():
    A, B, r, nrev, nf = (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 1.0, 2.0, 4
    fibers = W.helix_bundle(A, B, r, nrev, nf, pts_per_rev=24)
    assert len(fibers) == nf, "bundle has n_fibers polylines"
    # For a beam along +x, perpendicular distance from the axis = sqrt(y²+z²) ≈ r_eff for every sample.
    maxerr = 0.0
    for poly in fibers:
        for _, y, z in poly:
            maxerr = max(maxerr, abs(math.hypot(y, z) - r))
    assert maxerr < 1e-9, f"all points lie at R_eff from the beam axis (max err={maxerr:.3e})"


def test_helix_winding_and_phase():
    A, B, r, nrev, nf = (0.0, 0.0, 0.0), (10.0, 0.0, 0.0), 1.0, 3.0, 3
    fibers = W.helix_bundle(A, B, r, nrev, nf, pts_per_rev=48)
    # Unwrapped angle should span ≈ 2π·nrev along a fiber.
    ang = [math.atan2(z, y) for (_, y, z) in fibers[0]]
    total = 0.0
    for k in range(1, len(ang)):
        d = ang[k] - ang[k - 1]
        while d > math.pi:
            d -= 2 * math.pi
        while d < -math.pi:
            d += 2 * math.pi
        total += d
    assert (
        abs(abs(total) - 2 * math.pi * nrev) < 0.2
    ), f"fiber sweeps ≈ 2π·nrev (got {total/(2*math.pi):.2f} rev, want {nrev})"
    # Distinct fibers start at distinct phases.
    starts = {round(math.atan2(p[0][2], p[0][1]), 3) for p in fibers}
    assert len(starts) == nf, "fibers have distinct starting phases"


def test_generate_and_clearance():
    P = W.Params(topology="cubic", cells=(1, 1, 1), unitcell=40, n_fibers=4, fiber_radius=0.5)
    paths = W.generate_centerlines(P)
    assert len(paths) == 48, "cubic 1×1×1 → 12 edges × 4 fibers = 48 fibers"
    cl = W.clearance(paths, fiber_radius=0.5)
    # In the Tier-2 model, fibers of different beams MEET at shared nodes (that is the joint that makes the
    # lattice one printable solid), so the global min center-distance is ~0 by design. The metric therefore
    # flags only gross over-thickening, not the intended node joins.
    assert math.isfinite(cl["min_center_dist"]), "clearance returns a finite min center distance"
    assert {"min_center_dist", "max_printable_fiber_radius", "interpenetrates"} <= set(
        cl
    ), "clearance exposes the expected keys"
    assert (
        W.clearance(paths, 999.0)["interpenetrates"] is True
    ), "a huge fiber radius interpenetrates"


@pytest.mark.parametrize(
    "P", [W.Params(topology="octahedron"), W.Params(cells=(0, 1, 1)), W.Params(unitcell=-1)]
)
def test_validate(P):
    # validate rejects bad params / unsupported topology
    with pytest.raises(ValueError):
        P.validate()


def test_auto_n_fibers():
    assert (
        W.Params(topology="cubic").resolved_n_fibers() == 4
        and W.Params(topology="bcc").resolved_n_fibers() == 3
    ), "auto n_fibers: cubic→4, bcc→3"


# --------------------------------------- sweep (mock bpy) ---------------------------------------
class _Pt:
    """One spline point with a homogeneous coordinate slot."""

    def __init__(self):
        self.co = (0, 0, 0, 1)


class _Pts:
    """Spline point list; ``add(n)`` appends n points like Blender's API."""

    def __init__(self):
        self._l = [_Pt()]

    def add(self, n):
        self._l.extend(_Pt() for _ in range(n))

    def __getitem__(self, i):
        return self._l[i]


class _Spline:
    """A fake spline holding its point list."""

    def __init__(self, k):
        self.points = _Pts()


class _CurveData:
    """Fake curve datablock carrying the bevel attributes woven_simple.py sets."""

    def __init__(self, name, k):
        self.dimensions = "2D"
        self.bevel_depth = 0.0
        self.bevel_resolution = 0
        self._s = []

    @property
    def splines(self):
        return types.SimpleNamespace(new=lambda k: self._mk(k))

    def _mk(self, k):
        s = _Spline(k)
        self._s.append(s)
        return s


class _Obj:
    """A fake Blender object with a selection flag."""

    def __init__(self, n, d=None):
        self.name = n
        self.data = d
        self.selected = False

    def select_set(self, v):
        self.selected = v


class MockBpy:
    """Records curve/object creation, convert/join and export calls of the Tier-2 sweep."""

    def __init__(self):
        self.stats = {"curves": 0, "objects": 0, "joins": 0, "converts": 0, "exports": 0}
        self._objs = []
        self.context = types.SimpleNamespace(
            object=None,
            collection=types.SimpleNamespace(
                objects=types.SimpleNamespace(link=lambda o: self._objs.append(o))
            ),
            view_layer=types.SimpleNamespace(objects=types.SimpleNamespace(active=None)),
        )
        self.data = types.SimpleNamespace(
            curves=types.SimpleNamespace(new=self._cn), objects=types.SimpleNamespace(new=self._on)
        )
        self.ops = types.SimpleNamespace(
            object=types.SimpleNamespace(
                select_all=lambda action="SELECT": [
                    setattr(o, "selected", action == "SELECT") for o in self._objs
                ],
                delete=lambda use_global=False: None,
                convert=lambda target="MESH": self.stats.update(
                    converts=self.stats["converts"] + 1
                ),
                join=lambda: self.stats.update(joins=self.stats["joins"] + 1),
            ),
            wm=types.SimpleNamespace(
                stl_export=lambda filepath=None, export_selected_objects=True: self.stats.update(
                    exports=self.stats["exports"] + 1
                )
            ),
            export_mesh=types.SimpleNamespace(
                stl=lambda filepath=None, use_selection=True: self.stats.update(
                    exports=self.stats["exports"] + 1
                )
            ),
        )

    def _cn(self, name, k):
        self.stats["curves"] += 1
        return _CurveData(name, k)

    def _on(self, name, d):
        o = _Obj(name, d)
        self.stats["objects"] += 1
        self.context.object = o
        return o


def test_sweep_mock(monkeypatch, tmp_path):
    # Inject the mock for this test only (restored afterwards so other tests see the real module).
    monkeypatch.setattr(W, "bpy", MockBpy())
    monkeypatch.setattr(W, "_HAVE_BPY", True)
    paths = W.generate_centerlines(W.Params(topology="cubic", cells=(1, 1, 1), n_fibers=4))
    W.sweep(paths, fiber_radius=0.5)
    s = W.bpy.stats
    assert s["curves"] == len(paths), "one curve per fiber created"
    assert s["converts"] == 1 and s["joins"] == 1, "curves converted + joined"
    W.export_stl(str(tmp_path / "_woven_simple_mock.stl"))
    assert s["exports"] >= 1, "export triggers STL export"
