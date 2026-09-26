# =====================================================================================
# NON-FUSED WOVEN — step 1: frictional fiber crossover (the sliding mechanism).
#
# The fused woven cube is load-path-sensitive (TM-3 margin -0.108): a severed fiber kills its
# load path because the voxel-weld makes fibers monolithic. Real entangled woven lattices are
# NON-fused — fibers SLIDE and entangle (frictional contact), redistributing load as damage
# grows. Only a contact model can capture that; this deck establishes the capability on the
# minimal unit: two crossing fibers (bars) pressed together, one dragged across the other.
# Friction transfers shear up to mu*N, then the fibers slide (vs a fused joint that transfers
# fully and then snaps). PLA-magnitude material, mm/MPa units. Penalty frictional contact
# (robust). This is the seed for a full non-fused-woven TM-3 (many crossings) — see docs/FRACTURE.md.
# =====================================================================================
[GlobalParams]
  displacements = 'disp_x disp_y disp_z'
[]

[Mesh]
  [fiberA]                          # bottom fiber, runs along x
    type = GeneratedMeshGenerator
    dim = 3
    xmin = 0
    xmax = 12
    ymin = 4
    ymax = 8
    zmin = 0
    zmax = 2
    nx = 12
    ny = 4
    nz = 2
    boundary_name_prefix = fiberA
  []
  [fiberA_id]
    type = SubdomainIDGenerator
    input = fiberA
    subdomain_id = 1
  []
  [fiberB]                          # top fiber, runs along y, crossing A (touches at z=2)
    type = GeneratedMeshGenerator
    dim = 3
    xmin = 4
    xmax = 8
    ymin = 0
    ymax = 12
    zmin = 2
    zmax = 4
    nx = 4
    ny = 12
    nz = 2
    boundary_name_prefix = fiberB
    boundary_id_offset = 100
  []
  [fiberB_id]
    type = SubdomainIDGenerator
    input = fiberB
    subdomain_id = 2
  []
  [combined]
    type = MeshCollectionGenerator
    inputs = 'fiberA_id fiberB_id'
  []
  [rename]
    type = RenameBlockGenerator
    input = combined
    old_block = '1 2'
    new_block = 'fiberA fiberB'
  []
[]

[Physics/SolidMechanics/QuasiStatic]
  [all]
    strain = SMALL
    add_variables = true
    generate_output = 'stress_zz'
  []
[]

[Contact]
  [crossover]
    primary = fiberA_front          # A's top face (z=2)
    secondary = fiberB_back         # B's bottom face (z=2)
    model = coulomb
    friction_coefficient = 0.3
    formulation = penalty
    penalty = 1e5
    normalize_penalty = true
  []
[]

[BCs]
  [anchorA]                         # fiber A anchored at both ends (all DOF)
    type = DirichletBC
    variable = disp_x
    boundary = 'fiberA_left fiberA_right'
    value = 0
  []
  [anchorA_y]
    type = DirichletBC
    variable = disp_y
    boundary = 'fiberA_left fiberA_right'
    value = 0
  []
  [anchorA_z]
    type = DirichletBC
    variable = disp_z
    boundary = 'fiberA_left fiberA_right'
    value = 0
  []
  [pressB]                          # press B down onto A -> normal contact force
    type = FunctionDirichletBC
    variable = disp_z
    boundary = fiberB_front
    function = 'if(t<1, -0.05*t, -0.05)'
  []
  [dragB]                           # then drag B across A (along x) -> friction transfers to A, then slides
    type = FunctionDirichletBC
    variable = disp_x
    boundary = fiberB_front
    function = 'if(t<1, 0, 0.4*(t-1))'
  []
  [holdB_y]
    type = DirichletBC
    variable = disp_y
    boundary = fiberB_front
    value = 0
  []
[]

[Materials]
  [elast]
    type = ComputeIsotropicElasticityTensor
    youngs_modulus = 3500           # MPa (PLA)
    poissons_ratio = 0.36
    block = 'fiberA fiberB'
  []
  [stress]
    type = ComputeLinearElasticStress
    block = 'fiberA fiberB'
  []
[]

[Postprocessors]
  [dragforce]                       # reaction on the dragged face = shear carried through the crossing
    type = SidesetReaction
    direction = '1 0 0'
    stress_tensor = stress
    boundary = fiberB_front
  []
  [dragdisp]
    type = SideAverageValue
    variable = disp_x
    boundary = fiberB_front
  []
[]

[Executioner]
  type = Transient
  solve_type = PJFNK
  petsc_options_iname = '-pc_type -pc_factor_mat_solver_package'
  petsc_options_value = 'lu superlu_dist'
  line_search = basic
  nl_rel_tol = 1e-6
  nl_abs_tol = 1e-7
  l_max_its = 50
  nl_max_its = 30
  dt = 0.1
  end_time = 2.0
[]

[Outputs]
  csv = true
[]
