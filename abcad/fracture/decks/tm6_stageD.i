# =====================================================================================
# TM-6 STAGE D — FULL model (no symmetry): crack FREE to deflect through the rods.
#
# The half-model (tm6_twist.i) forced the crack straight along the symmetry plane. Here the
# specimen is full and the notch is an INTERNAL seeded crack at mid-height, so the crack can
# curve/deflect wherever the material steers it. D1: a single anisotropic orientation
# (euler_angle_1, swept on CLI) — in an off-axis material a mode-I crack should KINK toward
# the weak plane instead of running straight. That deflection is the ingredient the
# rotating-plywood (enamel/Bouligand) laminate uses; D2 will vary the angle with position so
# the crack is forced to twist back and forth.
#
# Internal crack seeded via FunctionIC on the damage c; irreversibility enforced by the
# variational-inequality bounded solver (vinewtonrsls) so the seeded crack persists and grows
# monotonically. Based on MOOSE's validated crack2d_vi_solver.i.
#   combined-opt -i tm6_stageD.i Materials/elasticity_tensor/euler_angle_1=30 Outputs/file_base=D_a30
# =====================================================================================
[Mesh]
  [gen]
    type = GeneratedMeshGenerator
    dim = 2
    nx = 60
    ny = 60
    xmax = 1
    ymax = 1
  []
[]

[GlobalParams]
  displacements = 'disp_x disp_y'
[]

[Modules/PhaseField/Nonconserved]
  [c]
    free_energy = F
    kappa = kappa_op
    mobility = L
  []
[]

[Physics/SolidMechanics/QuasiStatic]
  [mech]
    add_variables = true
    strain = SMALL
    additional_generate_output = 'stress_yy'
    save_in = 'resid_x resid_y'
    planar_formulation = PLANE_STRAIN
  []
[]

[ICs]
  [c_ic]
    type = FunctionIC
    function = ic
    variable = c
  []
[]

[Functions]
  [ic]                              # SMOOTH seeded notch (phase-field needs the crack smeared over l,
                                    # not a sharp step): exp(-|y-0.5|/l) along the crack line for x<0.5,
                                    # tapering past the tip at x=0.5. Sharp steps stall the c-solve.
    type = ParsedFunction
    expression = 'exp(-abs(y-0.5)/0.04) * if(x<0.5, 1.0, exp(-(x-0.5)/0.04))'
  []
[]

[AuxVariables]
  [resid_x][]
  [resid_y][]
  [bounds_dummy] order = FIRST family = LAGRANGE []
[]

[Kernels]
  [solid_x]
    type = PhaseFieldFractureMechanicsOffDiag
    variable = disp_x
    component = 0
    c = c
  []
  [solid_y]
    type = PhaseFieldFractureMechanicsOffDiag
    variable = disp_y
    component = 1
    c = c
  []
[]

[BCs]
  [ydisp]                           # mode I: pull the top up, clamp the bottom
    type = FunctionDirichletBC
    variable = disp_y
    boundary = top
    function = t
  []
  [yfix]
    type = DirichletBC
    variable = disp_y
    boundary = bottom
    value = 0
  []
  [xfix]
    type = DirichletBC
    variable = disp_x
    boundary = 'top bottom'
    value = 0
  []
[]

[Materials]
  [pfbulkmat]
    type = GenericConstantMaterial
    prop_names = 'gc_prop l visco'
    prop_values = '1e-3 0.04 1e-4'
  []
  [define_mobility]
    type = ParsedMaterial
    material_property_names = 'gc_prop visco'
    property_name = L
    expression = '1.0/(gc_prop * visco)'
  []
  [define_kappa]
    type = ParsedMaterial
    material_property_names = 'gc_prop l'
    property_name = kappa_op
    expression = 'gc_prop * l'
  []
  [elasticity_tensor]
    type = ComputeElasticityTensor
    C_ijkl = '127.0 70.8 70.8 127.0 70.8 127.0 73.55 73.55 73.55'
    fill_method = symmetric9
    euler_angle_1 = 30              # rod orientation (swept on CLI); off-axis -> crack should kink
    euler_angle_2 = 0
    euler_angle_3 = 0
  []
  [damage_stress]
    type = ComputeLinearElasticPFFractureStress
    c = c
    E_name = 'elastic_energy'
    D_name = 'degradation'
    F_name = 'local_fracture_energy'
    decomposition_type = stress_spectral   # required for anisotropic elasticity (not strain_spectral)
    use_snes_vi_solver = true
  []
  [degradation]
    type = DerivativeParsedMaterial
    property_name = degradation
    coupled_variables = 'c'
    expression = '(1.0-c)^2*(1.0 - eta) + eta'
    constant_names       = 'eta'
    constant_expressions = '0.0'
    derivative_order = 2
  []
  [local_fracture_energy]
    type = DerivativeParsedMaterial
    property_name = local_fracture_energy
    coupled_variables = 'c'
    material_property_names = 'gc_prop l'
    expression = 'c^2 * gc_prop / 2 / l'
    derivative_order = 2
  []
  [fracture_driving_energy]
    type = DerivativeSumMaterial
    coupled_variables = c
    sum_materials = 'elastic_energy local_fracture_energy'
    derivative_order = 2
    property_name = F
  []
[]

[Postprocessors]
  [top_disp]
    type = SideAverageValue
    variable = disp_y
    boundary = top
  []
  [reaction_y]
    type = NodalSum
    variable = resid_y
    boundary = top
  []
  [crack_c]
    type = ElementAverageValue
    variable = c
  []
[]

[Preconditioning]
  [smp]
    type = SMP
    full = true
  []
[]

[Bounds]
  [c_upper_bound]
    type = ConstantBounds
    variable = bounds_dummy
    bounded_variable = c
    bound_type = upper
    bound_value = 1.0
  []
  [c_lower_bound]
    type = VariableOldValueBounds
    variable = bounds_dummy
    bounded_variable = c
    bound_type = lower
  []
[]

[Executioner]
  type = Transient
  solve_type = NEWTON                # true Jacobian + direct solver = robust for the coupled PFF system
  petsc_options_iname = '-pc_type -pc_factor_mat_solver_package -snes_type'
  petsc_options_value = 'lu superlu_dist vinewtonrsls'
  nl_rel_tol = 1e-7
  nl_abs_tol = 1e-9
  l_max_its = 30
  nl_max_its = 15
  dtmin = 1e-8                       # allow adaptive cutback through the brittle snap-through
  end_time = 0.02
  [TimeStepper]
    type = IterationAdaptiveDT       # cut dt when a step struggles, grow it when easy
    dt = 5e-5
    optimal_iterations = 8
    growth_factor = 1.5
    cutback_factor = 0.5
  []
[]

[Outputs]
  exodus = true
  csv = true
[]
