# Damage tolerance — enamel_sigmoid_x4

Intact E_eff = **1120.52 MPa** (voxel 0.5 mm, 61006 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 0.5% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.005 | 1104.439 | **0.986** | 0.995 |
| 1 | 0.004 | 1106.475 | **0.988** | 0.996 |
| 2 | 0.006 | 1103.803 | **0.985** | 0.994 |

**Score: min retention = 0.985, mean = 0.986.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).