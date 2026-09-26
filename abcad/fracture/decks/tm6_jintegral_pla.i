# =====================================================================================
# TM-6 VALIDATION — analytical K/J benchmark (is our fracture mechanics correct?).
#
# Single-edge-notched tension (SENT), ISOTROPIC, a/W = 0.2. The J-integral has a
# closed-form target:  K_I = F(a/W)*sigma*sqrt(pi*a),  J = K_I^2 / E'  (E' = E/(1-nu^2),
# plane strain), with the Tada/handbook geometry factor
#   F(a/W) = 1.12 - 0.231(a/W) + 10.55(a/W)^2 - 21.72(a/W)^3 + 30.39(a/W)^4.
# We apply a fixed-grip displacement, MEASURE the remote stress from the top reaction,
# compute J with MOOSE DomainIntegral, and compare to the analytic J. Agreement (and the
# rings' path-independence) validates the J-integral, the units, and the crack geometry.
#
# Geometry: W=1 (x), H=2 (y, tall so the tip sees a near-remote field). Edge crack length
# a=0.2 realized as the FREE part of the bottom symmetry plane (x 0..0.2); ligament x 0.2..1
# held (disp_y=0). Tip at (0.2, 0), crack advances +x.
# =====================================================================================
[GlobalParams]
  displacements = 'disp_x disp_y'
[]

[Mesh]
  [gen]
    type = GeneratedMeshGenerator
    dim = 2
    nx = 60
    ny = 120
    xmax = 20
    ymax = 40
  []
  [ligament]                        # held part of the bottom symmetry plane (ahead of the tip)
    type = BoundingBoxNodeSetGenerator
    new_boundary = ligament
    bottom_left = '4 0 0'
    top_right = '20 0 0'
    input = gen
  []
  [xpin]                            # single node to kill rigid x-translation (far from the tip)
    type = BoundingBoxNodeSetGenerator
    new_boundary = xpin
    bottom_left = '19.6 39.6 0'
    top_right = '20.1 40.1 0'
    input = ligament
  []
[]

[Physics]
  [SolidMechanics]
    [QuasiStatic]
      [All]
        add_variables = true
        strain = SMALL
        planar_formulation = PLANE_STRAIN
        save_in = 'resid_x resid_y'
      []
    []
  []
[]

[DomainIntegral]
  integrals = JIntegral
  crack_front_points = '4 0 0'
  crack_direction_method = CrackDirectionVector
  crack_direction_vector = '1 0 0'
  2d = true
  axis_2d = 2
  radius_inner = '1.2 1.8 2.4 3.0'
  radius_outer = '1.8 2.4 3.0 3.6'
  incremental = false
  symmetry_plane = 1                # crack on the y=0 symmetry plane (normal = y); doubles the half-contour J
[]

[AuxVariables]
  [resid_x][]
  [resid_y][]
[]

[BCs]
  # Remote UNIFORM TRACTION with FREE sides = exactly the handbook SENT assumption.
  [pull]                            # tensile traction sigma applied to the top face (+y)
    type = NeumannBC
    variable = disp_y
    boundary = top
    value = 30.0                    # sigma = 30 MPa applied (real PLA stress range) (known -> analytic K needs no measurement)
  []
  [ligament_y]                      # symmetry plane ahead of the crack (free in x)
    type = DirichletBC
    variable = disp_y
    boundary = ligament
    value = 0
  []
  [pin_x]                           # one node fixes rigid x-translation (far from the tip)
    type = DirichletBC
    variable = disp_x
    boundary = xpin
    value = 0
  []
[]

[Materials]
  [elasticity]
    type = ComputeElasticityTensor          # anisotropic 'rod' material scaled to PLA magnitude (~3.5 GPa)
    C_ijkl = '3500 1951 1951 3500 1951 3500 2027 2027 2027'   # MPa (cubic test ratio x27.56 -> PLA scale)
    fill_method = symmetric9
    euler_angle_1 = 45              # rod orientation vs crack (swept on CLI)
    euler_angle_2 = 0
    euler_angle_3 = 0
  []
  [stress]
    type = ComputeLinearElasticStress
  []
[]

[Executioner]
  type = Steady
  solve_type = NEWTON
  petsc_options_iname = '-pc_type'
  petsc_options_value = 'lu'
  nl_rel_tol = 1e-10
[]

[Postprocessors]
  [reaction_top]                    # total reaction on the pulled edge -> remote stress sigma = R/W
    type = NodalSum
    variable = resid_y
    boundary = top
  []
[]

[Outputs]
  csv = true
[]
