"""
U-08 / U-09: the Blender executor and the harness helpers (abcad.agent.blender, blender_harness).

The executor is driven by a fake process runner (canned transcripts, or a timeout); the harness
helpers implement the studio and statistics formulas and must import without Blender.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from agent_fakes import FakeProcessRunner

from abcad.agent import blender_harness as harness
from abcad.agent.blender import (
    HARNESS_PATH,
    BlenderExecutor,
    error_excerpt,
    parse_harness_output,
    run_in_process_group,
)

SPLINES = "'Object' object has no attribute 'splines'"


def success_transcript(stl_path):
    """A harness stdout of a successful execution."""
    return "\n".join(
        [
            "Blender 5.0.1 (hash abc) startup noise",
            "ABCAD_BLENDER: 5.0.1",
            "ABCAD_OBJECTS: 1",
            'MESH_STATS: {"bbox_mm": [90.6, 90.6, 90.6], "overhang_area_frac": 0.1357}',
            "Render saved at /somewhere/render_initial.png",
            f"STL_PATH: {stl_path}",
            "ABCAD_EXEC: OK",
            "Blender quit",
        ]
    )


def test_success_transcript(tmp_path, settings):
    stl = tmp_path / "geom_initial.stl"
    stl.write_bytes(b"solid")

    def make_render(argv, kwargs):
        run_dir = tmp_path / "run"
        (run_dir / "render_initial.png").write_bytes(b"png")

    runner = FakeProcessRunner(success_transcript(stl), "", 0, on_call=make_render)
    executor = BlenderExecutor(settings, process_runner=runner)
    report = executor.execute("import bpy", label="initial", run_dir=str(tmp_path / "run"))
    assert report.ok and report.status == "success" and report.error == ""
    assert report.mesh_stats == {"bbox_mm": [90.6, 90.6, 90.6], "overhang_area_frac": 0.1357}
    assert report.stl_path == str(stl)
    assert report.render_png == str(tmp_path / "run" / "render_initial.png")
    assert report.blender_version == "5.0.1" and executor.blender_version == "5.0.1"
    assert report.exit_code == 0 and not report.timed_out


def test_stl_path_to_missing_file_is_ignored(tmp_path):
    parsed = parse_harness_output(success_transcript(tmp_path / "absent.stl"), "")
    assert parsed.ok and parsed.stl_path is None


def test_malformed_mesh_stats_give_none_but_success():
    stdout = "MESH_STATS: {not json}\nABCAD_EXEC: OK\n"
    parsed = parse_harness_output(stdout, "")
    assert parsed.ok and parsed.mesh_stats is None


def test_first_mesh_stats_line_wins():
    stdout = 'MESH_STATS: {"a": 1}\nMESH_STATS: {"a": 2}\nABCAD_EXEC: OK\n'
    assert parse_harness_output(stdout, "").mesh_stats == {"a": 1}


def test_fail_marker_gives_the_exception_text(tmp_path, settings):
    stdout = f"ABCAD_BLENDER: 5.0.1\nABCAD_EXEC: FAIL {SPLINES}\nBlender quit\n"
    stderr = "Traceback (most recent call last):\n  ...\nAttributeError: ...\n"
    runner = FakeProcessRunner(stdout, stderr, 1)
    report = BlenderExecutor(settings, process_runner=runner).execute(
        "import bpy", label="initial", run_dir=str(tmp_path / "run")
    )
    assert not report.ok and report.status == "failed"
    assert report.error == SPLINES
    assert report.render_png is None and report.exit_code == 1


def test_error_excerpt_rules():
    multi = "ABCAD_EXEC: FAIL line one\nline two\nMESH_STATS: {}\nignored"
    assert error_excerpt(multi, "") == "line one\nline two"
    long_fail = "ABCAD_EXEC: FAIL start\n" + "\n".join(f"l{i}" for i in range(30))
    assert error_excerpt(long_fail, "").splitlines() == ["start"] + [f"l{i}" for i in range(14)]
    thirty = "\n".join(f"out {i}" for i in range(30))
    assert error_excerpt(thirty, "err") == "\n".join(f"out {i}" for i in range(10, 30))
    five = "\n".join(f"err {i}" for i in range(5))
    assert error_excerpt("", five) == five


def test_ok_marker_does_not_override_a_fail_marker():
    parsed = parse_harness_output("ABCAD_EXEC: OK\nABCAD_EXEC: FAIL late\n", "")
    assert not parsed.ok and parsed.fail_message == "late"


def test_timeout_becomes_a_failed_report(tmp_path, settings):
    runner = FakeProcessRunner("partial output\n", "partial err", timeout=True)
    report = BlenderExecutor(settings, process_runner=runner).execute(
        "import bpy", label="fix_run_1", run_dir=str(tmp_path / "run")
    )
    assert report.status == "failed" and report.timed_out and report.exit_code is None
    assert report.error == "Blender timed out after 300 s"
    log = (tmp_path / "run" / "fix_run_1_blender.log").read_text(encoding="utf-8")
    assert "partial output" in log and "partial err" in log


def test_missing_blender_becomes_a_failed_report(tmp_path, make_settings):
    settings = make_settings(blender_path=str(tmp_path / "no_blender"))
    report = BlenderExecutor(settings).execute("import bpy", label="initial", run_dir=str(tmp_path))
    assert report.status == "failed" and "could not start Blender" in report.error


@pytest.mark.parametrize("keep_temp", [False, True])
def test_command_job_file_and_files_written(tmp_path, make_settings, keep_temp):
    settings = make_settings(keep_temp=keep_temp)
    run_dir = tmp_path / "run"
    seen = {}

    def inspect(argv, kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        with open(argv[-1], encoding="utf-8") as handle:
            seen["job"] = json.load(handle)

    runner = FakeProcessRunner("ABCAD_EXEC: OK\n", "", 0, on_call=inspect)
    report = BlenderExecutor(settings, process_runner=runner).execute(
        "import bpy\nx = 1", label="fix_run_2", run_dir=str(run_dir)
    )
    job_path = os.path.join(settings.paths.tmp_dir, "fix_run_2_job.json")
    assert seen["argv"] == [sys.executable, "-b", "--python", HARNESS_PATH, "--", job_path]
    assert os.path.isabs(HARNESS_PATH) and HARNESS_PATH.endswith("blender_harness.py")
    assert seen["kwargs"]["timeout"] == 300.0
    assert seen["job"] == {
        "schema": "abcad.agent.blender-job/1",
        "label": "fix_run_2",
        "script_path": str(run_dir / "fix_run_2_generated.py"),
        "output_dir": str(run_dir),
        "render_filename": "render_fix_run_2.png",
        "stl_filename": "geom_fix_run_2.stl",
        "resolution": [1280, 720],
        "samples": 64,
    }
    assert (run_dir / "fix_run_2_generated.py").read_text(encoding="utf-8") == "import bpy\nx = 1"
    assert report.script_copy == str(run_dir / "fix_run_2_generated.py")
    assert (run_dir / "fix_run_2_blender.log").is_file()
    assert os.path.exists(job_path) is keep_temp


def test_process_group_runner_kills_on_timeout():
    """The default runner raises TimeoutExpired after killing the child's process group."""
    code = "import time; print('started', flush=True); time.sleep(30)"
    with pytest.raises(subprocess.TimeoutExpired) as info:
        run_in_process_group([sys.executable, "-c", code], timeout=2)
    output = info.value.output
    output = output.decode() if isinstance(output, bytes) else output
    assert "started" in (output or "")
    done = run_in_process_group([sys.executable, "-c", "print('ok')"], timeout=30)
    assert done.returncode == 0 and done.stdout.strip() == "ok"


