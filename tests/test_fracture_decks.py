"""
test_fracture_decks.py — the MOOSE deck generators reproduce the shipped reference decks exactly.

The example decks in abcad/fracture/decks/ were emitted by the generators with fixed arguments, so
regenerating them must be byte-identical — a regression check that the pure-Python generators
(which only build text) still emit the validated physics. The two woven generators have no shipped
example; their decks are checked structurally (contact pairs, preload / cut levers, weak-interface
placement). Pure Python: no MOOSE needed.

Run:  python -m pytest tests/test_fracture_decks.py   (fast suite; standard library only)
"""

from __future__ import annotations

import pytest

from abcad import resources
from abcad.fracture import (
    tm6_make_3d_jintegral_deck,
    tm6_make_3d_twist_deck,
    tm6_make_bouligand_deck,
    tm6_make_woven_cell_deck,
    tm6_make_woven_fracture_deck,
)


@pytest.mark.parametrize(
    "module, args, example",
    [
        (tm6_make_3d_twist_deck, ["30", "6"], "tm6_3d_twist_example.i"),
        (tm6_make_bouligand_deck, ["30", "6"], "tm6_bouligand_d30_example.i"),
        (tm6_make_3d_jintegral_deck, ["30", "5"], "tm6_3d_jintegral_example.i"),
    ],
)
def test_generator_reproduces_shipped_example(module, args, example, tmp_path, capsys):
    out = tmp_path / example
    module.main([*args, str(out)])
    assert out.read_bytes() == resources.deck_path(example).read_bytes(), f"{example} drifted"
    assert f"wrote {out}" in capsys.readouterr().out  # the one-line summary is still printed


def test_woven_cell_deck_levers(tmp_path):
    # 3x3 cell, warp 0 cut, 0.05 mm weft preload: 9 frictional pairs, cut fiber not pulled, press on.
    out = tmp_path / "wcell3.i"
    tm6_make_woven_cell_deck.main(["3", str(out), "0", "0.05"])
    deck = out.read_text()
    assert deck.count("model = coulomb") == 9, "one frictional contact pair per crossing"
    assert "warp0_right" not in deck.split("[pull_x]")[1].split("\n")[0], "cut fiber is not pulled"
    assert "[weft_press]" in deck and "[weft_piny]" in deck, "preload + y-pin emitted"
    # Intact, free-weft default: every warp pulled, no press.
    out2 = tmp_path / "wcell2.i"
    tm6_make_woven_cell_deck.main(["2", str(out2)])
    deck2 = out2.read_text()
    assert deck2.count("model = coulomb") == 4 and "[weft_press]" not in deck2


def test_woven_fracture_deck_modes(tmp_path):
    fused = tmp_path / "fused.i"
    tm6_make_woven_fracture_deck.main(["fused", str(fused)])
    assert "expression = '0.001'" in fused.read_text(), "fused = uniform Gc"
    nonfused = tmp_path / "nonfused.i"
    tm6_make_woven_fracture_deck.main(["nonfused", str(nonfused), "4", "2e-3", "0.2"])
    text = nonfused.read_text()
    # 4 weak interfaces at 0.5 ± 0.15 and 0.5 ± 0.30, never on the crack line y = 0.5
    assert "Interfaces (y): [0.2, 0.35, 0.65, 0.8]" in text
    assert text.count("exp(-((y-") == 4
    with pytest.raises(SystemExit):
        tm6_make_woven_fracture_deck.main(["bogus", str(tmp_path / "x.i")])
