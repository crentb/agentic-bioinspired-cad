# Damage tolerance — dt_inplane

Intact E_eff = **896.93 MPa** (voxel 1.25 mm, 9698 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 0.3% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.003 | 894.847 | **0.998** | 0.997 |
| 1 | 0.003 | 895.905 | **0.999** | 0.997 |
| 2 | 0.003 | 891.875 | **0.994** | 0.998 |

**Score: min retention = 0.994, mean = 0.997.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).