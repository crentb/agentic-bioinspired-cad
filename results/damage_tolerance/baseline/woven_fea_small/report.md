# Damage tolerance — woven_fea_small

Intact E_eff = **82.70 MPa** (voxel 1.0 mm, 8262 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 1.2% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.013 | 76.274 | **0.922** | 0.988 |
| 1 | 0.012 | 73.302 | **0.886** | 0.988 |
| 2 | 0.010 | 72.844 | **0.881** | 0.990 |

**Score: min retention = 0.881, mean = 0.896.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).