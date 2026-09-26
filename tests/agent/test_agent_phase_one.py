"""
The Phase-1 child launcher (abcad.agent.phase_one) and the run preflight (abcad.agent.runner).

The emitter child runs in its own session, so no signal sent to the parent's process group
reaches it. These tests pin that every abnormal end of the parent's wait (Ctrl-C, SIGTERM from a
supervisor or watchdog) kills the child's process group before the parent unwinds, that the
parent's signal handlers are restored afterwards, and that the preflight rejects a --use-code
file that is not readable UTF-8 before any run folder exists.
"""

from __future__ import annotations

import os
import signal
import threading

import pytest

from abcad.agent import phase_one, runner


class _Process:
    """Fake child process whose ``wait`` raises the given exception."""

    pid = 424242  # never a real process group: _kill_process_group is replaced in these tests

    def __init__(self, exc: BaseException | None) -> None:
        self.exc = exc
        self.stdout = iter(())  # the output-forwarding thread finishes at once

    def wait(self, timeout=None):
        raise self.exc


def _emit(settings, process):
    """Run emit_via_child against a fake process (no real child is started)."""
    return phase_one.emit_via_child(
        "a woven cubic lattice", settings, log=lambda line: None, popen=lambda *a, **k: process
    )


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), phase_one._ParentTerminated(143)])
def test_interrupted_wait_kills_the_child_group(settings, monkeypatch, exc):
    killed = []
    monkeypatch.setattr(
        phase_one, "_kill_process_group", lambda process: killed.append(process.pid)
    )
    with pytest.raises(type(exc)):
        _emit(settings, _Process(exc))
    assert killed == [_Process.pid]


def test_signal_handlers_are_restored_after_the_wait(settings, monkeypatch):
    before = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(phase_one, "_kill_process_group", lambda process: None)
    with pytest.raises(KeyboardInterrupt):
        _emit(settings, _Process(KeyboardInterrupt()))
    assert signal.getsignal(signal.SIGTERM) is before


def test_sigterm_during_the_wait_exits_143_after_killing_the_child(settings, monkeypatch):
    # A real SIGTERM to this process while it waits: the handler installed by emit_via_child must
    # turn it into a SystemExit with status 128 + 15, and the child's group must be killed first.
    # Without the handler SIGTERM would end the test process, so run it only in the main thread.
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers can only be installed from the main thread")
    killed = []
    monkeypatch.setattr(phase_one, "_kill_process_group", lambda process: killed.append(True))

    class _Signalled(_Process):
        def wait(self, timeout=None):
            os.kill(os.getpid(), signal.SIGTERM)  # the handler raises here, in the main thread
            raise AssertionError("the SIGTERM handler did not interrupt the wait")

    with pytest.raises(SystemExit) as info:
        _emit(settings, _Signalled(None))
    assert info.value.code == 128 + signal.SIGTERM
    assert killed == [True]


def test_preflight_rejects_a_use_code_file_that_is_not_utf8(settings, tmp_path):
    bad = tmp_path / "emit.py"
    bad.write_bytes(b"import bpy\n\xff\xfe not UTF-8\n")
    with pytest.raises(runner.PreflightError, match="UTF-8"):
        runner.preflight(settings, use_code=str(bad))


def test_preflight_accepts_a_readable_use_code_file(settings, tmp_path):
    good = tmp_path / "emit.py"
    good.write_text("import bpy\n", encoding="utf-8")
    runner.preflight(settings, use_code=str(good))  # no exception
