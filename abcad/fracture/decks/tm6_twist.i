# SPDX-License-Identifier: LGPL-2.1-only
# Adapted from a MOOSE framework test input (https://github.com/idaholab/moose), so this deck stays
# under LGPL-2.1: full text in LICENSE-LGPL-2.1.txt beside it; see NOTICE.
# =====================================================================================
# TM-6 — FRACTURE RESPONSE vs ROD ORIENTATION (phase-field fracture).
#
# The instrument TM-3 (stiffness retention) cannot see a crack-path mechanism in
# decussation/Bouligand (2026-07-05 TM-3 sweep: twist-law and pitch made ~0 TM-3 difference;
# the proposed mechanism is crack-path work of fracture, not stiffness). THIS deck probes
# that mechanism directly: a single-edge-notched specimen of an ANISOTROPIC material whose
# rod/fiber axis is rotated by `euler_angle_1` relative to the crack plane. A phase-field
# crack must fight the material's directional stiffness/energy landscape; the WORK OF
# FRACTURE (area under the load-displacement curve, integrated to failure) depends on that
# angle. Sweeping euler_angle_1 = {0,15,30,45,60,75,90} maps the per-ply fracture response
# that a rotating-plywood (Bouligand/enamel) laminate would exploit: if intermediate angles
# were tougher, crack twisting through them would raise the effective R-curve (a hypothesis;
# see the result note below).
#
# Adapted from modules/combined/test/tests/phase_field_fracture/crack2d_aniso.i (validated
# MOOSE PFF test). Material = the test's cubic C_ijkl (relative comparison across angle is
# the result; a first-order model — see docs/FRACTURE.md, TM-6 note). Sweep the angle on the CLI:
#   combined-opt -i tm6_twist.i Materials/elasticity_tensor/euler_angle_1=45 \
#       Outputs/file_base=tm6_a45 Executioner/num_steps=160
# Requires: combined-opt (phase_field + solid_mechanics). Small 2D mesh; runs to failure in
# ~O(100) steps. VALIDATION GATE (validate_uniaxial.i) must pass first (QMS-002).
#
# RESULT NOTE (archived sweep, results/fracture/orientation_sweep/): with the ramp as configured,
# every run stops a few percent past peak load, before the crack propagates, so the work ratio
# between angles reflects initial stiffness rather than propagation work. Extend the ramp (end
# time) to measure propagation work; initiation toughness is measured by tm6_jintegral.i.
# =====================================================================================
[Mesh]
  [gen]
    type = GeneratedMeshGenerator
    dim = 2
    nx = 40
    ny = 20
    ymax = 0.5
  []
  [noncrack]                        # holds the un-cracked half of the bottom edge -> a left notch
    type = BoundingBoxNodeSetGenerator
    new_boundary = noncrack
    bottom_left = '0.5 0 0'
    top_right = '1 0 0'
    input = gen
  []
[]

[GlobalParams]
  displacements = 'disp_x disp_y'
[]

[Physics]
  [SolidMechanics]
    [QuasiStatic]
      [All]
        add_variables = true
        strain = SMALL
        additional_generate_output = 'strain_yy stress_yy'
        planar_formulation = PLANE_STRAIN
        save_in = 'resid_x resid_y'   # nodal residuals -> reaction force (load-displacement)
      []
    []
  []
[]

[Modules]
  [PhaseField]
    [Nonconserved]
      [c]
        free_energy = F
        kappa = kappa_op
        mobility = L
      []
    []
  []
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
  [off_disp]
    type = AllenCahnElasticEnergyOffDiag
    variable = c
    displacements = 'disp_x disp_y'
    mob_name = L
  []
[]

[AuxVariables]
  [resid_x]
  []
  [resid_y]                         # accumulated nodal reaction in y; summed on 'top' = load
  []
[]

[BCs]
  [ydisp]                           # displacement-controlled pull of the top edge
    type = FunctionDirichletBC
    variable = disp_y
    boundary = top
    function = t
  []
  [yfix]
    type = DirichletBC
    variable = disp_y
    boundary = noncrack
    value = 0
  []
  [xfix]
    type = DirichletBC
    variable = disp_x
    boundary = right
    value = 0
  []
[]

[Materials]
  [pfbulkmat]
    type = GenericConstantMaterial
    prop_names = 'gc_prop l visco'
    prop_values = '1e-3 0.05 1e-6'   # fracture toughness Gc, length scale l, viscosity
  []
  [elasticity_tensor]
    type = ComputeElasticityTensor
    C_ijkl = '127.0 70.8 70.8 127.0 70.8 127.0 73.55 73.55 73.55'
    fill_method = symmetric9
    euler_angle_1 = 30               # THE LEVER: rod/fiber orientation vs crack plane [deg]
    euler_angle_2 = 0
    euler_angle_3 = 0
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
  [damage_stress]
    type = ComputeLinearElasticPFFractureStress
    c = c
    E_name = 'elastic_energy'
    D_name = 'degradation'
    F_name = 'local_fracture_energy'
    decomposition_type = stress_spectral
    use_current_history_variable = true
  []
  [degradation]
    type = DerivativeParsedMaterial
    property_name = degradation
    coupled_variables = 'c'
    expression = '(1.0-c)^2*(1.0 - eta) + eta'
    constant_names       = 'eta'
    constant_expressions = '1.0e-6'
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
  [top_disp]                        # applied displacement (== t)
    type = SideAverageValue
    variable = disp_y
    boundary = top
  []
  [reaction_y]                      # reaction force on the pulled edge; ∫ reaction d(disp) = work of fracture
    type = NodalSum
    variable = resid_y
    boundary = top
  []
  [av_stress_yy]
    type = ElementAverageValue
    variable = stress_yy
  []
  [crack_c]                         # mean damage: rises 0 -> ~1 as the crack sweeps through
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

[Executioner]
  type = Transient
  solve_type = PJFNK
  petsc_options_iname = '-pc_type -pc_factor_mat_solving_package'
  petsc_options_value = 'lu superlu_dist'
  nl_rel_tol = 1e-8
  l_tol = 1e-4
  l_max_its = 100
  nl_max_its = 10
  dt = 5e-5
  num_steps = 160                   # to failure; override on CLI once calibrated
[]

[Outputs]
  csv = true
  exodus = false
[]
