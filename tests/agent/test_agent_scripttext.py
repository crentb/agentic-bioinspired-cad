"""
U-01: script extraction, normalization and digests (abcad.agent.scripttext).

These rules decide which code the emitter, the repairer and the refiner accept and fix the
digests the stall guards compare, so they are tested against exact strings.
"""

from __future__ import annotations

from abcad.agent.scripttext import extract_script, first_line, normalize_script, script_digest

FENCE = "```"


def test_extract_last_python_fence_wins():
    text = f"intro\n{FENCE}python\nimport bpy\na = 1\n{FENCE}\nmore\n{FENCE}python\n  import bpy\nb = 2  \n{FENCE}\n"
    assert extract_script(text) == "import bpy\nb = 2"


def test_extract_python_tag_may_be_followed_by_newlines():
    text = f"{FENCE}python\n\n\nimport bpy\nc = 3\n{FENCE}"
    assert extract_script(text) == "import bpy\nc = 3"


def test_extract_falls_back_to_last_import_bpy():
    assert extract_script("x\nimport bpy\na=1\nimport bpy\nb=2") == "import bpy\nb=2"


def test_extract_without_markers_returns_stripped_text():
    assert extract_script("no code") == "no code"
    assert extract_script("   \n  ") == ""


def test_untagged_or_other_tagged_fence_falls_through_to_rule_two():
    untagged = f"{FENCE}\nimport bpy\nx = 1\n{FENCE}"
    assert extract_script(untagged) == f"import bpy\nx = 1\n{FENCE}"
    other = f"{FENCE}py\nimport bpy\ny = 2\n{FENCE}"
    assert extract_script(other) == f"import bpy\ny = 2\n{FENCE}"


def test_normalize_empty_inputs():
    assert normalize_script(None) == "import bpy"
    assert normalize_script("") == "import bpy"


def test_normalize_prepends_import_bpy():
    assert normalize_script("x = 1") == "import bpy\nx = 1"


def test_normalize_removes_control_characters_and_carriage_returns():
    assert normalize_script("import bpy\r\nx=1\x07") == "import bpy\nx=1"
    # Tabs and line feeds are kept.
    assert normalize_script("import bpy\n\tx = 1") == "import bpy\n\tx = 1"


def test_normalize_removes_fences_without_restripping():
    text = f"{FENCE}python\nimport bpy\n{FENCE}"
    assert normalize_script(text) == "\nimport bpy\n"


def test_normalize_is_idempotent_on_the_regression_fixture(woven_fixture):
    raw = woven_fixture.read_text(encoding="utf-8")
    assert raw.startswith("import bpy")
    once = normalize_script(raw)
    assert normalize_script(once) == once
    assert once == raw.strip()


def test_script_digest_reference_value():
    assert script_digest("  import bpy \n") == "1c2386664860d5fd280f08283ae71ee2cbfb16c1"
    assert len(script_digest("anything")) == 40
    # Surrounding whitespace does not change the digest; inner changes do.
    assert script_digest("import bpy\nx=1\n") == script_digest("\nimport bpy\nx=1")
    assert script_digest("import bpy\nx=1") != script_digest("import bpy\nx=2")


def test_first_line():
    assert first_line("\n\n  first line  \nsecond") == "first line"
    assert first_line("x" * 300) == "x" * 160
    assert first_line("abcdef", limit=3) == "abc"
    assert first_line("") == "(no message)"
    assert first_line(None) == "(no message)"
    assert first_line("  \n\t\n") == "(no message)"