# --------------------------------------------------------------------------------------------------
# U-09: harness helpers
# --------------------------------------------------------------------------------------------------
def test_harness_imports_without_bpy():
    assert "bpy" not in sys.modules and "mathutils" not in sys.modules
    assert callable(harness.main)


def test_bbox_diagonal():
    assert harness.bbox_diagonal((0, 0, 0), (0, 0, 0)) == 1.0
    assert harness.bbox_diagonal((0, 0, 0), (90.6, 90.6, 90.6)) == pytest.approx(156.924, abs=1e-3)


def test_camera_placement():
    location, clip = harness.camera_placement((0, 0, 0), 10)
    assert location == pytest.approx((11.717, -11.717, 7.030), abs=1e-3)
    assert clip == 1000
    location, clip = harness.camera_placement((0, 0, 0), 156.924)
    assert location == pytest.approx((183.868, -183.868, 110.321), abs=1e-3)
    # clip_end = max(1000, 12 * diag): 12 * 156.924 = 1883.088 exactly (the spec's 1883.09 is rounded)
    assert clip == pytest.approx(1883.088, abs=1e-3)


def test_key_light():
    assert harness.key_light((0, 0, 0), 5, 10) == ((0, 0, 15), 800, 14)
    location, energy, size = harness.key_light((0, 0, 0), 5, 20)
    assert location == (0, 0, 25) and energy == pytest.approx(2000) and size == 20


def test_gray_ramp():
    expected = [
        (0.234442, 0.217221, 0.165558),
        (0.525795, 0.512898, 0.474205),
        (0.792057, 0.796029, 0.807943),
    ]
    for got, want in zip(harness.gray_ramp(3), expected):
        assert got == pytest.approx(want, abs=1e-3)
    assert harness.gray_ramp(0) == []
    assert harness.gray_ramp(1)[0] == pytest.approx(harness.gray_ramp(3)[0], abs=1e-9)


def test_overhang_fraction():
    faces = [(1, (0, 0, -1)), (1, (0, 0, 1)), (2, (0, -1, -1)), (1, (0, 0, 0))]
    assert harness.overhang_fraction(faces) == 0.6
    assert harness.overhang_fraction([]) == 0.0


def test_mesh_stats_payload_rounding():
    payload = harness.mesh_stats_payload((0, 0, 0), (90.60004, 90.6, 90.5974), 0.1392)
    assert payload == {"bbox_mm": [90.6, 90.6, 90.597], "overhang_area_frac": 0.1392}
    line = "MESH_STATS: " + json.dumps(payload)
    assert parse_harness_output(line + "\nABCAD_EXEC: OK", "").mesh_stats == payload
