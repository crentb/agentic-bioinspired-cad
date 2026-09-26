# Vendored: woven-lattice geometry engine

`makeunitcell_func1.py` in this directory is **vendored verbatim** — an unmodified copy of
third-party code. **It is not original to this project.**

| | |
|---|---|
| Source repository | https://github.com/mollyacarton/woven-lattice |
| Pinned commit | `8583837e712b01e161f93c0f360c3a2318d51191` |
| Author | Molly Carton (Portela Research Group, MIT), with Jiayi Wu |
| License | MIT — see [`LICENSE`](LICENSE) in this directory (shipped with the code it covers) |
| Paper | M. Carton, J. U. Surjadi, B. F. G. Aymon, C. M. Portela, "Design framework for programmable three-dimensional woven metamaterials", *Nat. Commun.* (2026), doi:10.1038/s41467-026-68298-3; preprint arXiv:2507.14130 |

## Why it is vendored

It is the validated geometry engine for woven lattices: it converts a parent beam lattice into
continuous woven fiber centerlines (topology graph → spherical-dual nodes → helical fiber bundles →
chiral-twist node connectors → stitched continuous fibers). Reusing it unchanged keeps the
generated geometry faithful to the published design framework, and pinning a commit keeps builds
reproducible. The upstream project is not published as an installable package, so it is carried
here rather than declared as a dependency.

## Where the adaptations live

**All adaptations live in [`abcad/generators/woven/build.py`](../../generators/woven/build.py)** —
nothing in this directory is edited. That module:

- imports the engine (installing a tiny matplotlib stub first, so only numpy + scipy are needed —
  matplotlib is used only by the engine's plotting helpers, which are never called);
- calls `wovenLattice(...)` and extracts each `Curve.path` (the N×3 fiber centerline);
- adds the fiber-clearance (interpenetration) check, optional linear grading of the bundle radius,
  single-material print scaling and a CLI;
- sweeps the centerlines into tubes either with a Blender curve + bevel sweep or, Blender-free, with
  the engine's own `save_piped_stl` numpy-stl mesher followed by a watertight report and a render.

## Dependencies of the vendored module

Top-level imports: `numpy`, `scipy.spatial`, `scipy.interpolate`, `matplotlib.pyplot` and the
standard library. `numpy-stl` (`from stl import mesh`) is imported lazily inside `save_piped_stl`,
which is used only by the Blender-free sweep stages.

## Updating

Re-clone the upstream repository, copy `makeunitcell_func1.py` and `LICENSE` here unmodified, update
the pinned commit above, and re-run the woven tests (`tests/test_woven_logic.py`). Never edit the
vendored file; put every change in `abcad/generators/woven/build.py`. This directory is excluded
from formatting and linting so its bytes stay identical to the audited upstream copy.
