"""
test_woven_logic.py — Tests for the Tier-1 woven generator (vendored engine + adapter).

The vendored engine is pure numpy+scipy, so unlike the Blender sweep we CAN run it here and verify the
real centerline geometry (counts, scaling, clearance, grading). The Blender sweep path is exercised against
a mock ``bpy`` (injected per test with monkeypatch). A real-Blender STL check is a separate step.

Run:  python -m pytest tests/test_woven_logic.py
(fast suite: needs numpy + scipy only — matplotlib is stubbed if absent. A few-second engine run per
topology.)
"""

from __future__ import annotations

import types

import numpy as np
import pytest

from abcad.generators.woven import build as W


def extent(paths):
    """Axis-aligned extent (max - min per axis) of all centerline points."""
    pts = np.vstack([np.asarray(p) for p in paths])
    return pts.max(0) - pts.min(0)


# --------------------------------------------------------------------------------------------------
# Real engine geometry (runs here).
# --------------------------------------------------------------------------------------------------
def test_centerlines_cubic():
    P = W.Params(topology="cubic", cells=(1, 1, 1), unitcell=40.0)
    paths = W.run_centerlines(P)
    assert len(paths) > 0, "cubic returns fibers"
    assert all(
        np.asarray(p).ndim == 2 and np.asarray(p).shape[1] == 3 and len(p) >= 2 for p in paths
    ), "each centerline is Nx3 with >=2 points"


@pytest.mark.parametrize("topo", ["bcc", "diamond"])
def test_topology_generality(topo):
    # A couple more topologies to ensure the driver generalizes (kept small for runtime).
    P = W.Params(topology=topo, cells=(1, 1, 1), unitcell=40.0)
    paths = W.run_centerlines(P)
    assert len(paths) > 0, f"{topo} returns fibers"


def test_bbox_scales_with_unitcell():
    e1 = extent(W.run_centerlines(W.Params(topology="cubic", cells=(1, 1, 1), unitcell=40.0)))
    e2 = extent(W.run_centerlines(W.Params(topology="cubic", cells=(1, 1, 1), unitcell=80.0)))
    ratio = float(np.mean(e2 / e1))
    assert 1.8 <= ratio <= 2.2, f"bbox doubles when unitcell doubles (ratio={ratio:.2f})"


def test_clearance():
    paths = W.run_centerlines(W.Params(topology="cubic", cells=(1, 1, 1), unitcell=40.0))
    cl_small = W.clearance(paths, fiber_radius=0.05)
    cl_huge = W.clearance(paths, fiber_radius=999.0)
    assert cl_small["min_center_dist"] > 0, "clearance reports a positive min center distance"
    assert (
        abs(cl_small["max_printable_fiber_radius"] - cl_small["min_center_dist"] / 2) < 1e-9
    ), "max printable radius = min_dist/2"
    assert cl_small["interpenetrates"] is False, "tiny fiber does not interpenetrate"
    assert cl_huge["interpenetrates"] is True, "huge fiber interpenetrates"


def test_linear_grading():
    P = W.Params(
        grade="linear", grade_axis=2, reff_bot=0.05, reff_top=0.15, unitcell=40.0, cells=(1, 1, 2)
    )
    sp = W.make_strut_params(P)
    L = P.unitcell / 2.0
    r_low = sp((0.0, 0.0, -1.0), L)[0]  # near the bottom of the grade axis
    r_high = sp((0.0, 0.0, 1.0), L)[0]  # near the top
    assert r_high > r_low > 0, "graded R_eff increases along the axis"
    assert (
        W.make_strut_params(W.Params(unitcell=40.0))((0, 0, -1), L)[0]
        == W.make_strut_params(W.Params(unitcell=40.0))((0, 0, 1), L)[0]
    ), "uniform mode ignores position"


def test_save_load_roundtrip(tmp_path):
    paths = [
        np.array([[0, 0, 0], [1, 1, 1], [2, 0, 2]], float),
        np.array([[0, 1, 0], [1, 0, 1]], float),
    ]
    P = W.Params(fiber_radius=0.37, unitcell=42.0, topology="cubic")
    tmp = str(tmp_path / "_woven_cl.npz")
    W.save_centerlines(paths, P, tmp)
    loaded, meta = W.load_centerlines(tmp)
    assert len(loaded) == 2, "roundtrip preserves fiber count"
    assert np.allclose(loaded[0], paths[0]) and np.allclose(
        loaded[1], paths[1]
    ), "roundtrip preserves arrays"
    assert (
        abs(meta["fiber_radius"] - 0.37) < 1e-9 and meta["topology"] == "cubic"
    ), "roundtrip preserves metadata"


