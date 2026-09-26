# Test fixtures for `abcad.agent`

## `woven_failing_emit.py`

The recorded Phase-1 output of the code emitter for the prompt "a woven cubic lattice
metamaterial", kept byte-for-byte as the loop's regression fixture (2,059 bytes, SHA-256
`0d8a1d54858c8ea92d6493f35b5a69f75ac9909441cd26be95972c995d22efc5`).

It encodes a 2 × 2 × 2 woven cubic lattice (40 mm cells, helix radius 4.8 mm, one revolution,
4 fibers per cube edge, 24 path segments, fiber radius 0.5 mm, a final join), but it creates mesh
cylinders and then drives them with curve-spline calls, so Blender stops with
`'Object' object has no attribute 'splines'`. The loop must repair it; the end-to-end regression
test (`abcad-agent --use-code tests/agent/fixtures/woven_failing_emit.py "a woven cubic lattice
metamaterial"`) measures how reliably it does. Because it is model output, it is excluded from
linting and formatting and must never be edited.

## `recorded_runs.json`

Condensed records of the recorded loop runs that the replay tests drive through the real runner
with scripted test doubles.
