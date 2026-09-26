"""
tests/agent/agent_fakes.py — deterministic test doubles for the abcad.agent test suite.

PURPOSE
    Stand-ins for every external dependency of the loop, so unit and replay tests exercise the
    real steps, routers, runner and gate module without network, Blender, GPU or model weights:

      FakeEmbedder        bag-of-words hash into 64 dimensions, L2-normalized
      FakeTransport       scripted chat-completions JSON (or exceptions); records every request
      FakeProcessRunner   canned Blender stdout / stderr / exit code, or a timeout
      ScriptedExecutor    scripted ExecutionReport per call; writes render / STL placeholders
      ScriptedChat        scripted text-model replies; records prompts and temperatures
      ScriptedCritic      scripted verdicts or exceptions
      FakePrintAudit, FakeFdmVariants, fake_pyvista_module   the deep-audit contract of the gate

INPUTS / OUTPUTS
    Pure Python + numpy. Nothing here touches the network or spawns processes.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import types
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import numpy as np

from abcad.agent.blender import ExecutionReport

FIXTURE_ERROR = "'Object' object has no attribute 'splines'"
REPAIRED_STATS = {"bbox_mm": [90.6, 90.6, 90.6], "overhang_area_frac": 0.1357}


# --------------------------------------------------------------------------------------------------
# Embedding
# --------------------------------------------------------------------------------------------------
class FakeEmbedder:
    """Deterministic bag-of-words embedder: each lowercase token hashes into one of 64 buckets."""

    DIM = 64

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        """Return an (n, 64) float32 array with L2-normalized rows (zero rows for empty text)."""
        items = list(texts)
        self.calls.append(items)
        out = np.zeros((len(items), self.DIM), dtype=np.float32)
        for row, text in enumerate(items):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                out[row, int.from_bytes(digest[:4], "big") % self.DIM] += 1.0
            norm = float(np.linalg.norm(out[row]))
            if norm > 0:
                out[row] /= norm
        return out


# --------------------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------------------
def chat_reply(content: Any = None, **message_fields: Any) -> dict:
    """A chat-completions response whose first choice carries the given message fields."""
    return {"choices": [{"message": {"role": "assistant", "content": content, **message_fields}}]}


class FakeTransport:
    """Scripted ChatTransport: each request pops the next response (a dict, or an exception)."""

    def __init__(self, responses: Iterable[Any]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def post_json(self, url: str, body: dict, headers: dict, timeout_s: float) -> dict:
        """Record the request and return (or raise) the next scripted item."""
        self.requests.append({"url": url, "body": body, "headers": headers, "timeout_s": timeout_s})
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class ScriptedChat:
    """Stand-in for ChatEndpoint.text(): scripted replies (str) or exceptions, in order."""

    def __init__(self, replies: Iterable[Any] = ()) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def text(self, prompt: str, *, temperature: float, max_tokens: int, model=None) -> str:
        """Record the call and return (or raise) the next scripted reply."""
        self.calls.append({"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens})
        if not self.replies:
            raise AssertionError("ScriptedChat ran out of replies")
        item = self.replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    @property
    def prompts(self) -> list[str]:
        """Prompts sent so far."""
        return [call["prompt"] for call in self.calls]

    @property
    def temperatures(self) -> list[float]:
        """Temperatures used so far."""
        return [call["temperature"] for call in self.calls]


def fenced(code: str) -> str:
    """A model reply that carries ``code`` in a python-tagged fence, with some prose around it."""
    return f"Here is the script:\n```python\n{code}\n```\nDone."


class ScriptedCritic:
    """Stand-in for RenderCritic.assess(): scripted verdict dicts or exceptions, in order."""

    def __init__(self, outcomes: Iterable[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str | None]] = []

    def assess(self, prompt: str, render_png: str | None) -> dict:
        """Record the call and return (a copy of) or raise the next outcome."""
        self.calls.append((prompt, render_png))
        if not self.outcomes:
            raise AssertionError("ScriptedCritic ran out of outcomes")
        item = self.outcomes.pop(0)
        if isinstance(item, BaseException):
            raise item
        return dict(item)


# --------------------------------------------------------------------------------------------------
# Blender
# --------------------------------------------------------------------------------------------------
class FakeProcessRunner:
    """subprocess.run stand-in with canned output, or a timeout; ``on_call`` sees each call."""

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        *,
        timeout: bool = False,
        on_call: Callable[[list[str], dict], None] | None = None,
    ) -> None:
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode
        self.timeout = timeout
        self.on_call = on_call
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        """Record the call, then return the canned result or raise TimeoutExpired."""
        self.calls.append((list(argv), kwargs))
        if self.on_call is not None:
            self.on_call(list(argv), kwargs)
        if self.timeout:
            raise subprocess.TimeoutExpired(
                argv, kwargs.get("timeout"), output=self.stdout.encode(), stderr=self.stderr
            )
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


def make_report(
    label: str,
    run_dir: str,
    *,
    ok: bool,
    error: str = "",
    mesh_stats: Mapping[str, Any] | None = None,
) -> ExecutionReport:
    """An ExecutionReport; successful ones get real placeholder render / STL files on disk."""
    render = stl = None
    if ok:
        os.makedirs(run_dir, exist_ok=True)
        render = os.path.join(run_dir, f"render_{label}.png")
        stl = os.path.join(run_dir, f"geom_{label}.stl")
        for path in (render, stl):
            with open(path, "wb") as handle:
                handle.write(b"placeholder")
    return ExecutionReport(
        label=label,
        ok=ok,
        status="success" if ok else "failed",
        render_png=render,
        stl_path=stl,
        mesh_stats=dict(mesh_stats or REPAIRED_STATS) if ok else None,
        error="" if ok else error,
        exit_code=0 if ok else 1,
        timed_out=False,
        seconds=0.01,
        script_copy=os.path.join(run_dir, f"{label}_generated.py"),
        blender_log=os.path.join(run_dir, f"{label}_blender.log"),
        blender_version="5.0.1",
    )


class ScriptedExecutor:
    """BlenderExecutor stand-in: each execute() pops the next outcome dict.

    Outcome keys: ``ok`` (bool), ``error`` (str) and optional ``mesh_stats``. ``on_execute`` is
    called with (label, script, run_dir) before the report is produced.
    """

    def __init__(
        self,
        outcomes: Iterable[Mapping[str, Any]],
        *,
        on_execute: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.outcomes = [dict(o) for o in outcomes]
        self.on_execute = on_execute
        self.calls: list[dict[str, str]] = []
        self.blender_version: str | None = None

    def execute(self, script: str, *, label: str, run_dir: str) -> ExecutionReport:
        """Record the call and return the next scripted report."""
        self.calls.append({"label": label, "script": script, "run_dir": run_dir})
        if self.on_execute is not None:
            self.on_execute(label, script, run_dir)
        if not self.outcomes:
            raise AssertionError(f"ScriptedExecutor ran out of outcomes at {label}")
        outcome = self.outcomes.pop(0)
        self.blender_version = "5.0.1"
        return make_report(
            label,
            run_dir,
            ok=bool(outcome.get("ok")),
            error=outcome.get("error", FIXTURE_ERROR),
            mesh_stats=outcome.get("mesh_stats"),
        )

    @property
    def labels(self) -> list[str]:
        """Labels executed so far, in order."""
        return [call["label"] for call in self.calls]


def ok(**extra: Any) -> dict:
    """Scripted successful execution."""
    return {"ok": True, **extra}


def fail(error: str = FIXTURE_ERROR) -> dict:
    """Scripted failed execution with the given error excerpt."""
    return {"ok": False, "error": error}


# --------------------------------------------------------------------------------------------------
# Deep-audit contract of the gate (print audit, STL variants, pyvista)
# --------------------------------------------------------------------------------------------------
class FakePrintAudit:
    """print_audit stand-in honoring the gate's contract.

    ``original`` and ``variant`` are dicts with ``surface``, ``voxel`` and ``grade`` entries; files
    whose name contains ``_autoscaled_x`` get the variant numbers. ``grade`` answers for the file
    most recently passed to ``surface_checks`` (the gate always calls surface, voxel, grade).
    """

    PROCESS_LIMITS = {
        "fdm": {"min_feature_mm": 0.8, "build_mm": (220.0, 220.0, 250.0)},
        "resin": {"min_feature_mm": 0.3, "build_mm": (145.0, 145.0, 175.0)},
    }

    def __init__(self, original: Mapping[str, Any], variant: Mapping[str, Any]) -> None:
        self.original, self.variant = original, variant
        self.audited: list[str] = []
        self._current: Mapping[str, Any] = original

    def _record(self, stl_path: str) -> Mapping[str, Any]:
        self._current = (
            self.variant if "_autoscaled_x" in os.path.basename(stl_path) else self.original
        )
        return self._current

    def surface_checks(self, stl_path: str) -> dict:
        """Surface record of the file (bbox, volume, watertight, manifold, overhang)."""
        self.audited.append(stl_path)
        return dict(self._record(stl_path)["surface"])

    def voxel_checks(self, stl_path: str, bbox_mm: Any) -> dict:
        """Voxel record of the file (voxel size, formable diameter, losses, voids)."""
        return dict(self._record(stl_path)["voxel"])

    def grade(self, process: str, surface: Mapping, voxel: Mapping) -> dict:
        """Verdict, issues and recommendations of the most recently audited file."""
        grade = self._current["grade"]
        return {
            "verdict": grade["verdict"],
            "issues": list(grade["issues"]),
            "recommendations": list(grade["recommendations"]),
        }


class FakeMesh:
    """pyvista mesh stand-in: triangulate() returns itself, save() writes a placeholder file."""

    def __init__(self, source: str = "") -> None:
        self.source = source

    def triangulate(self) -> FakeMesh:
        """Return the mesh itself (already triangles)."""
        return self

    def save(self, path: str) -> None:
        """Write a placeholder STL."""
        with open(path, "wb") as handle:
            handle.write(b"scaled placeholder")


class FakeFdmVariants:
    """fdm_variants stand-in: records the scale factor and target-size normalizations."""

    def __init__(self, orig_max_mm: float = 90.6) -> None:
        self.orig_max_mm = orig_max_mm
        self.scales: list[float] = []
        self.normalizations: list[tuple[str, float, str]] = []

    def scaled_about_base(self, mesh: FakeMesh, k: float) -> FakeMesh:
        """Uniform scale about the base center (recorded; geometry is not needed here)."""
        self.scales.append(k)
        return FakeMesh(mesh.source)

    def normalize_to_target_size(self, stl_path: str, target_max_mm: float, out_path: str) -> dict:
        """Write the sized placeholder and return the normalization record."""
        self.normalizations.append((stl_path, target_max_mm, out_path))
        with open(out_path, "wb") as handle:
            handle.write(b"sized placeholder")
        return {
            "target_max_mm": target_max_mm,
            "orig_max_mm": self.orig_max_mm,
            "new_max_mm": target_max_mm,
            "scale": target_max_mm / self.orig_max_mm,
            "out": out_path,
        }


def fake_pyvista_module() -> types.ModuleType:
    """A module named ``pyvista`` whose read() returns a FakeMesh."""
    module = types.ModuleType("pyvista")
    module.read = lambda path: FakeMesh(path)  # type: ignore[attr-defined]
    return module


def install_fake_audit(monkeypatch: Any, audit: FakePrintAudit, variants: FakeFdmVariants) -> None:
    """Route the gate module's lazy loaders (and its direct pyvista import) to the fakes."""
    from abcad.agent import manufacturability

    monkeypatch.setattr(manufacturability, "_load_print_audit", lambda: audit)
    monkeypatch.setattr(manufacturability, "_load_fdm_variants", lambda: variants)
    monkeypatch.setitem(sys.modules, "pyvista", fake_pyvista_module())