@pytest.mark.parametrize(
    "P",
    [
        W.Params(topology="spiral"),
        W.Params(cells=(0, 1, 1)),
        W.Params(unitcell=-1),
        W.Params(stage="bogus"),
    ],
)
def test_validate_rejects_bad_input(P):
    with pytest.raises(ValueError):
        P.validate()


# --------------------------------------------------------------------------------------------------
# Sweep path against a mock bpy.
# --------------------------------------------------------------------------------------------------
class _Pt:
    """One spline point with a homogeneous coordinate slot."""

    def __init__(self):
        self.co = (0, 0, 0, 1)


class _Pts:
    """Spline point list; ``add(n)`` appends n points like Blender's API."""

    def __init__(self):
        self._l = [_Pt()]  # a fresh POLY spline starts with one point

    def add(self, n):
        self._l.extend(_Pt() for _ in range(n))

    def __getitem__(self, i):
        return self._l[i]

    def __len__(self):
        return len(self._l)


class _Spline:
    """A fake spline of a given kind with its point list."""

    def __init__(self, kind):
        self.kind = kind
        self.points = _Pts()


class _CurveData:
    """Fake curve datablock carrying the bevel attributes build.py sets."""

    def __init__(self, name, kind):
        self.name, self.kind = name, kind
        self.dimensions = "2D"
        self.bevel_depth = 0.0
        self.bevel_resolution = 0
        self.bevel_mode = "ROUND"
        self.bevel_object = None
        self._splines = []

    @property
    def splines(self):
        return types.SimpleNamespace(new=lambda kind: self._new_spline(kind))

    def _new_spline(self, kind):
        s = _Spline(kind)
        self._splines.append(s)
        return s


class _Obj:
    """A fake Blender object with a selection flag."""

    def __init__(self, name, data=None):
        self.name, self.data, self.selected = name, data, False

    def select_set(self, v):
        self.selected = v


class MockBpyCurves:
    """Records curve/object creation, convert/join and export calls of the Blender sweep."""

    def __init__(self):
        self.stats = {"curves": 0, "objects": 0, "joins": 0, "converts": 0, "exports": 0}
        self._objs = []
        coll_objs = types.SimpleNamespace(link=lambda o: self._objs.append(o))
        self.context = types.SimpleNamespace(
            object=None,
            collection=types.SimpleNamespace(objects=coll_objs),
            view_layer=types.SimpleNamespace(objects=types.SimpleNamespace(active=None)),
        )
        self.data = types.SimpleNamespace(
            curves=types.SimpleNamespace(new=self._curve_new),
            objects=types.SimpleNamespace(new=self._obj_new, remove=self._obj_remove),
        )
        self.ops = types.SimpleNamespace(
            object=types.SimpleNamespace(
                select_all=lambda action="SELECT": self._select_all(action),
                delete=lambda use_global=False: None,
                convert=lambda target="MESH": self._convert(),
                join=lambda: self._join(),
            ),
            curve=types.SimpleNamespace(
                primitive_bezier_circle_add=lambda radius=1.0: self._obj_new("ellipse", None)
            ),
            wm=types.SimpleNamespace(
                stl_export=lambda filepath=None, export_selected_objects=True: self._export()
            ),
            export_mesh=types.SimpleNamespace(
                stl=lambda filepath=None, use_selection=True: self._export()
            ),
        )

    def _curve_new(self, name, kind):
        self.stats["curves"] += 1
        return _CurveData(name, kind)

    def _obj_new(self, name, data):
        o = _Obj(name, data)
        self.stats["objects"] += 1
        self.context.object = o
        return o

    def _obj_remove(self, obj, do_unlink=False):
        if obj in self._objs:
            self._objs.remove(obj)

    def _select_all(self, action):
        for o in self._objs:
            o.selected = action == "SELECT"

    def _convert(self):
        self.stats["converts"] += 1

    def _join(self):
        self.stats["joins"] += 1
        self.context.object = self.context.view_layer.objects.active

    def _export(self):
        self.stats["exports"] += 1


def test_sweep_path_mock(monkeypatch, tmp_path):
    # Inject the mock for this test only (restored afterwards so other tests see the real module).
    monkeypatch.setattr(W, "bpy", MockBpyCurves())
    monkeypatch.setattr(W, "_HAVE_BPY", True)
    paths = [np.linspace([0, 0, 0], [10, 0, 0], 12), np.linspace([0, 2, 0], [10, 2, 5], 20)]
    W.sweep_centerlines(paths, fiber_radius=0.4, bevel_resolution=6, eccentricity=1.0)
    s = W.bpy.stats
    assert s["curves"] == 2, "a curve is created per centerline"
    assert s["objects"] == 2, "an object is created per centerline"
    assert s["converts"] == 1 and s["joins"] == 1, "curves are converted to mesh and joined"
    W.export_stl(str(tmp_path / "_woven_mock.stl"))
    assert s["exports"] >= 1, "export_stl triggers an STL export"
