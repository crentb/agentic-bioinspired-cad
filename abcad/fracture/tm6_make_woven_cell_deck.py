"""
tm6_make_woven_cell_deck.py — non-fused woven CELL with frictional crossings (the full test seed).

Extends the working single crossover (tm6_contact_crossover.i) to a small NxN plain grid: N warp
fibers along x (bottom layer, z in [0,h]) and N weft fibers along y (top layer, z in [h,2h]),
each a SEPARATE body, with frictional contact at every warp-weft crossing (N*N pairs). Warp
fibers are gripped at both x-ends and pulled in tension; the weft fibers couple them laterally
through friction. This is the non-fused analog of the fused woven cube (TM-3 margin -0.108):
here a severed warp fiber can shed its load to neighbours THROUGH the frictional weft crossings
(graceful redundancy) instead of the load path simply dying.

Damage-tolerance protocol (mirrors TM-3): (1) intact tension -> E_eff; (2) "cut" one warp fiber
(free its grip / soften its block) -> E_eff_damaged; (3) retention = E_dmg/E_intact. Compare the
retention to the fused woven's 0.5mm value. PLA-magnitude isotropic material, mm/MPa units.

STATUS: the emitted NEWTON + superlu_dist + automatic_scaling + staged-loading settings (with the
weft y-pin below) converge the 2x2 and 3x3 cells; the measured retention is recorded in
results/woven_cell/RESULTS.md.

INPUTS   <N> <out.i> [cut] [preload]   (grid size, deck path, index of the cut warp fiber or -1,
         weft normal-press depth [mm]; see the lever comments in main())
OUTPUTS  the MOOSE deck at <out.i> + a one-line summary on stdout.
Usage: python -m abcad.fracture.tm6_make_woven_cell_deck <N> <out.i> [cut] [preload]
       (start with N=2 -> 4 crossings)
"""

from __future__ import annotations

import sys


