"""
prompt_vocab.py — Vocabulary extension for the new structural families (helicoidal variants, woven).

Adds natural-language "shape phrases" for the woven and new helicoidal-variant base scripts so a
prompt-synthesis pipeline can produce diverse instructions that map to them (the base scripts ship in
abcad/data/exemplars/; locate them with ``abcad.resources.exemplars_dir()``).

SELF-CONTAINED ON PURPOSE: depends only on the stdlib ``random``, so it can be imported and tested
standalone and dispatched to from any existing prompt generator via a small guarded call (unknown ids
return None, leaving the caller's own vocabulary in charge).

INPUTS / OUTPUTS
    shape_phrase_x(base_id) -> str | None   (draws from the module-level ``random`` generator; seed it
                                             for reproducible phrases)
    NEW_BASE_IDS                            sorted list of every base_id handled here

Recognised base_ids:
  helical: bouligand_doubletwist, bouligand_graded, bouligand_exponential, bouligand_fibonacci, bouligand_herringbone
  woven:   woven_cubic, woven_bcc, woven_octahedron, woven_diamond, woven_graded
"""

from __future__ import annotations

import random

# --- helicoidal variant modifiers (combined with a helical core phrase) -------------------------------
HELICAL_CORE = [
    "a helical Bouligand bioinspired structure",
    "a helical twisted-ply bioinspired structure",
    "a Bouligand bioinspired material",
    "a helical rotating-plywood bioinspired structure",
]

HELICAL_VARIANT_MODIFIERS = {
    "bouligand_doubletwist": [
        "with two interleaved (double-twist) helicoids",
        "in a double-twist arrangement",
        "with a double helicoid of interleaved plies",
    ],
    "bouligand_graded": [
        "with a graded pitch angle increasing through the thickness",
        "with a pitch gradient, small angle at the surface and larger inside",
        "with functionally graded ply rotation",
    ],
    "bouligand_exponential": [
        "with an exponentially increasing rotation per ply",
        "with exponential pitch progression",
    ],
    "bouligand_fibonacci": [
        "with a Fibonacci rotation sequence",
        "with Fibonacci-progression ply angles",
    ],
    "bouligand_herringbone": [
        "with a herringbone (alternating twist sense) pattern",
        "in a chevron herringbone Bouligand arrangement",
    ],
}

# --- woven phrases ------------------------------------------------------------------------------------
WOVEN_CORE = [
    "a woven lattice metamaterial",
    "a woven metamaterial of entangled fibers",
    "a 3D woven lattice",
]

WOVEN_TOPOLOGY = {
    "woven_cubic": ["with a cubic unit cell", "on a cubic lattice"],
    "woven_bcc": ["with a body-centered-cubic unit cell", "on a BCC lattice"],
    "woven_octahedron": ["with an octahedral unit cell", "on an octahedron lattice"],
    "woven_diamond": ["with a diamond unit cell", "on a diamond lattice"],
    "woven_graded": ["with a functional stiffness gradient", "with graded effective strut radius"],
}


def shape_phrase_x(base_id: str):
    """Return a natural-language shape phrase for a new-family base_id, or None if not recognised."""
    if base_id in HELICAL_VARIANT_MODIFIERS:
        return f"{random.choice(HELICAL_CORE)} {random.choice(HELICAL_VARIANT_MODIFIERS[base_id])}"
    if base_id in WOVEN_TOPOLOGY:
        return f"{random.choice(WOVEN_CORE)} {random.choice(WOVEN_TOPOLOGY[base_id])}"
    if base_id == "woven" or base_id.startswith("woven_"):
        return random.choice(WOVEN_CORE)  # generic woven id without a known topology
    return None


# Convenience for callers/tests.
NEW_BASE_IDS = sorted(set(HELICAL_VARIANT_MODIFIERS) | set(WOVEN_TOPOLOGY))
