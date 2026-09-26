"""
abcad.reporting — human-readable summaries of the evidence records.

MODULES
    mission_control   one self-contained static HTML dashboard (no server, no external requests)
                      over the damage-tolerance ranking, fracture results, print certifications and
                      design-loop runs found under the output root.

INPUTS / OUTPUTS
    Reads JSON / CSV / PNG records under ``./out`` (or ABCAD_OUT) and writes the HTML there.
    Import-light: nothing is imported here.
"""
