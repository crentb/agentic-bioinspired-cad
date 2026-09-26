"""
abcad/fea/run_tension_finite.py — FINITE-STRAIN (large-stretch) uniaxial tension of a hex mesh, SfePy.

PURPOSE
    Pull a plated voxel-hex lattice (or a validation block) in tension under GEOMETRIC NONLINEARITY, so the
    woven stiffening that a linear solver cannot show (toward stretch lambda up to ~4) can actually appear.
    Produces a nominal-stress vs stretch curve (CSV + optional plot) and the small-strain effective modulus.

WHY (vs run_tension.py)
    run_tension.py reuses the stock biomimetic-lattice-pipeline solver, which is LINEAR small-strain
    (tension == compression in |E_eff|). This module is a self-contained TOTAL-LAGRANGIAN, compressible
    NEO-HOOKEAN solve (dw_tl_he_neohook shear + dw_tl_bulk_penalty bulk) with a Newton solver, load-stepped
    to a target strain (= strain control). It is the path for testing the lattices properly in tension.

METHOD (validated on a block: small-strain slope recovers E)
    - Material: mu = E/2(1+nu), K = E/3(1-2nu)  [MPa]. Compressible -> displacement-only TL form (no u-p mix).
    - BCs: bottom plate fully fixed (u=0); top plate pulled +z by a ramped displacement (lateral free) — the
      same bonded-plate grip as the mesh. Top/Bottom regions = the mesh z-extremes (our loading plates).
    - Load stepping: SimpleTimeSteppingSolver ramps the top displacement 0 -> max over n_step (strain control).
    - Reaction per step: the residual returned by evaluate(mode='weak') is REDUCED (free DOFs only), so the
      reaction is recovered by re-evaluating the FULL internal-force vector at each saved displacement with the
      EBCs cleared, then summing the z-component over the fixed-face nodes. E_eff = (|F|/A0)/strain.

INPUTS (CLI; mm / MPa)
    --msh PATH        hex mesh (.msh/.vtk). Footprint A0 + height H0 are read from the sidecar <msh>.json
                      (written by voxel_plate_mesh.py) unless --A0/--H0 are given.
    --block L,n       INSTEAD of --msh: a validation block "Lx,Ly,Lz,nx,ny,nz" (e.g. 10,10,20,5,5,9).
    --E MPA           solid Young's modulus (default 3000 — resin).      --nu (default 0.40)
    --max-strain      nominal tensile strain target (default 0.10).      --nsteps (default 6)
    --A0 / --H0       override footprint area [mm^2] / height [mm].
    --out PATH        stress-stretch CSV (default <msh>.tension_finite.csv, or $ABCAD_OUT/block... for
                      --block).   --png PATH  optional plot.

OUTPUTS
    CSV (step, stretch lambda, top displacement, reaction force N, nominal stress MPa, and each step's
    Newton record: converged flag, iterations, final residual N) + optional PNG plot; prints the curve
    and the small-strain effective modulus. Exit status 0 when every loaded step converged, 3 when any
    did not (those rows are not equilibrium states). On thin-fibre lattices keep the strain increment
    at about 0.005 per step (validated); larger increments can exhaust the Newton iterations.
    Run with the sfepy_env interpreter:
      "$ABCAD_SFEPY_PYTHON" -u -m abcad.fea.run_tension_finite --msh out/woven_fea_small.msh
      (or the file directly: "$ABCAD_SFEPY_PYTHON" -u abcad/fea/run_tension_finite.py ...)

SIDE EFFECTS
    Pure compute; writes the CSV/PNG. Needs sfepy (+ numpy; matplotlib optional) — i.e. run in sfepy_env.
    Imports nothing from ``abcad`` so it runs standalone in that environment.
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from sfepy.base.base import IndexedStruct, output
from sfepy.discrete import Equation, Equations, FieldVariable, Function, Integral, Material, Problem
from sfepy.discrete.conditions import Conditions, EssentialBC
from sfepy.discrete.fem import FEDomain, Field, Mesh
from sfepy.mesh.mesh_generators import gen_block_mesh
from sfepy.solvers.ls import ScipyDirect
from sfepy.solvers.nls import Newton
from sfepy.solvers.ts_solvers import SimpleTimeSteppingSolver
from sfepy.terms import Term

# Output root: ./out under the working directory unless ABCAD_OUT points elsewhere (used only for the
# default CSV name of a --block validation run, which has no mesh path to derive a name from).
_OUT_ROOT = os.environ.get("ABCAD_OUT", "out")


def build_domain(args):
    """Return (domain, A0 [mm^2], H0 [mm]) from a mesh file or a generated validation block."""
    if args.block:
        Lx, Ly, Lz, nx, ny, nz = [float(x) for x in args.block.split(",")]
        # Block centred at z = Lz/2 so it spans z in [0, Lz] (bottom face at z = 0).
        mesh = gen_block_mesh(
            [Lx, Ly, Lz], [int(nx), int(ny), int(nz)], [0, 0, Lz / 2.0], name="block", verbose=False
        )
        domain = FEDomain("domain", mesh)
        return domain, Lx * Ly, Lz
    mesh = Mesh.from_file(args.msh)
    domain = FEDomain("domain", mesh)
    bb = domain.get_mesh_bounding_box()
    H0 = float(bb[1][2] - bb[0][2])
    # A0/H0 prefer the sidecar (true nominal footprint), else CLI, else the mesh bbox.
    A0 = None
    side = args.msh + ".json"
    if os.path.exists(side):
        d = json.load(open(side))
        A0 = float(d.get("footprint_area_mm2"))
        H0 = float(d.get("height_mm", H0))
    if args.A0:
        A0 = args.A0
    if A0 is None:
        A0 = float((bb[1][0] - bb[0][0]) * (bb[1][1] - bb[0][1]))
    if args.H0:
        H0 = args.H0
    return domain, A0, H0


def main(argv=None):
    """CLI entry point: load-stepped neo-Hookean tension, reaction recovery, CSV (+ plot)."""
    output.set_output(quiet=True)  # silence sfepy's per-iteration logging

    # --- 1. CLI ---
    ap = argparse.ArgumentParser(
        description="Finite-strain (neo-Hookean TL) uniaxial tension of a hex mesh."
    )
    ap.add_argument("--msh", default="")
    ap.add_argument("--block", default="", help='validation block "Lx,Ly,Lz,nx,ny,nz"')
    ap.add_argument("--E", type=float, default=3000.0)
    ap.add_argument("--nu", type=float, default=0.40)
    ap.add_argument("--max-strain", dest="max_strain", type=float, default=0.10)
    ap.add_argument("--nsteps", type=int, default=6)
    ap.add_argument("--A0", type=float, default=0.0)
    ap.add_argument("--H0", type=float, default=0.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--png", default="")
    a = ap.parse_args(argv)
    if not a.msh and not a.block:
        ap.error("give --msh PATH or --block Lx,Ly,Lz,nx,ny,nz")

    # --- 2. Domain, regions (Top/Bottom = mesh z-extremes = the loading plates) ---
    domain, A0, H0 = build_domain(a)
    omega = domain.create_region("Omega", "all")
    bb = domain.get_mesh_bounding_box()
    zmin, zmax = float(bb[0][2]), float(bb[1][2])
    tol = 1e-4 * (zmax - zmin)  # relative tolerance for picking the extreme-z facets
    bottom = domain.create_region("Bottom", f"vertices in (z < {zmin + tol:.8f})", "facet")
    top = domain.create_region("Top", f"vertices in (z > {zmax - tol:.8f})", "facet")

    # --- 3. Field, neo-Hookean material, TL balance equation ---
    mu = a.E / (2.0 * (1.0 + a.nu))  # shear modulus [MPa]
    K = a.E / (3.0 * (1.0 - 2.0 * a.nu))  # bulk modulus  [MPa]
    field = Field.from_args("fu", np.float64, "vector", omega, approx_order=1)
    u = FieldVariable("u", "unknown", field, history=1)
    v = FieldVariable("v", "test", field, primary_var_name="u")
    m = Material("m", mu=mu, K=K)
    integ = Integral("i", order=2)
    eqs = Equations(
        [
            Equation(
                "balance",
                Term.new("dw_tl_he_neohook(m.mu, v, u)", integ, omega, m=m, v=v, u=u)
                + Term.new("dw_tl_bulk_penalty(m.K, v, u)", integ, omega, m=m, v=v, u=u),
            )
        ]
    )

    # --- 4. BCs: bottom fixed, top ramped in +z (strain control) ---
    max_disp = a.max_strain * H0  # top displacement at the final step [mm]

    def disp_fn(ts, coors, bc=None, problem=None):
        return np.full(coors.shape[0], max_disp * ts.time)  # ramp 0 -> max_disp over t in [0,1]

    ebcs = Conditions(
        [
            EssentialBC("fix", bottom, {"u.all": 0.0}),
            EssentialBC("pull", top, {"u.2": Function("disp_fn", disp_fn)}),
        ]
    )

    # --- 5. Solvers + time stepping ---
    nls = Newton({"i_max": 12, "eps_a": 1e-6}, lin_solver=ScipyDirect({}), status=IndexedStruct())
    pb = Problem("tension_finite", equations=eqs)
    pb.set_bcs(ebcs=ebcs)
    pb.set_ics(Conditions([]))
    pb.set_solver(
        SimpleTimeSteppingSolver(
            {"t0": 0.0, "t1": 1.0, "n_step": a.nsteps + 1}, nls=nls, context=pb
        )  # +1 so the first step is t=0
    )

    # Save the full displacement state at each load step (reaction is recovered post-hoc), together
    # with the Newton convergence record of that step. An unconverged step is NOT an equilibrium
    # state, so its reaction is meaningless; recording the status per step lets the report flag it
    # instead of silently writing a wrong curve (large strain increments on thin-fibre lattices can
    # exhaust the i_max = 12 Newton iterations).
    states = []

    def step_hook(problem, ts, variables):
        disp = max_disp * ts.time
        st = nls.status  # filled in by the Newton solver after each step's solve
        converged = getattr(st, "condition", 0) == 0  # sfepy: condition 0 = converged, 1 = not
        n_iter = int(getattr(st, "n_iter", 0) or 0)
        resid = float(getattr(st, "err", 0.0) or 0.0)  # final absolute residual norm [N]
        states.append((disp, problem.get_variables()["u"]().copy(), converged, n_iter, resid))
        # flushed per-step progress so the load-stepping is observable in real time (run with python -u)
        print(
            f"[finite]   step {ts.step}/{ts.n_step - 1}  strain={disp / H0:.4f}  disp={disp:.3f} mm  "
            f"Newton {n_iter} it, |r|={resid:.2e} N, {'converged' if converged else 'NOT CONVERGED'}",
            flush=True,
        )

    print(
        f"[finite] neo-Hookean TL tension: E={a.E} nu={a.nu} mu={mu:.1f} K={K:.1f} MPa | "
        f"A0={A0:.1f} mm^2 H0={H0:.2f} mm | target strain={a.max_strain} in {a.nsteps} steps",
        flush=True,
    )
    pb.solve(save_results=False, step_hook=step_hook)

    # --- 6. Reaction per step (VALIDATED for both --block AND loaded --msh meshes) ---
    # The clear-EBC + time_update replay below recovers the FULL internal-force vector (with EBCs active,
    # evaluate(dw_mode='vector') returns only the REDUCED free-DOF residual, which excludes exactly the
    # reaction DOFs — so clearing the EBCs first is required), then sums its z-component over the fixed
    # bottom face. Validated 2026-07-03 on the real out/woven_fea_tiny.msh (17,685 hex, 64% node-stripped):
    # E_eff = 93.1 MPa at 0.5% strain vs the trusted LINEAR reference 91.8 MPa on the same mesh (+1.4%),
    # interior residual ~7e-7 N (equilibrium), and the residual is BIT-IDENTICAL to an independent no-EBC
    # companion problem. Also validated on gen_block_mesh (--block: small-strain E_eff == E, 2026-06-04)
    # and on a faithful 1.0 mm woven proxy (84 MPa, 2026-06-29). An earlier "material-drop / ~200x wrong"
    # report (2026-06-24) did not reproduce and its diagnosis was refuted point-by-point (see docs/FEA.md).
    zdofs = 3 * bottom.vertices + 2  # z-DOF of each fixed-face node (vector field: 3*node+comp)
    bexpr = "dw_tl_he_neohook.2.Omega(m.mu, v, u) + dw_tl_bulk_penalty.2.Omega(m.K, v, u)"
    pb.set_bcs(ebcs=Conditions([]))
    pb.time_update()
    rows = []
    newton = []  # per-step (converged, iterations, final residual [N]) — reported with the curve
    for disp, sol, converged, n_iter, resid in states:
        pb.get_variables().set_state(sol, reduced=False)
        R = pb.evaluate(bexpr, mode="weak", dw_mode="vector", copy_materials=False)
        F = abs(float(R[zdofs].sum()))  # axial reaction [N]
        strain = disp / H0
        # row = (stretch lambda, disp [mm], strain, reaction F [N], nominal stress F/A0 [MPa])
        rows.append((1.0 + strain, disp, strain, F, F / A0))
        newton.append((converged, n_iter, resid))

    # --- 7. Report + write CSV (+ optional plot) ---
    print(" step  stretch  disp_mm   strain    F_N          nominal_MPa")
    for i, (lam, disp, strain, F, sig) in enumerate(rows):
        print(f" {i:4d}  {lam:.4f}  {disp:7.3f}  {strain:7.4f}  {F:11.2f}   {sig:9.4f}")
    # small-strain effective modulus from the first loaded step
    if len(rows) > 1 and rows[1][2] > 0:
        E_eff0 = rows[1][4] / rows[1][2]
        print(
            f"[finite] small-strain E_eff = {E_eff0:.2f} MPa ({E_eff0/a.E*100:.2f}% of solid E={a.E})"
        )
    if len(rows) > 1:
        # secant modulus between consecutive load steps: rising = stiffening, falling = softening
        sec = [
            (rows[i][4] - rows[i - 1][4]) / (rows[i][2] - rows[i - 1][2])
            for i in range(1, len(rows))
        ]
        print(
            f"[finite] secant modulus first->last step: {sec[0]:.1f} -> {sec[-1]:.1f} MPa "
            f"({'stiffening' if sec[-1] > sec[0] else 'softening'})"
        )

    # --- Convergence verdict: a curve with an unconverged step is not a result -----------------
    # Step 0 is the unloaded reference state; every loaded step must have converged for the curve
    # (and the small-strain modulus taken from step 1) to be trusted.
    bad = [i for i, (ok, _, _) in enumerate(newton) if i > 0 and not ok]
    if bad:
        per_step = a.max_strain / max(a.nsteps, 1)
        print(
            f"[finite] WARNING: Newton did NOT converge at load step(s) {bad}; those rows are not "
            f"equilibrium states and the curve is unreliable. Use smaller strain increments "
            f"(now {per_step:.4f} per step; on thin-fibre lattices 0.005 per step is validated): "
            f"raise --nsteps or lower --max-strain."
        )

    out_csv = a.out or ((a.msh or os.path.join(_OUT_ROOT, "block")) + ".tension_finite.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w") as fh:
        # The three trailing columns record each step's Newton convergence so a consumer can
        # reject unconverged rows (appended last to keep the original column positions).
        fh.write(
            "stretch,disp_mm,strain,reaction_N,nominal_stress_MPa,"
            "newton_converged,newton_iters,newton_residual_N\n"
        )
        for (lam, disp, strain, F, sig), (ok, n_iter, resid) in zip(rows, newton):
            fh.write(
                f"{lam:.6f},{disp:.6f},{strain:.6f},{F:.6f},{sig:.6f},{int(ok)},{n_iter},{resid:.3e}\n"
            )
    print(f"[finite] wrote {out_csv}")

    if a.png:
        try:
            import matplotlib

            matplotlib.use("Agg")  # headless backend: file output only
            import matplotlib.pyplot as plt

            arr = np.array([(r[0], r[4]) for r in rows])
            plt.figure(figsize=(6, 4.5))
            plt.plot(arr[:, 0], arr[:, 1], "o-", color="#b5402a")
            plt.xlabel("stretch  $\\lambda = l/l_0$")
            plt.ylabel("nominal stress  [MPa]")
            plt.title("Finite-strain tension (neo-Hookean TL)")
            plt.grid(alpha=0.3)
            plt.tight_layout()
            plt.savefig(a.png, dpi=130)
            plt.close()
            print(f"[finite] plot -> {a.png}")
        except Exception as e:
            print(f"[finite] (plot skipped: {e})")

    # Exit status 3 flags an unconverged solve to scripts and CI (0 = every loaded step converged).
    return 3 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
