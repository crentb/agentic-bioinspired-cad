import bpy
import math

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

cells, U, R, n_rev, n_fibers, seg, fiber_radius = 2, 40.0, 4.8, 1.0, 4, 24, 0.5   # U, R, fiber_radius in mm
E = [((0,0,0),(1,0,0)),((0,1,0),(1,1,0)),((0,0,1),(1,0,1)),((0,1,1),(1,1,1)),
     ((0,0,0),(0,1,0)),((1,0,0),(1,1,0)),((0,0,1),(0,1,1)),((1,0,1),(1,1,1)),
     ((0,0,0),(0,0,1)),((1,0,0),(1,0,1)),((0,1,0),(0,1,1)),((1,1,0),(1,1,1))]

fibers = []
for ci in range(cells):
    for cj in range(cells):
        for ck in range(cells):
            for s, e in E:
                A = ((ci+s[0])*U, (cj+s[1])*U, (ck+s[2])*U)
                B = ((ci+e[0])*U, (cj+e[1])*U, (ck+e[2])*U)
                p1, p2 = (1, 2) if A[0]!= B[0] else (0, 2) if A[1]!= B[1] else (0, 1)  # wind plane perp to beam
                for f in range(n_fibers):
                    bpy.ops.mesh.primitive_cylinder_add(radius=fiber_radius, depth=1, location=(A[0], A[1], A[2]))
                    cu = bpy.context.object
                    cu.splines.new('POLY').points.add(seg)
                    for k in range(seg+1):
                        t = k/seg
                        p = [A[0]+(B[0]-A[0])*t, A[1]+(B[1]-A[1])*t, A[2]+(B[2]-A[2])*t]  # point on beam axis
                        a = 2*math.pi*n_rev*t + 2*math.pi*f/n_fibers
                        p[p1] += R*math.cos(a); p[p2] += R*math.sin(a)                    # helical offset
                        cu.splines[k].points[k].co = (p[0], p[1], p[2], 1.0)
                    bpy.context.view_layer.objects.active = cu
                    bpy.ops.object.mode_set(mode='EDIT')
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.mesh.remove_doubles(threshold=0.2)
                    bpy.ops.mesh.dissolve_limited()
                    bpy.ops.object.mode_set(mode='OBJECT')
                    fibers.append(cu)

bpy.ops.object.select_all(action='DESELECT')
for o in fibers:
    o.select_set(True)
bpy.context.view_layer.objects.active = fibers[0]
bpy.ops.object.join()