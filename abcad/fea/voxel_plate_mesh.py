"""
abcad/fea/voxel_plate_mesh.py — STL -> plated voxel-hex mesh for uniaxial FEA.

PURPOSE
    Bridge a watertight single-material lattice STL (our woven/helicoidal generators' output) into a
    finite-element mesh WITH LOADING PLATES, ready for uniaxial tension/compression in SfePy. It mirrors
    the voxel-hex route of the author's biomimetic-lattice-pipeline package (``biomimetic_pipeline``).
    Blender-free; runs in `cad_env`.

WHY VOXEL-HEX (not tet-from-STL)
    Woven lattices are dense with near-tangent fiber crossings. Tetrahedralizing such surfaces hits PLC
    self-intersections / 0-tet failures (the tet-meshing failure modes met in the biomimetic-lattice-pipeline
    project). An occupancy grid -> one 8-node hexahedron per solid voxel is watertight and single-component
    by construction and loads straight into SfePy. This is the canonical image-based micro-FE method.

WHY LOADING PLATES
    Solid top/bottom slabs that the members PENETRATE (their inner faces sit `overlap` inside the member
    z-extent) give (i) flat z-faces for the displacement/fixed boundary conditions and (ii) a single
    bonded load path so the specimen can carry BOTH compression and tension (the bonded grip a tensile
    test needs). Ported from biomimetic_pipeline.generators.digital_twin_sdf_runner._plate_occupancy.

PIPELINE
    watertight STL --voxelize (VTK image stencil)--> occupancy grid (bool, mm)
        --keep largest face-connected component--> drop voxelization speckle (FEA floaters)
        --add_plates--> plated occupancy + plate mask (grid grown in z to hold the slabs)
        --keep largest component again--> guarantee ONE connected solid spanning both plates
        --occupancy_to_hex_msh--> gmsh-2.2 hex .msh (mm coords, VTK/meshio hex node order)
    (optional) render_plated --> PNG (fibers tan + plates steel-blue)

INPUTS (CLI; all lengths in mm)
    --stl PATH      watertight input STL
    --voxel MM      voxel edge = FEA element size. Choose so the THINNEST member spans >= ~3-4 voxels
                    (a 2 mm-diameter fiber at 0.5 mm voxel = 4 voxels). Too coarse -> the network
                    fragments (reported); too fine -> element count (and solve time) explode.
    --plate MM      loading-plate thickness, each (top and bottom)
    --overlap MM    how far the plate inner face sits INSIDE the member z-extent (bond depth)
    --downsample N  integer block-mean coarsening of the FINAL grid (default 1 = off) to cap hex count
    --msh PATH      output gmsh-2.2 hex mesh (the FEA input)
    --png PATH      optional render of the plated specimen
    --no_render     skip the render

OUTPUTS
    - gmsh-2.2 hex .msh (mm coordinates; node order matches the hex kernels in
      biomimetic_pipeline.fea.fea_runner / abcad.fea.fea_runner_amg so its element-volume/centroid
      post-processing is correct).
    - a sidecar <msh>.json with the geometry needed to reduce an FEA reaction force to an effective
      modulus: nominal footprint area A0 [mm^2], specimen height H0 [mm], voxel size, element count.
    - optional PNG.
    Prints grid shape, solid fraction, element/plate counts, connectivity diagnostics, A0/H0.

UNITS
    mm throughout. SfePy reads MATERIAL_E in MPa and the displacement in mm, so stress comes out in MPa
    and reaction force in N (MPa * mm^2) — all consistent with a mesh whose coordinates are in mm.

SIDE EFFECTS
    Pure geometry; NO FEA here (see abcad/fea/run_tension.py). Needs numpy, scipy, pyvista+vtk,
    meshio — all present in `cad_env`. Imports nothing from ``abcad`` so it also runs standalone.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass

import numpy as np


# ==================================================================================================
# 1. Voxelize a watertight STL into a boolean occupancy grid (VTK image stencil)
# ==================================================================================================
def voxelize_stl(stl_path: str, voxel_mm: float):
    """Rasterize a CLOSED triangulated surface into a boolean occupancy grid.

    Uses VTK's polydata->image stencil (the standard "is this voxel inside the closed surface?" test),
    which is robust for the complex, multiply-connected woven topology as long as the STL is watertight
    (ours are — verified by build.py's watertight_report). Returns:
        occ    : bool ndarray indexed [x, y, z]  (True = solid material)
        origin : (ox, oy, oz) world coords [mm] of grid index (0,0,0)
        voxel_mm : echoed back for downstream use
    """
    import pyvista as pv
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy

    surf = pv.read(stl_path).triangulate()
    xmin, xmax, ymin, ymax, zmin, zmax = surf.bounds
    margin = 2.0 * voxel_mm  # one-cell empty border so boundary voxels are unambiguous
    # +1 because vtkImageData dimensions count POINTS (we treat each point as a voxel centre/cell).
    dims = [
        int(np.ceil((hi - lo + 2 * margin) / voxel_mm)) + 1
        for lo, hi in ((xmin, xmax), (ymin, ymax), (zmin, zmax))
    ]
    origin = (xmin - margin, ymin - margin, zmin - margin)

    # A "white" image (all 1) that the stencil will carve the OUTSIDE out of.
    white = vtk.vtkImageData()
    white.SetSpacing(voxel_mm, voxel_mm, voxel_mm)
    white.SetOrigin(*origin)
    white.SetDimensions(*dims)
    white.AllocateScalars(vtk.VTK_UNSIGNED_CHAR, 1)
    white.GetPointData().GetScalars().Fill(1)

    # Build the stencil from the surface, on the same image lattice.
    p2s = vtk.vtkPolyDataToImageStencil()
    p2s.SetInputData(surf)
    p2s.SetOutputOrigin(origin)
    p2s.SetOutputSpacing(voxel_mm, voxel_mm, voxel_mm)
    p2s.SetOutputWholeExtent(white.GetExtent())
    p2s.Update()

    cut = vtk.vtkImageStencil()
    cut.SetInputData(white)
    cut.SetStencilConnection(p2s.GetOutputPort())
    cut.ReverseStencilOff()  # keep what is INSIDE the surface
    cut.SetBackgroundValue(0)  # outside -> 0
    cut.Update()

    # VTK scalars are stored z-slowest -> reshape (nz, ny, nx) then transpose to [x, y, z].
    flat = vtk_to_numpy(cut.GetOutput().GetPointData().GetScalars())
    occ = (flat.reshape(dims[2], dims[1], dims[0]) > 0).transpose(2, 1, 0)
    return occ, origin, voxel_mm


# ==================================================================================================
# 2. Connectivity cleanup — drop voxel "speckle" / FEA floaters
# ==================================================================================================
def keep_largest_component(occ: np.ndarray, connectivity: int = 2) -> tuple:
    """Keep only the largest connected solid component (drops floaters that would be FEA mechanisms).

    `connectivity` selects the voxel adjacency that defines "connected":
      1 = faces only (6-neighbour) — strictest; thin voxelized helices fragment where the staircase
          steps diagonally (shares only an edge/corner there).
      2 = faces + edges (18-neighbour) — DEFAULT; keeps staircased/curved fibers together (an edge
          bond = 2 shared nodes) while still excluding pure single-corner (1-node) hinges.
      3 = faces + edges + corners (26-neighbour) — loosest; any touch counts (allows 1-node hinges).
    Woven fibers are curved bundles, so 18-connectivity is the robust default. Returns
    (cleaned_occ, kept_fraction).
    """
    from scipy import ndimage

    structure = ndimage.generate_binary_structure(3, connectivity)
    labels, n = ndimage.label(occ, structure=structure)
    if n <= 1:
        return occ, 1.0
    counts = np.bincount(labels.ravel())
    counts[0] = 0  # background label
    keep = int(counts.argmax())
    cleaned = labels == keep
    return cleaned, float(cleaned.sum()) / float(occ.sum())


# ==================================================================================================
# 3. Add top + bottom loading plates (port of biomimetic_pipeline _plate_occupancy, mm units)
# ==================================================================================================
def add_plates(
    rod_occ: np.ndarray, voxel_mm: float, plate_mm: float, overlap_mm: float, origin: tuple
) -> tuple:
    """Add solid top + bottom plate slabs to a member-only occupancy grid.

    The slabs span the full x,y footprint and extend the physical z-extent outward by
    (plate_mm - overlap_mm) at each end; their INNER faces sit `overlap_mm` *inside* the member
    z-extent so members penetrate and bond into a single load path (no tangent-contact ambiguity).
    The grid is grown in z to hold the slabs; the member region is unchanged. Returns
    (plated_occ, is_plate_mask, new_origin, meta).
    """
    t = max(int(round(plate_mm / voxel_mm)), 1)  # plate thickness [voxels]
    # bond depth [voxels]; clamped below t so a plate is never entirely inside the members
    o = min(max(int(round(overlap_mm / voxel_mm)), 0), t - 1)

    # np.asarray: numpy < 2.3 types a reduced .any() as scalar-or-array; the result here is always
    # a 1-D array over z, and the explicit array keeps len() and slicing well-typed.
    z_any = np.asarray(rod_occ.any(axis=(0, 1)))
    if not z_any.any():
        raise RuntimeError("occupancy grid is empty — nothing to plate")
    z_min = int(np.argmax(z_any))  # first occupied z-slice
    z_max = int(len(z_any) - 1 - np.argmax(z_any[::-1]))  # last occupied z-slice

    # Pad z to fit the slabs (member region untouched); track the world-origin shift.
    below = max(t - o - z_min, 0)
    above = max(t - o - (rod_occ.shape[2] - 1 - z_max), 0)
    plated = np.pad(rod_occ, ((0, 0), (0, 0), (below, above)))
    is_plate = np.zeros_like(plated)
    z_min2, z_max2 = z_min + below, z_max + below

    b_top = z_min2 + o + 1  # slice-exclusive upper bound
    b_bot = max(b_top - t, 0)
    is_plate[:, :, b_bot:b_top] = True  # bottom slab, full footprint

    t_bot = z_max2 - o
    t_top = min(t_bot + t, plated.shape[2])
    is_plate[:, :, t_bot:t_top] = True  # top slab, full footprint

    new_origin = (origin[0], origin[1], origin[2] - below * voxel_mm)
    meta = {
        "plate_thickness_mm": plate_mm,
        "plate_overlap_mm": overlap_mm,
        "plate_thickness_voxels": t,
        "plate_overlap_voxels": o,
        "grid_extra_below_voxels": int(below),
        "grid_extra_above_voxels": int(above),
    }
    return (plated | is_plate), is_plate, new_origin, meta


# ==================================================================================================
# 4. Occupancy grid -> gmsh-2.2 hexahedral mesh (one hex per solid voxel)
# ==================================================================================================
def occupancy_to_hex_msh(
    occ: np.ndarray, voxel_mm: float, origin: tuple, msh_path: str, downsample: int = 1
):
    """Emit one 8-node hexahedron per solid voxel as a gmsh-2.2 mesh (mm coords).

    Node order follows the VTK/meshio convention (bottom quad CCW from the local origin, then the top
    quad in the same order) so it matches the hex element-volume / centroid kernels in
    biomimetic_pipeline.fea.fea_runner. Unreferenced corner nodes (the void interior) are stripped.
    `downsample` (block-mean, majority-true) optionally coarsens the grid to cap the element count.
    Returns (n_hex, n_nodes, grid_shape).
    """
    import meshio

    ds = int(downsample)
    if ds > 1:
        # Pad each axis up to a multiple of ds, average ds^3 blocks, keep blocks that are >= half solid.
        pad = [(-n) % ds for n in occ.shape]
        occ_p = np.pad(occ, [(0, p) for p in pad])
        NX, NY, NZ = (s // ds for s in occ_p.shape)
        occ = occ_p.reshape(NX, ds, NY, ds, NZ, ds).mean(axis=(1, 3, 5)) >= 0.5
        voxel_mm = voxel_mm * ds

    NX, NY, NZ = occ.shape
    nNX, nNY, nNZ = NX + 1, NY + 1, NZ + 1  # corner-node counts per axis
    # Corner-node grid; flat index i + j*nNX + k*nNX*nNY so neighbour hexes share nodes.
    flat = np.arange(nNX * nNY * nNZ)
    points = (
        np.column_stack([flat % nNX, (flat // nNX) % nNY, flat // (nNX * nNY)]).astype(float)
        * voxel_mm
    )
    points += np.asarray(origin, dtype=float)  # shift into world mm coords

    solid = np.argwhere(occ)
    i, j, k = solid[:, 0], solid[:, 1], solid[:, 2]

    def nid(i, j, k):
        return i + j * nNX + k * nNX * nNY

    # fmt: off
    hexes = np.column_stack([
        nid(i,     j,     k),       nid(i + 1, j,     k),
        nid(i + 1, j + 1, k),       nid(i,     j + 1, k),
        nid(i,     j,     k + 1),   nid(i + 1, j,     k + 1),
        nid(i + 1, j + 1, k + 1),   nid(i,     j + 1, k + 1),
    ])
    # fmt: on

    # Strip corner nodes no hex references, and renumber the connectivity compactly.
    used = np.unique(hexes)
    remap = np.full(points.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    hexes = remap[hexes]
    points = points[used]

    os.makedirs(os.path.dirname(os.path.abspath(msh_path)), exist_ok=True)
    meshio.write(
        msh_path,
        meshio.Mesh(points=points, cells=[("hexahedron", hexes)]),
        file_format="gmsh22",
        binary=False,
    )
    return len(hexes), len(points), occ.shape


# ==================================================================================================
# 5. Render the plated specimen (fibers tan, plates steel-blue)
# ==================================================================================================
def render_plated(
    fiber_only: np.ndarray, is_plate: np.ndarray, voxel_mm: float, origin: tuple, png_path: str
) -> str:
    """Off-screen render: members in tan, loading plates in steel-blue, so the load frame is visible."""
    import pyvista as pv

    def boxes(mask):
        # One cell per voxel (dimensions count points, hence +1); keep only the flagged cells.
        g = pv.ImageData(
            dimensions=np.array(mask.shape) + 1, spacing=(voxel_mm,) * 3, origin=origin
        )
        g.cell_data["v"] = mask.flatten(order="F").astype(np.uint8)
        return g.threshold(0.5, scalars="v")

    pl = pv.Plotter(off_screen=True, window_size=(1000, 1100))
    pl.add_mesh(boxes(fiber_only), color="#c2b39a", smooth_shading=False)
    pl.add_mesh(boxes(is_plate), color="#4a6f8a", smooth_shading=False)
    pl.add_axes()
    pl.camera_position = "xz"
    os.makedirs(os.path.dirname(os.path.abspath(png_path)), exist_ok=True)
    pl.screenshot(png_path)
    pl.close()
    return png_path


# ==================================================================================================
# 6. End-to-end driver + CLI
# ==================================================================================================
@dataclass
class PlatedMesh:
    """Summary of one plated hex mesh written by build_plated_hex_mesh."""

    msh_path: str
    n_hex: int
    n_nodes: int
    footprint_area_mm2: float  # nominal A0 (member bounding box in x,y)
    height_mm: float  # specimen height H0 (plated z extent)
    grid_shape: tuple


def build_plated_hex_mesh(
    stl_path: str,
    voxel_mm: float,
    plate_mm: float,
    overlap_mm: float,
    msh_path: str,
    downsample: int = 1,
    conn: int = 2,
    png_path: str = "",
    verbose: bool = True,
) -> PlatedMesh:
    """STL -> voxelize -> plate -> keep largest connected body -> hex .msh (+ render). Writes <msh>.json."""

    def log(m):
        if verbose:
            print(m)

    # --- voxelize ---
    occ, origin, vmm = voxelize_stl(stl_path, voxel_mm)
    log(
        f"[voxelize] voxel={vmm}mm grid={occ.shape} solid={int(occ.sum()):,} ({occ.mean()*100:.2f}%)"
    )
    fib_bbox = np.argwhere(occ)
    # nominal footprint A0 = member bounding box in x,y (voxel counts are inclusive, hence +1) [mm^2]
    a0 = ((np.ptp(fib_bbox[:, 0]) + 1) * vmm) * ((np.ptp(fib_bbox[:, 1]) + 1) * vmm)

    # --- plate the FULL voxelization, THEN keep the largest connected body ---
    # The loading plates intersect the members `overlap_mm` BEFORE the members terminate, so fiber ends
    # are embedded in the slab (no free ends) and bond into the load path — this is the trick that made
    # the biomimetic_pipeline geometries meshable. We plate BEFORE pruning (pre-pruning the fibers alone
    # can discard most of an entangled woven network); keeping the largest component of the PLATED grid
    # then drops only voxels NOT bonded into the load path, while the solid plate slabs tie the surviving
    # members together. 18-connectivity (conn=2) keeps curved/staircased helices intact.
    plated, is_plate, origin2, pmeta = add_plates(occ, vmm, plate_mm, overlap_mm, origin)
    plated, frac2 = keep_largest_component(plated, connectivity=conn)
    is_plate = is_plate & plated  # plate mask within the kept body
    fiber_only = plated & ~is_plate
    # Valid load path: the kept body must include BOTH plate slabs (lower and upper halves of the grid).
    nz = plated.shape[2]
    spans = bool(is_plate[:, :, : nz // 2].any()) and bool(is_plate[:, :, nz // 2 :].any())
    log(
        f"[plate] overlap={overlap_mm}mm grid={plated.shape} height={nz*vmm:.1f}mm "
        f"fiber_vox={int(fiber_only.sum()):,} plate_vox={int(is_plate.sum()):,} "
        f"kept={frac2*100:.1f}% spans_both_plates={spans}"
    )
    if (not spans) or frac2 < 0.5:
        log(
            "[plate] WARNING: kept body misses a plate or drops >50% of solid — use a smaller --voxel, "
            "higher --connectivity, more --overlap, or a thicker-fiber specimen."
        )

    # --- mesh ---
    n_hex, n_nodes, gshape = occupancy_to_hex_msh(
        plated, vmm, origin2, msh_path, downsample=downsample
    )
    height = gshape[2] * (vmm * downsample)
    log(f"[mesh] wrote {msh_path}: {n_hex:,} hex, {n_nodes:,} nodes (downsample={downsample})")

    # --- sidecar geometry for force->modulus reduction ---
    sidecar = {
        "stl": os.path.abspath(stl_path),
        "voxel_mm": vmm,
        "downsample": downsample,
        "footprint_area_mm2": float(a0),
        "height_mm": float(height),
        "n_hex": int(n_hex),
        "n_nodes": int(n_nodes),
        "grid_shape": list(gshape),
        "spans_both_plates": spans,
        **pmeta,
    }
    with open(msh_path + ".json", "w") as fh:
        json.dump(sidecar, fh, indent=2)

    if png_path:
        render_plated(fiber_only, is_plate, vmm, origin2, png_path)
        log(f"[render] {png_path}")

    return PlatedMesh(msh_path, n_hex, n_nodes, float(a0), float(height), gshape)


def _parse(argv=None):
    """Parse the meshing CLI (all lengths in mm)."""
    p = argparse.ArgumentParser(description="STL -> plated voxel-hex mesh for SfePy uniaxial FEA.")
    p.add_argument("--stl", required=True)
    p.add_argument("--voxel", type=float, default=0.6, help="voxel edge / element size [mm]")
    p.add_argument("--plate", type=float, default=2.0, help="loading-plate thickness each [mm]")
    p.add_argument("--overlap", type=float, default=0.8, help="plate-into-member bond depth [mm]")
    p.add_argument(
        "--downsample", type=int, default=1, help="block-mean coarsen the final grid (cap hex)"
    )
    p.add_argument(
        "--connectivity",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="connected-body adjacency: 1=faces, 2=+edges (default), 3=+corners",
    )
    p.add_argument("--msh", required=True, help="output gmsh-2.2 hex mesh")
    p.add_argument("--png", default="", help="optional render PNG")
    p.add_argument("--no_render", dest="render", action="store_false")
    return p.parse_args(argv)


def main(argv=None):
    """CLI entry point: mesh one STL and print the element count, A0 and H0."""
    a = _parse(argv)
    png = a.png or (os.path.splitext(a.msh)[0] + ".png" if a.render else "")
    r = build_plated_hex_mesh(
        a.stl,
        a.voxel,
        a.plate,
        a.overlap,
        a.msh,
        downsample=a.downsample,
        conn=a.connectivity,
        png_path=png,
    )
    print(
        f"[done] {r.n_hex:,} hex | footprint A0={r.footprint_area_mm2:.1f} mm^2 | H0={r.height_mm:.1f} mm"
    )


if __name__ == "__main__":
    main()