def main(argv=None):
    """CLI entry point: write the NxN non-fused woven-cell contact deck."""
    argv = sys.argv[1:] if argv is None else list(argv)
    # Positional CLI: print the usage (this module's docstring) for -h/--help or missing arguments
    # rather than failing with an IndexError/ValueError traceback.
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    N = int(argv[0])
    out = argv[1]
    # Optional damage-tolerance levers (default to the original intact/free-weft behaviour):
    #   argv[2] cut     = index of the warp fiber to "cut" by FREEING its pulled (right) grip, so it carries
    #                     no applied tension but can still be dragged by friction through the weft crossings
    #                     (the chosen flaw-seed method; -1 = no cut). Fallback method if this proves too
    #                     weak a signal = sever the fiber's elements mid-span (delete-elements) — noted, not default.
    #   argv[3] preload = weft normal-press depth in mm. The frictional crossings only transmit load when the
    #                     warp/weft are pressed together (like the validated crossover deck's pressB). With
    #                     preload = 0 the weft floats with ~zero normal force -> friction ~0 -> a cut fiber
    #                     cannot shed load (retention pinned at the naive 1 - 1/N). preload > 0 presses each
    #                     weft down onto the warp so the sliding/redundancy mechanism actually engages.
    cut = int(argv[2]) if len(argv) > 2 else -1
    preload = float(argv[3]) if len(argv) > 3 else 0.0
    h = 2.0  # layer thickness (mm)
    w = 2.0  # fiber width (mm)
    sp = 5.0  # crossing spacing (mm)
    L = (N + 1) * sp  # fiber length
    E = 3500.0  # PLA Young's modulus [MPa]
    nu = 0.36  # PLA Poisson ratio

    # fiber centrelines: warp i at y=(i+1)*sp (runs full x); weft j at x=(j+1)*sp (runs full y)
    gens, prev, sub = [], "", 0
    mesh = ["[Mesh]"]
    for i in range(N):  # warp fibers (along x), bottom layer
        yc = (i + 1) * sp
        mesh += [
            f"  [warp{i}]",
            "    type = GeneratedMeshGenerator",
            "    dim = 3",
            "    xmin = 0",
            f"    xmax = {L}",
            f"    ymin = {yc-w/2}",
            f"    ymax = {yc+w/2}",
            "    zmin = 0",
            f"    zmax = {h}",
            "    nx = 12",
            "    ny = 2",
            "    nz = 2",
            f"    boundary_name_prefix = warp{i}",
            f"    boundary_id_offset = {sub*20}",  # unique sideset ids per body
            "  []",
            f"  [warp{i}_id]",
            "    type = SubdomainIDGenerator",
            f"    input = warp{i}",
            f"    subdomain_id = {sub+1}",
            "  []",
        ]
        prev = f"warp{i}_id"
        sub += 1
    for j in range(N):  # weft fibers (along y), top layer
        xc = (j + 1) * sp
        mesh += [
            f"  [weft{j}]",
            "    type = GeneratedMeshGenerator",
            "    dim = 3",
            f"    xmin = {xc-w/2}",
            f"    xmax = {xc+w/2}",
            "    ymin = 0",
            f"    ymax = {L}",
            f"    zmin = {h}",
            f"    zmax = {2*h}",
            "    nx = 2",
            "    ny = 12",
            "    nz = 2",
            f"    boundary_name_prefix = weft{j}",
            f"    boundary_id_offset = {sub*20}",
            "  []",
            f"  [weft{j}_id]",
            "    type = SubdomainIDGenerator",
            f"    input = weft{j}",
            f"    subdomain_id = {sub+1}",
            "  []",
        ]
        prev = f"weft{j}_id"
        sub += 1
    ids = [f"warp{i}_id" for i in range(N)] + [f"weft{j}_id" for j in range(N)]
    mesh += [
        "  [combined]",
        "    type = MeshCollectionGenerator",
        f"    inputs = '{' '.join(ids)}'",
        "  []",
    ]
    names = [f"warp{i}" for i in range(N)] + [f"weft{j}" for j in range(N)]
    mesh += [
        "  [rename]",
        "    type = RenameBlockGenerator",
        "    input = combined",
        f"    old_block = '{' '.join(str(k+1) for k in range(2*N))}'",
        f"    new_block = '{' '.join(names)}'",
        "  []",
        "[]",
    ]

    # contact: every warp-top (front) vs weft-bottom (back)
    contacts = ["[Contact]"]
    for i in range(N):
        for j in range(N):
            contacts += [
                f"  [c_{i}_{j}]",
                f"    primary = warp{i}_front",
                f"    secondary = weft{j}_back",
                "    model = coulomb",
                "    friction_coefficient = 0.3",
                "    formulation = penalty",
                "    penalty = 1e5",
                "    normalize_penalty = true",
                "  []",
            ]
    contacts.append("[]")

    # BCs: grip ALL warp left ends (fixed reference). Pull every warp's right end EXCEPT the cut fiber's,
    # which is freed -> it carries no applied tension but stays anchored at the left and can be dragged by
    # weft friction (the redundancy path). Optionally press the weft down to engage the frictional crossings.
    gripL = " ".join(f"warp{i}_left" for i in range(N))  # all warp left ends -> fixed anchor
    pulled = [i for i in range(N) if i != cut]  # warp fibers whose right end is gripped + pulled
    # pulled/measured surface (excludes the cut fiber)
    gripR = " ".join(f"warp{i}_right" for i in pulled)

    # Weft normal preload: press each weft's top face down by `preload` mm (ramped over the first step, then
    # held) so its underside bears on the warp -> normal contact force -> live friction. The z-Dirichlet also
    # removes the weft's z rigid-body mode; penalty friction grounds its in-plane motion to the warp once
    # engaged (the intact free-weft deck already converged, so a real preload only strengthens that coupling).
    weft_bc = ""
    if preload > 0:
        wtop = " ".join(f"weft{j}_front" for j in range(N))  # weft top faces (z = 2h) to press down
        # weft y-ends (ymin/ymax faces)
        wends = " ".join(f"weft{j}_bottom weft{j}_top" for j in range(N))
        # Pin the weft y-ends in y only: they are held along their length by the surrounding fabric. This
        # kills the weft's in-plane rigid-body mode (which aborts the NEWTON solve for the free-weft/cut
        # cases) WITHOUT constraining x (the load-transfer direction, grounded by penalty friction) or z
        # (driven by the press). Physically faithful and makes every cut/preload combination converge.
        weft_bc = (
            f"\n  [weft_press] type = FunctionDirichletBC variable = disp_z boundary = '{wtop}' "
            f"function = 'if(t<0.25, -{preload}*t/0.25, -{preload})' []"
            f"\n  [weft_piny] type = DirichletBC variable = disp_y boundary = '{wends}' value = 0 []"
        )

    # Pull ramps over t in [0.25, 1.0] to 0.02 mm, after the weft preload has seated.
    bcs = f"""[BCs]
  [fixL_x] type = DirichletBC variable = disp_x boundary = '{gripL}' value = 0 []
  [fixL_y] type = DirichletBC variable = disp_y boundary = '{gripL}' value = 0 []
  [fixL_z] type = DirichletBC variable = disp_z boundary = '{gripL}' value = 0 []
  [pull_x] type = FunctionDirichletBC variable = disp_x boundary = '{gripR}' function = '0.02*max(t-0.25,0)/0.75' []
  [pull_yz1] type = DirichletBC variable = disp_y boundary = '{gripR}' value = 0 []
  [pull_yz2] type = DirichletBC variable = disp_z boundary = '{gripR}' value = 0 []{weft_bc}
[]"""

    # The deck text below is emitted verbatim (column 0 is intentional: it is file content).
    deck = f"""# NON-FUSED WOVEN CELL — {N}x{N} plain grid, frictional crossings. Generated by
# tm6_make_woven_cell_deck.py. PLA (mm/MPa). Warp gripped + pulled; weft couples via friction.
[GlobalParams]
  displacements = 'disp_x disp_y disp_z'
[]

{chr(10).join(mesh)}

[Physics/SolidMechanics/QuasiStatic]
  [all]
    strain = SMALL
    add_variables = true
    generate_output = 'stress_xx'
  []
[]

{chr(10).join(contacts)}

{bcs}

[Materials]
  [elast]
    type = ComputeIsotropicElasticityTensor
    youngs_modulus = {E}
    poissons_ratio = {nu}
  []
  [stress]
    type = ComputeLinearElasticStress
  []
[]

[Postprocessors]
  [pull_force] type = SidesetReaction direction = '1 0 0' stress_tensor = stress boundary = '{gripR}' []
  [pull_disp]  type = SideAverageValue variable = disp_x boundary = '{gripR}' []
  [react_L]    type = SidesetReaction direction = '1 0 0' stress_tensor = stress boundary = '{gripL}' []
[]

[Executioner]
  # NEWTON + exact (superlu_dist) Jacobian + automatic_scaling is far more robust for penalty contact
  # than matrix-free PJFNK (which death-spiralled the timestep to ~1e-8 on the preloaded cell). dtmin
  # floors the step so a genuinely failed solve ABORTS instead of grinding forever. Loading is staged:
  # the weft preload seats over t in [0, 0.25]; the warp pull ramps over t in [0.25, 1.0].
  type = Transient
  solve_type = NEWTON
  automatic_scaling = true
  petsc_options_iname = '-pc_type -pc_factor_mat_solver_package'
  petsc_options_value = 'lu superlu_dist'
  line_search = basic
  nl_rel_tol = 1e-6
  nl_abs_tol = 1e-7
  l_max_its = 100
  nl_max_its = 40
  dt = 0.125
  dtmin = 0.02
  end_time = 1.0
[]

[Outputs]
  csv = true
  exodus = true   # mesh + disp/stress fields per step -> pyvista renders (deformed cell, load-shed, sliding)
[]
"""
    open(out, "w").write(deck)
    _cut = f"cut warp{cut} (grip freed)" if cut >= 0 else "intact"
    _pre = f"weft preload {preload} mm" if preload > 0 else "free weft (no preload)"
    print(
        f"wrote {out}: {N}x{N} non-fused woven cell, {N*N} frictional crossings, {2*N} fibers, {_cut}, {_pre}"
    )


if __name__ == "__main__":
    main()
