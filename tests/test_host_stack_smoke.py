"""
test_host_stack_smoke.py — SLOW end-to-end smoke tests on the host-side stack.

Each test drives a real tool on a tiny input inside ``tmp_path`` and skips cleanly when its stack is
missing:
  * conda ``cad_env`` modules (pyvista / vtk / numpy-stl / meshio): the Blender-free woven sweep, the
    enamel sweep, plated voxel-hex meshing and the print audit;
  * ``sfepy_env``: the finite-strain tension driver on a validation block;
  * Blender: the helicoidal and Tier-2 woven generators executed as standalone Blender scripts
    (``blender -b -P <file> -- ...``), which is how they run in production. The executable is
    $ABCAD_BLENDER, else ``blender`` on PATH.
These prove the moved modules still run under the interpreters they target.

Run:  python -m pytest -m slow tests/test_host_stack_smoke.py   (under the conda cad_env interpreter)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.slow


def _need(*modules):
    """Skip the calling test unless every module in ``modules`` imports."""
    for m in modules:
        pytest.importorskip(m)


@pytest.fixture(scope="module")
def woven_stl(tmp_path_factory):
    """A small watertight woven STL from the Blender-free numpy-stl sweep (cad_env stack)."""
    _need("pyvista", "stl", "matplotlib", "scipy")
    from abcad.generators.woven import build

    out = tmp_path_factory.mktemp("woven") / "woven_c111.stl"
    build.main(
        [
            "--stage",
            "all_np",
            "--topology",
            "cubic",
            "--cells",
            "1",
            "1",
            "1",
            "--unitcell",
            "20",
            "--fiber_radius",
            "0.4",
            "--stl",
            str(out),
            "--no_render",
        ]
    )
    return out


def test_woven_numpy_sweep_is_watertight(woven_stl):
    from abcad.generators.woven import build

    rep = build.watertight_report(str(woven_stl))
    assert rep["watertight"] and rep["open_edges"] == 0 and rep["n_tris"] > 0


def test_enamel_sweep_small(tmp_path):
    _need("pyvista", "stl", "matplotlib")
    from abcad.generators import enamel

    P = enamel.Params(n_rings=1, scale=2.0, stl_path=str(tmp_path / "enamel.stl"), render=False)
    rep = enamel.build_stl(P)
    assert rep["n_rods"] == 7 and rep["n_bridges"] == 6 * P.n_bridge_layers
    assert (tmp_path / "enamel.stl").is_file()
    assert not list(tmp_path.glob("*.tmp.stl")), "temporary per-radius STLs are cleaned up"


def test_voxel_plate_mesh_small(woven_stl, tmp_path):
    _need("pyvista", "vtk", "meshio", "scipy")
    from abcad.fea import voxel_plate_mesh as vpm

    msh = tmp_path / "woven.msh"
    r = vpm.build_plated_hex_mesh(str(woven_stl), 0.5, 2.0, 0.8, str(msh), verbose=False)
    assert r.n_hex > 0 and msh.is_file() and (tmp_path / "woven.msh.json").is_file()


def test_print_audit_small(woven_stl, tmp_path):
    _need("pyvista", "vtk", "scipy")
    from abcad.printing import print_audit as pa

    res = pa.audit_one(str(woven_stl), ["fdm", "resin"], 0.25)
    pa.write_reports([res], str(tmp_path), ["fdm", "resin"])
    assert {g["process"] for g in res["grades"]} == {"fdm", "resin"}
    assert (tmp_path / "print_audit.csv").is_file() and (
        tmp_path / "print_audit_report.md"
    ).is_file()


def test_finite_strain_block(tmp_path):
    _need("sfepy")
    from abcad.fea import run_tension_finite

    out = tmp_path / "block.csv"
    run_tension_finite.main(
        ["--block", "10,10,20,3,3,5", "--nsteps", "2", "--max-strain", "0.02", "--out", str(out)]
    )
    rows = [line.split(",") for line in out.read_text().splitlines()[1:]]
    assert len(rows) == 3, "t = 0 plus two load steps"
    strain, sigma = float(rows[1][2]), float(rows[1][4])
    # Block validation: the small-strain slope recovers the solid modulus (coarse mesh: within 10%).
    assert sigma / strain == pytest.approx(3000.0, rel=0.10)


def _blender():
    """Blender executable: $ABCAD_BLENDER, else `blender` on PATH; skip when neither exists."""
    exe = os.environ.get("ABCAD_BLENDER") or shutil.which("blender")
    if not exe:
        pytest.skip("Blender not found (set ABCAD_BLENDER)")
    return exe


@pytest.mark.parametrize(
    "script, args",
    [
        (
            "abcad/generators/helicoidal.py",
            ["--progression", "double_twist", "--plies", "6", "--interface", "solid"],
        ),
        (
            "abcad/generators/woven/woven_simple.py",
            ["--topology", "cubic", "--cells", "1", "1", "1", "--unitcell", "20"],
        ),
    ],
)
def test_blender_standalone_scripts(script, args, repo_root, tmp_path):
    exe = _blender()
    stl = tmp_path / "out.stl"
    cmd = [exe, "-b", "--factory-startup", "-P", str(repo_root / script), "--", *args]
    cmd += ["--export_stl", "--stl_path", str(stl)]
    # Run outside the checkout so the script cannot rely on the working directory.
    proc = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True, timeout=600)
    assert stl.is_file() and stl.stat().st_size > 0, proc.stdout[-2000:] + proc.stderr[-2000:]


def test_standalone_file_execution_without_package(tmp_path, repo_root):
    """The cad_env tools still run as plain files when `abcad` is NOT importable (conda-env usage)."""
    _need("pyvista", "stl", "matplotlib", "scipy")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    out = tmp_path / "w.stl"
    cmd = [
        sys.executable,
        "-I",  # isolated mode: no cwd / user site on sys.path, so `import abcad` fails
        str(repo_root / "abcad/generators/woven/build.py"),
        "--stage",
        "all_np",
        "--cells",
        "1",
        "1",
        "1",
        "--unitcell",
        "20",
        "--stl",
        str(out),
        "--no_render",
    ]
    proc = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "watertight=True" in proc.stdout
