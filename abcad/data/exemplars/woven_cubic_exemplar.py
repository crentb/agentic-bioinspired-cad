# Base script: woven cubic lattice — compact, self-contained, single-material.
# Each cube edge is rendered as a bundle of helical fibers winding around the beam axis; bundles meet at
# shared nodes to form one connected, printable solid. Geometry-only compliance (no material contrast).
# Simplified node model (see abcad/generators/woven/woven_simple.py); for paper-exact nodes use the Tier-1 engine.
import bpy
import math

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# --- parameters ---
cells = (2, 2, 2)       # tessellation
U = 40.0                # unit-cell side [mm]
reff_over_L = 0.12      # bundle radius / U
n_rev = 1.0             # helix revolutions per beam
n_fibers = 4            # fibers per beam (cubic connectivity)
pts_per_rev = 24
fiber_radius = 0.5      # swept-tube radius [mm]
R = reff_over_L * U

# --- tiny vector helpers ---
def sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def add(a, b): return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def scale(a, s): return (a[0]*s, a[1]*s, a[2]*s)
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def norm(a): return math.sqrt(a[0]**2+a[1]**2+a[2]**2)
def unit(a):
    n = norm(a); return (a[0]/n, a[1]/n, a[2]/n) if n > 1e-9 else (0.0, 0.0, 0.0)

# --- cubic lattice: nodes + edges, tessellated and de-duplicated ---
h = U/2.0
corners = [(-h,-h,-h),(h,-h,-h),(-h,h,-h),(-h,-h,h),(h,h,-h),(h,-h,h),(-h,h,h),(h,h,h)]
cube_edges = [(0,1),(0,2),(0,3),(1,4),(1,5),(2,4),(2,6),(3,5),(3,6),(4,7),(5,7),(6,7)]
nodes, idx = [], {}
def node_id(p):
    k = (round(p[0],4), round(p[1],4), round(p[2],4))
    if k not in idx:
        idx[k] = len(nodes); nodes.append(k)
    return idx[k]
edges = set()
for ci in range(cells[0]):
    for cj in range(cells[1]):
        for ck in range(cells[2]):
            c = (ci*U, cj*U, ck*U)
            g = [node_id(add(c, p)) for p in corners]
            for a, b in cube_edges:
                e = (g[a], g[b]); edges.add((min(e), max(e)))

# --- build a helical fiber bundle along each beam ---
def add_fiber(A, B, phase):
    axis = unit(sub(B, A))
    ref = (0.0,0.0,1.0) if abs(axis[2]) < 0.9 else (1.0,0.0,0.0)
    u = unit(cross(ref, axis)); v = cross(axis, u)
    N = max(8, int(pts_per_rev*max(n_rev,1.0))) + 1
    cu = bpy.data.curves.new("wf", 'CURVE'); cu.dimensions = '3D'
    sp = cu.splines.new('POLY'); sp.points.add(N-1)
    for s in range(N):
        t = s/(N-1)
        centre = add(A, scale(sub(B, A), t))
        ang = 2*math.pi*n_rev*t + phase
        off = add(scale(u, R*math.cos(ang)), scale(v, R*math.sin(ang)))
        p = add(centre, off)
        sp.points[s].co = (p[0], p[1], p[2], 1.0)
    cu.bevel_depth = fiber_radius; cu.bevel_resolution = 6
    o = bpy.data.objects.new("wf", cu); bpy.context.collection.objects.link(o)
    return o

objs = []
for i, j in edges:
    for f in range(n_fibers):
        objs.append(add_fiber(nodes[i], nodes[j], 2*math.pi*f/n_fibers))

# --- convert curves to mesh and join into one object ---
bpy.ops.object.select_all(action='DESELECT')
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.convert(target='MESH')
bpy.ops.object.select_all(action='DESELECT')
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.join()
