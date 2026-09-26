"""
abcad.agent.emitter — the Phase-1 code emitter: a LoRA adapter on a local causal language model.

PURPOSE
    Turns a design request into a Blender Python script with a fine-tuned PEFT LoRA adapter
    (applied unmerged on its base model), grounded by retrieved code exemplars. The adapter was
    fine-tuned on one specific chat frame and user-text template; both are reproduced here
    exactly, because the adapter's output distribution depends on them:

      * the Llama-3 header tokens are written as literal text and the model's own chat template
        is NOT used (it injects a date preamble the adapter never saw);
      * the frame is tokenized with default special-token handling, so the tokenizer prepends its
        own beginning-of-text token in front of the literal one; that double token is part of
        the adapter's input distribution and is kept;
      * "Write Blender Python code for a " + prompt is used verbatim, so a prompt that starts with
        "a ..." yields "for a a ..." (kept: the emitter was validated with this exact instruction).

MEMORY
    This module is import-light: torch, transformers and peft are imported inside ``load()`` only
    (through the small ``_import_*`` seams, which tests replace with fakes). The emitter runs only
    inside the Phase-1 child process (see phase_one.py), which exits after the emit so that the
    PyTorch/Metal memory returns to the operating system.

INPUTS / OUTPUTS
    ``LoraCodeEmitter(settings, exemplars).load().emit(prompt, mode)`` -> ``EmitResult`` holding
    the normalized script, the raw completion (new tokens only), the user text, the exemplars used
    and the wall time. ``unload()`` drops every model reference and releases the MPS cache.
"""

from __future__ import annotations

import gc
import logging
import random
import time
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any, Final, Literal

from abcad.agent.retrieval import Exemplar, ExemplarIndex, format_exemplars
from abcad.agent.scripttext import extract_script, normalize_script

if TYPE_CHECKING:  # imported for annotations only; keeps runtime imports minimal
    from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

EmitMode = Literal["design", "direct"]

# --------------------------------------------------------------------------------------------------
# Prompt framing (external interface: the adapter was fine-tuned on exactly this text)
# --------------------------------------------------------------------------------------------------
# System text of the training frame. There is intentionally no final period.
SYSTEM_TEXT: Final[str] = "You are a helpful assistant"

_DESIGN_PREFIX = "Write Blender Python code for a "


def frame_llama3(user_text: str, system_text: str = SYSTEM_TEXT) -> str:
    """Wrap ``user_text`` in the literal Llama-3 chat frame the adapter was trained on.

    Args:
        user_text: the user turn (see :func:`compose_emitter_request`).
        system_text: the system turn; defaults to :data:`SYSTEM_TEXT`.

    Returns:
        The full prompt string, ending with the open assistant header.
    """
    return (
        "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
        + system_text
        + "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n"
        + user_text
        + "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
    )


def _check_mode(mode: str) -> None:
    """Reject unknown prompt modes early with a clear message."""
    if mode not in ("design", "direct"):
        raise ValueError(f"emit mode must be 'design' or 'direct', got {mode!r}")


def emitter_retrieval_query(prompt: str, mode: EmitMode) -> str:
    """Retrieval query of the emitter: the design prefix + prompt (no period), or the bare prompt."""
    _check_mode(mode)
    return _DESIGN_PREFIX + prompt if mode == "design" else prompt


def compose_emitter_request(prompt: str, mode: EmitMode, context: str) -> str:
    """Build the user text of the emitter prompt.

    Args:
        prompt: the design request.
        mode: ``"design"`` frames the prompt as "Write Blender Python code for a <prompt>.";
            ``"direct"`` passes the prompt unchanged (no period added).
        context: the retrieval context block (``""`` when retrieval is off; the surrounding text
            stays the same).

    Returns:
        The user text, ending with a line feed.
    """
    _check_mode(mode)
    if mode == "design":
        request_line = "User request: " + _DESIGN_PREFIX + prompt + "."
    else:
        request_line = "User request: " + prompt
    return (
        "You are a Blender scripting assistant.\n\n"
        + "Here are some useful base codes retrieved from the database:\n\n"
        + context
        + "\n\n"
        + request_line
        + "\n\n"
        + "Generate ONLY valid Blender Python code.\n"
    )


# --------------------------------------------------------------------------------------------------
# Lazy import seams (tests replace these with fakes; production imports the real libraries)
# --------------------------------------------------------------------------------------------------
def _import_torch() -> ModuleType:
    """Import torch on demand."""
    import torch

    return torch


def _import_transformers() -> ModuleType:
    """Import transformers on demand."""
    import transformers

    return transformers


def _import_peft() -> ModuleType:
    """Import peft on demand."""
    import peft

    return peft


def resolve_device(requested: str, torch: Any) -> str:
    """Resolve ``auto`` to ``mps`` (Apple GPU), else ``cuda:0``, else ``cpu``; keep explicit values."""
    if requested != "auto":
        return requested
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    cuda = getattr(torch, "cuda", None)
    if cuda is not None and cuda.is_available():
        return "cuda:0"
    return "cpu"


def resolve_dtype(name: str, torch: Any) -> Any:
    """Map the settings dtype name to a torch dtype (bfloat16 when asked, float16 otherwise)."""
    return torch.bfloat16 if name == "bfloat16" else torch.float16


# --------------------------------------------------------------------------------------------------
# The emitter
# --------------------------------------------------------------------------------------------------
@dataclass
class EmitResult:
    """Outcome of one emit.

    Attributes:
        script: the normalized script, ready to execute.
        completion: decoded text of the newly generated tokens only (special tokens skipped).
        user_text: the user turn that was framed and sent.
        exemplars: the retrieved exemplars placed in the context block.
        seconds: wall time of retrieval + generation + decoding.
    """

    script: str
    completion: str
    user_text: str
    exemplars: list[Exemplar] = field(default_factory=list)
    seconds: float = 0.0


