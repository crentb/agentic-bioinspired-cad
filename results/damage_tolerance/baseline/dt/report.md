# Damage tolerance — dt

Intact E_eff = **732.03 MPa** (voxel 1.25 mm, 12781 hex).
Flaw model: 3 replicates x 3 spherical flaws r=1.5 mm (mean dose 0.7% of member material).

| replicate | dose f | E_eff [MPa] | retention R | 1 - f |
|---|---|---|---|---|
| 0 | 0.008 | 729.735 | **0.997** | 0.992 |
| 1 | 0.006 | 724.933 | **0.990** | 0.994 |
| 2 | 0.007 | 723.336 | **0.988** | 0.993 |

**Score: min retention = 0.988, mean = 0.992.** R above (1 - f) means the architecture carries load around flaws (redundant/entangled paths).