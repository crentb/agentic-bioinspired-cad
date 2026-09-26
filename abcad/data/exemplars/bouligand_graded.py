# Base script: graded-pitch Bouligand — inter-ply angle ramps with height.
# Biological inspiration: mantis-shrimp dactyl club, where the pitch angle increases from the impact surface
#   inward; small angle near the loading face resists shear-driven delamination, larger angle inside resists
#   matrix splitting. See docs/LITERATURE.md.
# Single material: stacked rotated thin plates; rotating interfaces are the weak planes (crack twisting).
# Parameters: replace {num_plies} (10-40), {delta_min} (2-6 deg, bottom), {delta_max} (10-24 deg, top).
import bpy
import math

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

num_plies = {num_plies}          # total plies
delta_min = {delta_min}          # deg inter-ply increment at the base (impact face)
delta_max = {delta_max}          # deg inter-ply increment at the top (interior)

final_height = 2.0
plate_size = 2.0
ply_thickness = final_height / num_plies

theta = 0.0                      # cumulative orientation [deg]
for i in range(num_plies):
    z = i * ply_thickness
    bpy.ops.mesh.primitive_cube_add(size=plate_size, location=(0, 0, z))
    plate = bpy.context.object
    plate.scale[2] = ply_thickness / 2
    bpy.context.view_layer.objects.active = plate
    plate.select_set(True)
    bpy.ops.transform.rotate(value=math.radians(theta), orient_axis='Z')
    # Increment grows linearly from delta_min (base) to delta_max (top).
    frac = i / (num_plies - 1) if num_plies > 1 else 0.0
    theta += delta_min + (delta_max - delta_min) * frac
