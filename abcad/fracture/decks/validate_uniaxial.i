# =====================================================================================
# TM-6 Stage A — MOOSE cross-code VALIDATION GATE (QMS-002: mandatory before any MOOSE
# number enters records). A solid block under uniaxial tension, in OUR unit system
# (mm, MPa, N), material E = 3000 MPa, nu = 0.40 — the same constants as the SfePy
# lineage. For a solid uniaxial bar the effective modulus is analytically E exactly:
#     E_eff = <stress_zz> / strain_zz  ==  E  (== 3000 MPa)
# Passing this proves MOOSE's elasticity, our units, and the BC setup all agree with
# analytics AND with the SfePy solid control (E_eff ~ E). Small, ~128 elements.
# Run:  conda run -n moose solid_mechanics-opt -i validate_uniaxial.i
# =====================================================================================

[GlobalParams]
  displacements = 'disp_x disp_y disp_z'
[]

[Mesh]
  type = GeneratedMesh
  dim = 3
  nx = 4
  ny = 4
  nz = 8
  xmax = 4      # mm
  ymax = 4      # mm
  zmax = 8      # mm  (gauge length H0 = 8 mm)
[]

# Small-strain linear elasticity; auto-creates disp_x/y/z and outputs stress/strain_zz.
[Physics/SolidMechanics/QuasiStatic]
  [all]
    strain = SMALL
    add_variables = true
    generate_output = 'stress_zz strain_zz'
  []
[]

[BCs]
  # Symmetry planes let the bar contract laterally (Poisson) -> a pure uniaxial stress state.
  [sym_x]                       # x = 0 face ('left')
    type = DirichletBC
    variable = disp_x
    boundary = left
    value = 0.0
  []
  [sym_y]                       # y = 0 face ('bottom')
    type = DirichletBC
    variable = disp_y
    boundary = bottom
    value = 0.0
  []
  [fix_z]                       # z = 0 face ('back') held
    type = DirichletBC
    variable = disp_z
    boundary = back
    value = 0.0
  []
  [pull_z]                      # z = H face ('front') pulled: disp = strain*H = 0.01*8 = 0.08 mm
    type = DirichletBC
    variable = disp_z
    boundary = front
    value = 0.08
  []
[]

[Materials]
  [elasticity]
    type = ComputeIsotropicElasticityTensor
    youngs_modulus = 3000     # MPa
    poissons_ratio = 0.40
  []
  [stress]
    type = ComputeLinearElasticStress
  []
[]

[Executioner]
  type = Steady
  solve_type = NEWTON
  petsc_options_iname = '-pc_type -pc_hypre_type'
  petsc_options_value = 'hypre boomeramg'
  nl_rel_tol = 1e-10
[]

[Postprocessors]
  # Uniform for a solid bar; E_eff = avg_stress_zz / avg_strain_zz must equal E = 3000 MPa.
  [avg_stress_zz]
    type = ElementAverageValue
    variable = stress_zz
  []
  [avg_strain_zz]
    type = ElementAverageValue
    variable = strain_zz
  []
[]

[Outputs]
  csv = true
[]
