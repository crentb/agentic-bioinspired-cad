"""
tm6_make_3d_jintegral_deck.py — RIGOROUS 3D J-integral on a rotating-plywood crack, PLA units.

The 2D J-integral gave one number per uniform orientation. This is the real 3D version: a
through-thickness edge crack in a block whose plies rotate through the thickness (z), so the
J-integral is evaluated ALONG the crack front (one value per depth) and varies as each depth's
plies point a different way. Elastic + sharp crack (the standard, rigorous way to get a J-
integral — the phase-field damage field is diffuse and not integrable this way).

Geometry (mm) = 3D extension of the validated 2D benchmark (tm6_benchmark_K.i, matched closed-form
K to 4.5%): the y=0 face is a SYMMETRY plane; the crack is its free part x<a; the ligament x>a is
held (disp_y=0); traction sigma on top drives mode I; the crack front is the line (a, 0, z). N ply
slabs through the thickness, slab k rotated k*pitch. MOOSE DomainIntegral (3D, crack_front_points,
symmetry_plane) reports J at each depth -> converted to K = sqrt(J*E') in MPa*sqrt(m).

Material = PLA magnitude (cubic 'rod' tensor scaled to ~3.5 GPa; MPa/mm/N units so J is in kJ/m^2).

INPUTS   <pitch_deg> <n_slabs> <out.i>   (pitch per ply [deg], number of ply slabs, deck path)
OUTPUTS  the MOOSE deck at <out.i> + a two-line summary on stdout. The shipped example
         abcad/fracture/decks/tm6_3d_jintegral_example.i is exactly `30 5`.
Usage: python -m abcad.fracture.tm6_make_3d_jintegral_deck <pitch_deg> <n_slabs> <out.i>
"""

from __future__ import annotations

import sys


def main(argv=None):
    """CLI entry point: write the 3D J-integral deck for the requested pitch and slab count."""
    argv = sys.argv[1:] if argv is None else list(argv)
    # Positional CLI: print the usage (this module's docstring) for -h/--help or missing arguments
    # rather than failing with an IndexError/ValueError traceback.
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    pitch = float(argv[0])
    N = int(argv[1])
    out = argv[2]

    W, H, T = 20.0, 40.0, 10.0  # mm: width, height (half-model), thickness (ply stack)
    a = 4.0  # crack length [mm], a/W = 0.2 (matches the validated benchmark)
    nx, ny, nz = 40, 50, max(10, 2 * N)  # at least 2 elements through each slab
    slab_t = T / N
    sigma = 30.0  # MPa applied

    # crack-front points: one per slab centre, interior (avoid the z-free-surfaces for J accuracy)
    fpts = []
    for k in range(N):
        z = (k + 0.5) * slab_t
        z = min(max(z, 0.8), T - 0.8)
        fpts.append((a, 0.0, round(z, 3)))
    fpts_str = "\n                        ".join(f"{x} {y} {z}" for x, y, z in fpts)

    # mesh: base + N z-slab subdomains + ligament + pin nodesets
    mesh = [
        "[Mesh]",
        "  [gen]",
        "    type = GeneratedMeshGenerator",
        "    dim = 3",
        f"    nx = {nx}",
        f"    ny = {ny}",
        f"    nz = {nz}",
        f"    xmax = {W}",
        f"    ymax = {H}",
        f"    zmax = {T}",
        "  []",
    ]
    prev = "gen"
    for k in range(N):
        z0, z1 = k * slab_t, (k + 1) * slab_t
        mesh += [
            f"  [slab{k}]",
            "    type = SubdomainBoundingBoxGenerator",
            f"    block_id = {k+1}",
            f"    bottom_left = '0 0 {z0}'",
            f"    top_right = '{W} {H} {z1}'",
            f"    input = {prev}",
            "  []",
        ]
        prev = f"slab{k}"
    mesh += [
        "  [ligament]",
        "    type = BoundingBoxNodeSetGenerator",
        "    new_boundary = ligament",
        f"    bottom_left = '{a} 0 0'",
        f"    top_right = '{W} 0 {T}'",
        f"    input = {prev}",
        "  []",
        "  [xpin]",
        "    type = BoundingBoxNodeSetGenerator",
        "    new_boundary = xpin",
        f"    bottom_left = '{W-0.4} {H-0.4} 0'",
        f"    top_right = '{W+0.1} {H+0.1} {T}'",
        "    input = ligament",
        "  []",
        "  [zpin]",
        "    type = BoundingBoxNodeSetGenerator",
        "    new_boundary = zpin",
        "    bottom_left = '0 0 0'",
        f"    top_right = '{W} {H} 0.01'",
        "    input = xpin",
        "  []",
        "[]",
    ]

    # one anisotropic elasticity tensor per slab, rotated by k*pitch about z
    mats = []
    for k in range(N):
        ang = round(k * pitch, 3)
        mats += [
            f"  [elast{k}]",
            "    type = ComputeElasticityTensor",
            "    C_ijkl = '3500 1951 1951 3500 1951 3500 2027 2027 2027'",  # PLA magnitude, MPa
            "    fill_method = symmetric9",
            f"    euler_angle_1 = {ang}",
            f"    block = {k+1}",
            "  []",
        ]

    # The deck text below is emitted verbatim (column 0 is intentional: it is file content).
    deck = f"""# =====================================================================================
# TM-6 3D J-INTEGRAL — rotating-plywood crack, pitch {pitch} deg/ply, {N} slabs, PLA units (mm/MPa).
# J evaluated along the through-thickness crack front; each depth's plies are rotated, so J(depth)
# is the real 3D result. Generated by tm6_make_3d_jintegral_deck.py.
# =====================================================================================
[GlobalParams]
  displacements = 'disp_x disp_y disp_z'
[]

{chr(10).join(mesh)}

[Physics/SolidMechanics/QuasiStatic]
  [all]
    add_variables = true
    strain = SMALL
    generate_output = 'stress_yy'
  []
[]

[DomainIntegral]
  integrals = JIntegral
  crack_front_points = '{fpts_str}'
  crack_direction_method = CrackDirectionVector
  crack_direction_vector = '1 0 0'
  radius_inner = '1.0 1.5 2.0'
  radius_outer = '1.5 2.0 2.5'
  incremental = false
  symmetry_plane = 1
[]

[BCs]
  [pull]
    type = NeumannBC
    variable = disp_y
    boundary = top
    value = {sigma}
  []
  [ligament_y]
    type = DirichletBC
    variable = disp_y
    boundary = ligament
    value = 0
  []
  [pin_x]
    type = DirichletBC
    variable = disp_x
    boundary = xpin
    value = 0
  []
  [pin_z]
    type = DirichletBC
    variable = disp_z
    boundary = zpin
    value = 0
  []
[]

[Materials]
{chr(10).join(mats)}
  [stress]
    type = ComputeLinearElasticStress
  []
[]

[Executioner]
  type = Steady
  solve_type = NEWTON
  petsc_options_iname = '-pc_type -pc_factor_mat_solver_package'
  petsc_options_value = 'lu superlu_dist'
  nl_rel_tol = 1e-8
[]

[Outputs]
  csv = true
[]
"""
    open(out, "w").write(deck)
    print(
        f"wrote {out}: 3D J-integral, {N} plies (0..{round((N-1)*pitch,1)} deg), "
        f"mesh {nx}x{ny}x{nz}={nx*ny*nz} hex"
    )
    print(f"  crack front points (depth z): {[p[2] for p in fpts]}")


if __name__ == "__main__":
    main()
