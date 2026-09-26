"""
test_helicoidal_build_mock.py — Exercise the Blender build path against a MOCK ``bpy``.

Without Blender we cannot validate that the produced GEOMETRY is correct. But we CAN catch Python-level
bugs in the build control flow (build(), the ply/groove/fibre/spine/export helpers, main(), CLI parsing)
by injecting a minimal fake ``bpy`` that records calls. A real-Blender geometry check is a separate step.

The mock is injected per test with ``monkeypatch`` (and removed afterwards), so it never leaks into the
pure-math tests in test_helicoidal_logic.py, which expect the real, Blender-less module state.

Run:  python -m pytest tests/test_helicoidal_build_mock.py   (fast suite; standard library only)
"""

from __future__ import annotations

import types

import pytest

from abcad.generators import helicoidal


# --------------------------------------------------------------------------------------------------
# Minimal stateful fake of the slice of bpy that helicoidal.py uses.
# --------------------------------------------------------------------------------------------------
class _Obj:
    """A fake Blender object: name, transform slots, selection flag and a modifier stack."""

    _n = 0

    def __init__(self):
        _Obj._n += 1
        self.name = f"obj{_Obj._n}"
        self.dimensions = [0, 0, 0]
        self.rotation_euler = [0, 0, 0]
        self.location = [0, 0, 0]
        self.selected = False
        self.modifiers = _Mods()

    def select_set(self, v):
        self.selected = v


class _Mod:
    """A fake modifier (only the attributes helicoidal.py sets)."""

    def __init__(self, name, type):
        self.name, self.type, self.operation, self.object = name, type, None, None


class _Mods:
    """A fake modifier collection supporting ``new(name, type)``."""

    def __init__(self):
        self._l = []

    def new(self, name, type):
        m = _Mod(name, type)
        self._l.append(m)
        return m


class MockBpy:
    """Records object creation, joins, deletes, and STL exports while letting build() run to completion."""

    def __init__(self):
        cursor = types.SimpleNamespace(location=(0, 0, 0))
        vlobjects = types.SimpleNamespace(active=None)
        self.context = types.SimpleNamespace(
            object=None,
            view_layer=types.SimpleNamespace(objects=vlobjects),
            scene=types.SimpleNamespace(cursor=cursor),
        )
        self._items = []
        self.stats = {"created": 0, "joins": 0, "deletes": 0, "exports": 0}
        self.data = types.SimpleNamespace(objects=types.SimpleNamespace(remove=self._remove))
        self.ops = types.SimpleNamespace(
            object=types.SimpleNamespace(
                select_all=lambda action="SELECT": self._select_all(action),
                delete=lambda use_global=False: self._delete_selected(),
                transform_apply=lambda **k: None,
                modifier_apply=lambda modifier=None: None,
                join=lambda: self._join(),
                origin_set=lambda type=None: None,
            ),
            mesh=types.SimpleNamespace(
                primitive_cube_add=lambda size=1.0, location=(0, 0, 0): self._new(),
                primitive_cylinder_add=self._new_cylinder,
            ),
            wm=types.SimpleNamespace(
                stl_export=lambda filepath=None, export_selected_objects=True: self._export()
            ),
            export_mesh=types.SimpleNamespace(
                stl=lambda filepath=None, use_selection=True: self._export()
            ),
        )

    def _new(self):
        o = _Obj()
        self._items.append(o)
        self.context.object = o
        self.stats["created"] += 1
        return o

    def _new_cylinder(self, radius=1.0, depth=1.0, location=(0, 0, 0), rotation=(0, 0, 0)):
        # Same keyword signature helicoidal.py passes to bpy.ops.mesh.primitive_cylinder_add.
        return self._new()

    def _remove(self, obj, do_unlink=False):
        if obj in self._items:
            self._items.remove(obj)

    def _select_all(self, action):
        for o in self._items:
            o.selected = action == "SELECT"

    def _delete_selected(self):
        before = len(self._items)
        self._items = [o for o in self._items if not o.selected]
        self.stats["deletes"] += before - len(self._items)
        self.context.object = None

    def _join(self):
        self.stats["joins"] += 1
        active = self.context.view_layer.objects.active
        for o in [x for x in self._items if x.selected and x is not active]:
            self._items.remove(o)
        self.context.object = active
        return active

    def _export(self):
        self.stats["exports"] += 1


@pytest.fixture
def H(monkeypatch):
    """The helicoidal module with a MockBpy injected for this test only (restored afterwards)."""
    monkeypatch.setattr(helicoidal, "bpy", MockBpy())
    monkeypatch.setattr(helicoidal, "_HAVE_BPY", True)
    return helicoidal


def run_build(H, **kw):
    """Reset the mock counters, run build(), return (objects, stats)."""
    H.bpy = MockBpy()  # fresh state per build (the fixture's monkeypatch restores the original)
    P = H.Params(**kw)
    objs = H.build(P)
    return objs, H.bpy.stats


@pytest.mark.parametrize(
    "prog",
    ["constant", "graded", "exponential", "fibonacci", "double_twist", "herringbone", "noise"],
)
def test_build_every_progression(H, prog):
    objs, stats = run_build(
        H, progression=prog, num_plies=6, interface="solid", fiber_style="plate"
    )
    assert stats["created"] >= 6, f"build runs for progression={prog}"


@pytest.mark.parametrize("itf", ["solid", "groove", "airgap"])
def test_build_every_interface(H, itf):
    objs, stats = run_build(
        H, progression="constant", num_plies=5, interface=itf, fiber_style="plate"
    )
    # groove adds a cutter per ply; airgap adds a spine.
    expect_min = 5 if itf == "solid" else (10 if itf == "groove" else 6)
    assert stats["created"] >= expect_min, f"build runs for interface={itf} (created≥{expect_min})"
    assert stats["joins"] >= 1, f"interface={itf} joined into one mesh"


@pytest.mark.parametrize("style", ["plate", "rect_fibers", "cyl_fibers"])
def test_build_every_fiber_style(H, style):
    objs, stats = run_build(
        H, progression="constant", num_plies=4, interface="solid", fiber_style=style
    )
    assert stats["created"] >= 4, f"build runs for fiber_style={style}"


def test_main_with_export(H, tmp_path):
    H.bpy = MockBpy()
    H.main(
        [
            "--progression",
            "double_twist",
            "--plies",
            "8",
            "--interface",
            "solid",
            "--export_stl",
            "--stl_path",
            str(tmp_path / "_helicoidal_mock.stl"),
        ]
    )
    assert H.bpy.stats["exports"] >= 1, "main() with --export_stl triggers an STL export"


def test_cli_parsing(H):
    P = H.parse_args(
        [
            "--progression",
            "graded",
            "--delta",
            "12.5",
            "--plies",
            "24",
            "--interface",
            "groove",
            "--fiber_style",
            "cyl_fibers",
            "--no_join",
        ]
    )
    assert abs(P.delta_theta - 12.5) < 1e-9, "CLI maps --delta → delta_theta"
    assert P.num_plies == 24, "CLI maps --plies → num_plies"
    assert (
        P.progression == "graded" and P.interface == "groove" and P.fiber_style == "cyl_fibers"
    ), "CLI sets progression/interface/fiber_style"
    assert P.join_mesh is False, "CLI --no_join clears join_mesh"
