# Damage tolerance — dt_inplane

Intact E_eff = **492.84 MPa** (voxel 0.5 mm, 133788 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 0.3% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.003 | 492.492 | **0.999** | 0.997 |
| 1 | 0.003 | 487.259 | **0.989** | 0.997 |
| 2 | 0.002 | 492.292 | **0.999** | 0.998 |

**Score: min retention = 0.989, mean = 0.996.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).