def audit_from_record(record: Mapping[str, Any]) -> tuple[FakePrintAudit, FakeFdmVariants]:
    """Build the audit fakes from one run entry of fixtures/recorded_runs.json."""
    audit = record["audit"]
    return FakePrintAudit(audit["original"], audit["variant"]), FakeFdmVariants()


# --------------------------------------------------------------------------------------------------
# Phase-2 components made of fakes
# --------------------------------------------------------------------------------------------------
def fake_components(settings: Any, *, executor: Any, chat: Any, critic: Any) -> Any:
    """Components with real retrieval (fake embedder), the real gate node, and scripted fakes."""
    from abcad.agent.gate import GatePreflight, make_gate_node
    from abcad.agent.retrieval import ExemplarIndex, ReferenceGallery
    from abcad.agent.runner import Components

    embedder = FakeEmbedder()
    return Components(
        embedder=embedder,
        exemplars=ExemplarIndex.from_corpora(
            settings.text_corpora, embedder, enabled=settings.rag_enabled
        ),
        gallery=ReferenceGallery.from_corpora(settings.vlm_corpora, embedder),
        chat=chat,
        executor=executor,
        critic=critic,
        gate_node=make_gate_node(settings),
        gate_preflight=GatePreflight(
            deep_audit_requested=settings.deep_audit, deep_audit_available=True, problems=[]
        ),
    )
