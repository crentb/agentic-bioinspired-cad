# =====================================================================================
# TM-6 3D proof-of-capability — a genuine 3D phase-field crack (dim = 3).
#
# Same physics as the 2D Stage D, but a real 3D block: the crack is a SURFACE, not a line.
# Kept small/coarse (30x30x15 hex ~ 50k DOF) for the 16 GB memory budget (memory safety first).
# Seeded mid-height crack across the full thickness; anisotropic material; mode-I pull. This
# exists to demonstrate the pipeline runs 3D fracture; a full coupon at crack-resolving
# resolution is far heavier (see docs/FRACTURE.md).
#   combined-opt -i tm6_stageD_3d.i
# =====================================================================================
[Mesh]
  [gen]
    type = GeneratedMeshGenerator
    dim = 3
    nx = 30
    ny = 30
    nz = 15
    xmax = 1
    ymax = 1
    zmax = 0.5
  []
[]

[GlobalParams]
  displacements = 'disp_x disp_y disp_z'
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
    save_in = 'resid_x resid_y resid_z'
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
  [ic]                              # smooth mid-height crack (y=0.5) for x<0.5, across full thickness z
    type = ParsedFunction
    expression = 'exp(-abs(y-0.5)/0.05) * if(x<0.5, 1.0, exp(-(x-0.5)/0.05))'
  []
[]

[AuxVariables]
  [resid_x][]
  [resid_y][]
  [resid_z][]
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
  [solid_z]                         # the 3rd component — this is what makes it 3D
    type = PhaseFieldFractureMechanicsOffDiag
    variable = disp_z
    component = 2
    c = c
  []
[]

[BCs]
  [ydisp]
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
  [zfix]                            # pin z on one face to remove rigid z-translation
    type = DirichletBC
    variable = disp_z
    boundary = back
    value = 0
  []
[]

[Materials]
  [pfbulkmat]
    type = GenericConstantMaterial
    prop_names = 'gc_prop l visco'
    prop_values = '1e-3 0.05 1e-4'
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
    euler_angle_1 = 30
    euler_angle_2 = 0
    euler_angle_3 = 0
  []
  [damage_stress]
    type = ComputeLinearElasticPFFractureStress
    c = c
    E_name = 'elastic_energy'
    D_name = 'degradation'
    F_name = 'local_fracture_energy'
    decomposition_type = stress_spectral
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
  solve_type = NEWTON
  petsc_options_iname = '-pc_type -pc_factor_mat_solver_package -snes_type'
  petsc_options_value = 'lu superlu_dist vinewtonrsls'
  nl_rel_tol = 1e-6
  nl_abs_tol = 1e-8
  l_max_its = 40
  nl_max_its = 15
  dtmin = 1e-8
  end_time = 0.006
  [TimeStepper]
    type = IterationAdaptiveDT
    dt = 5e-5
    optimal_iterations = 8
    growth_factor = 1.4
    cutback_factor = 0.5
  []
[]

[Outputs]
  exodus = true
[]
