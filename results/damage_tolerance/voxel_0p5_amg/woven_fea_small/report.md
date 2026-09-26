# Damage tolerance — woven_fea_small

Intact E_eff = **47.69 MPa** (voxel 0.5 mm, 63334 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 0.7% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.008 | 45.154 | **0.947** | 0.992 |
| 1 | 0.006 | 46.552 | **0.976** | 0.994 |
| 2 | 0.007 | 46.015 | **0.965** | 0.993 |

**Score: min retention = 0.947, mean = 0.963.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).