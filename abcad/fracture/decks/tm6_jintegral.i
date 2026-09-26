# =====================================================================================
# TM-6 J-INTEGRAL — rigorous crack driving force vs rod/crack orientation.
#
# Companion to tm6_twist.i (phase-field, which gives the crack PATH + work of fracture).
# This deck is ELASTIC (no damage) with a sharp edge notch, and computes the J-integral
# (energy release rate) around the notch tip via MOOSE's DomainIntegral — the standard
# fracture-mechanics driving force. Sweeping euler_angle_1 and reading J vs applied
# displacement gives the rigorous, absolute-units version of the toughness landscape:
# the crack initiates when J reaches the material's Gc, so the J-Δ curves per angle rank
# how the anisotropic architecture concentrates or shields crack driving force.
#
# Geometry matches tm6_twist: 1.0 x 0.5 SENT, notch = free left half of the bottom edge,
# tip at (0.5, 0, 0), crack grows +x. Sweep on the CLI:
#   combined-opt -i tm6_jintegral.i Materials/elasticity_tensor/euler_angle_1=45 \
#       Outputs/file_base=tm6j_a45
# =====================================================================================
[GlobalParams]
  displacements = 'disp_x disp_y'
[]

[Mesh]
  [gen]
    type = GeneratedMeshGenerator
    dim = 2
    nx = 40
    ny = 20
    ymax = 0.5
  []
  [noncrack]                        # held right half of the bottom edge; left half = crack face
    type = BoundingBoxNodeSetGenerator
    new_boundary = noncrack
    bottom_left = '0.5 0 0'
    top_right = '1 0 0'
    input = gen
  []
[]

[Physics]
  [SolidMechanics]
    [QuasiStatic]
      [All]
        add_variables = true
        strain = SMALL
        planar_formulation = PLANE_STRAIN
        additional_generate_output = 'stress_yy vonmises_stress'
      []
    []
  []
[]

[DomainIntegral]
  integrals = JIntegral
  crack_front_points = '0.5 0 0'    # the notch tip
  crack_direction_method = CrackDirectionVector
  crack_direction_vector = '1 0 0'  # crack advances in +x
  2d = true
  axis_2d = 2
  radius_inner = '0.06 0.09 0.12'   # J-integration rings around the tip (inside the domain)
  radius_outer = '0.09 0.12 0.15'
  incremental = false               # total small-strain material (ComputeLinearElasticStress)
  symmetry_plane = 1                # crack on the y=0 symmetry plane (validated 2026-07-05: without
[]                                  #   this the half-contour J is 2x low; relative angle trend unaffected)

[BCs]
  [ydisp]
    type = FunctionDirichletBC
    variable = disp_y
    boundary = top
    function = t                    # applied displacement = t
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
  [elasticity_tensor]
    type = ComputeElasticityTensor
    C_ijkl = '127.0 70.8 70.8 127.0 70.8 127.0 73.55 73.55 73.55'
    fill_method = symmetric9
    euler_angle_1 = 45              # THE LEVER (swept on CLI)
    euler_angle_2 = 0
    euler_angle_3 = 0
  []
  [stress]
    type = ComputeLinearElasticStress
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
  solve_type = NEWTON
  petsc_options_iname = '-pc_type'
  petsc_options_value = 'lu'
  nl_rel_tol = 1e-9
  dt = 1e-4
  num_steps = 40                    # ramp disp 0 -> 0.004 (covers the phase-field initiation range)
[]

[Postprocessors]
  [top_disp]
    type = SideAverageValue
    variable = disp_y
    boundary = top
  []
[]

[Outputs]
  csv = true
[]