class LoraCodeEmitter:
    """Loads the base model plus LoRA adapter and emits Blender scripts.

    Args:
        settings: loop settings (model ids, revisions, device, dtype, generation parameters).
        exemplars: code-exemplar index for the context block, or None for no retrieval.
    """

    def __init__(self, settings: AgentSettings, exemplars: ExemplarIndex | None) -> None:
        self._settings = settings
        self._exemplars = exemplars
        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._device: str | None = None

    @property
    def is_loaded(self) -> bool:
        """True while both the tokenizer and the adapted model are held."""
        return self._model is not None and self._tokenizer is not None

    def load(self) -> LoraCodeEmitter:
        """Load tokenizer, base model and adapter (unmerged PEFT wrapper), then switch to eval.

        Returns:
            self, for chaining.
        """
        if self.is_loaded:
            return self
        settings = self._settings
        torch = _import_torch()
        transformers = _import_transformers()
        peft = _import_peft()
        device = resolve_device(settings.emit_device, torch)
        dtype = resolve_dtype(settings.emit_dtype, torch)
        LOGGER.info(
            "loading emitter: base %s@%s + adapter %s@%s on %s (%s)",
            settings.base_model,
            settings.base_revision,
            settings.lora_adapter,
            settings.lora_revision,
            device,
            settings.emit_dtype,
        )
        tokenizer = transformers.AutoTokenizer.from_pretrained(
            settings.base_model, revision=settings.base_revision
        )
        base = transformers.AutoModelForCausalLM.from_pretrained(
            settings.base_model,
            revision=settings.base_revision,
            torch_dtype=dtype,  # accepted by every supported transformers release
            device_map={"": device},  # place the whole model on one device
        )
        # The adapter id is passed exactly as configured: the local cache keys on the string.
        model = peft.PeftModel.from_pretrained(
            base, settings.lora_adapter, revision=settings.lora_revision
        )
        model.eval()
        self._torch, self._tokenizer, self._model, self._device = torch, tokenizer, model, device
        LOGGER.info("emitter ready on device=%s dtype=%s", device, settings.emit_dtype)
        return self

    def unload(self) -> LoraCodeEmitter:
        """Drop the model and tokenizer, collect garbage and release the MPS allocator cache.

        The exemplar index is left intact. Calling it again (or before ``load``) is a no-op.

        Returns:
            self, for chaining.
        """
        if self._model is None and self._tokenizer is None:
            return self
        self._model = None
        self._tokenizer = None
        gc.collect()  # break reference cycles so the tensors are actually freed
        torch = self._torch
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and mps.is_available():
            torch.mps.empty_cache()  # hand cached Metal pages back to the operating system
        LOGGER.info("emitter unloaded")
        return self

    def emit(self, prompt: str, mode: EmitMode = "design") -> EmitResult:
        """Generate a script for ``prompt``.

        Args:
            prompt: the design request.
            mode: prompt framing (``"design"`` or ``"direct"``).

        Returns:
            The :class:`EmitResult`.

        Raises:
            RuntimeError: the emitter is not loaded.
        """
        if not self.is_loaded:
            raise RuntimeError("emitter is not loaded; call load() first")
        settings = self._settings
        started = time.perf_counter()

        # ---- retrieval context and prompt framing --------------------------------------------
        exemplars: list[Exemplar] = []
        if self._exemplars is not None and self._exemplars.enabled:
            query = emitter_retrieval_query(prompt, mode)
            exemplars = self._exemplars.search(query, settings.text_top_k)
        user_text = compose_emitter_request(prompt, mode, format_exemplars(exemplars))
        frame = frame_llama3(user_text)

        # ---- optional seeding (the default is unseeded, hence stochastic emits) --------------
        torch = self._torch
        if settings.emit_seed is not None:
            random.seed(settings.emit_seed)
            torch.manual_seed(settings.emit_seed)  # seeds the CPU and every accelerator device
            cuda = getattr(torch, "cuda", None)
            if cuda is not None and hasattr(cuda, "manual_seed_all"):
                cuda.manual_seed_all(settings.emit_seed)

        # ---- tokenize with DEFAULT special-token handling (keeps the double begin token) -----
        encoded = self._tokenizer(frame, return_tensors="pt")
        encoded = encoded.to(self._device)
        input_length = int(encoded["input_ids"].shape[-1])

        generation: dict[str, Any] = {
            "max_new_tokens": settings.emit_max_new_tokens,
            "do_sample": True,
            "temperature": settings.emit_temperature,
            "top_p": settings.emit_top_p,
        }
        # End-of-sequence ids come from the base model's generation config; pad_token_id is set
        # only to silence the library's "no pad token" warning.
        eos_id = getattr(self._tokenizer, "eos_token_id", None)
        if eos_id is not None:
            generation["pad_token_id"] = eos_id
        with torch.inference_mode():
            output = self._model.generate(**encoded, **generation)

        # ---- decode ONLY the new tokens (never the echoed prompt), then extract and normalize ------------------
        completion = self._tokenizer.decode(output[0][input_length:], skip_special_tokens=True)
        script = normalize_script(extract_script(completion))
        seconds = time.perf_counter() - started
        LOGGER.info("emitted %d characters in %.1f s", len(script), seconds)
        return EmitResult(
            script=script,
            completion=completion,
            user_text=user_text,
            exemplars=exemplars,
            seconds=seconds,
        )
