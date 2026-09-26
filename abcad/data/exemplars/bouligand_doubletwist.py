# Base script: double-twist Bouligand — two interleaved helicoids.
# Biological inspiration: coelacanth scale double-helicoid; the literature's highest-toughness Bouligand variant.
# Single material: stacked rotated thin plates; the rotating ply interfaces are the weak planes that force
#   helicoidal crack twisting (no material contrast needed). See docs/LITERATURE.md.
# Parameters: replace {num_plies} (8-48), {delta_a} (5-15 deg), {delta_b} (3-10 deg). Even plies advance by
#   delta_a (helicoid A); odd plies by delta_b (helicoid B), offset 90 deg.
import bpy
import math

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

num_plies = {num_plies}          # total plies
delta_a = {delta_a}              # deg per step, helicoid A (even plies)
delta_b = {delta_b}              # deg per step, helicoid B (odd plies)
offset = 90.0                    # deg starting offset between the two interleaved helicoids

final_height = 2.0               # total stack height
plate_size = 2.0                 # square plate side
ply_thickness = final_height / num_plies

def theta(k):
    # Cumulative orientation of ply k: two interleaved constant-pitch helicoids.
    if k % 2 == 0:
        return (k // 2) * delta_a
    return (k // 2) * delta_b + offset

for i in range(num_plies):
    z = i * ply_thickness
    bpy.ops.mesh.primitive_cube_add(size=plate_size, location=(0, 0, z))
    plate = bpy.context.object
    plate.scale[2] = ply_thickness / 2          # thin plate
    bpy.context.view_layer.objects.active = plate
    plate.select_set(True)
    bpy.ops.transform.rotate(value=math.radians(theta(i)), orient_axis='Z')
