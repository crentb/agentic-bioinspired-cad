"""
abcad.agent — the local agentic LLM-to-CAD design loop.

PURPOSE
    Turns a short design request (for example "a woven cubic lattice metamaterial") into a
    Blender Python script, a render judged by a local vision-language critic, an exported STL and
    a single-material manufacturability verdict, and ends every run with a truthful run manifest.
    Everything runs on one machine: a fine-tuned code emitter (PyTorch, Phase-1 child process),
    Ollama for the critic and the repair / refine model, headless Blender, and the print audit.
    See docs/AGENT.md for the architecture, configuration and operating rules.

PUBLIC API (re-exported lazily)
    AgentSettings, load_settings   configuration (abcad.agent.settings)
    DesignLoop                     the explicit state-machine executor (abcad.agent.runner)
    run_design_loop, LoopOutcome   end-to-end two-phase orchestration (abcad.agent.runner)

    The command line is ``python -m abcad.agent`` (``abcad.agent.cli.main``).

INPUTS / OUTPUTS
    Importing this package imports nothing: the names above resolve on first attribute access
    (PEP 562). That keeps ``import abcad.agent.manufacturability`` and the fast test suite free of
    the loop's dependencies. The Phase-2 parent never loads the code emitter: peft and the
    emitter's model are loaded only inside the Phase-1 child. The parent's one model is the
    small retrieval embedder (sentence-transformers, on the CPU), loaded on first use.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

__all__ = ["AgentSettings", "DesignLoop", "LoopOutcome", "load_settings", "run_design_loop"]

# Public name -> defining submodule (resolved on first access).
_EXPORTS = {
    "AgentSettings": "abcad.agent.settings",
    "load_settings": "abcad.agent.settings",
    "DesignLoop": "abcad.agent.runner",
    "run_design_loop": "abcad.agent.runner",
    "LoopOutcome": "abcad.agent.runner",
}

if TYPE_CHECKING:  # static analyzers see the real names
    from abcad.agent.runner import DesignLoop, LoopOutcome, run_design_loop
    from abcad.agent.settings import AgentSettings, load_settings


def __getattr__(name: str) -> Any:
    """Resolve a public name lazily from its submodule."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'abcad.agent' has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache: later lookups bypass __getattr__
    return value


def __dir__() -> list[str]:
    """Include the lazily exported names in dir()."""
    return sorted(set(globals()) | set(__all__))
