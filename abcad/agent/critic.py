"""
abcad.agent.critic — the render critic (a local vision-language model) and the critique step.

PURPOSE
    ``RenderCritic.assess(prompt, render_png)`` shows the critic model the most similar reference
    renders from the gallery, then the candidate render, then an instruction, and returns the
    parsed verdict::

        {"match_quality": "good" | "partial" | "poor",
         "physical_stability": "stable" | "unstable",
         "comment": "<one sentence>",
         "approve": true | false}

    Defenses against empty or malformed verdicts, in order: JSON-schema constrained decoding
    (``VERDICT_RESPONSE_FORMAT``), the strict-JSON instruction, the reasoning-field fallback of the
    chat client, first-to-last-brace extraction, and one retry in the step.

    ``CritiqueStep`` is the loop step. It retries once, applies the approval rules (only the JSON
    boolean ``true`` approves; the ever-approved latch) and on failure records the exact marker
    ``VLM CRITIQUE FAILED (no verdict): `` so the router can end the run honestly.

INPUTS / OUTPUTS
    Images are downsampled to a 640-pixel long side before encoding (about 300 instead of 1100
    vision tokens per 1280 x 720 render; the structures being judged are large-scale). Pillow is
    imported lazily; without it the original bytes are sent.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from collections.abc import Mapping
from typing import Any, Final

from abcad.agent.chat import ChatEndpoint
from abcad.agent.console import event
from abcad.agent.retrieval import ReferenceGallery
from abcad.agent.settings import AgentSettings

LOGGER = logging.getLogger("abcad.agent")

# JSON schema of the verdict, sent as the vision call's response_format. Ollama turns it into
# grammar-constrained decoding, so the content channel can only carry schema-valid JSON.
VERDICT_RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "render_critic_verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "match_quality": {"type": "string", "enum": ["good", "partial", "poor"]},
                "physical_stability": {"type": "string", "enum": ["stable", "unstable"]},
                "comment": {"type": "string"},
                "approve": {"type": "boolean"},
            },
            "required": ["match_quality", "physical_stability", "comment", "approve"],
            "additionalProperties": False,
        },
    },
}

# Exact prefix of the feedback text after a failed critique (routers and tests rely on it).
CRITIQUE_FAILED_PREFIX: Final[str] = "VLM CRITIQUE FAILED (no verdict): "

# The final two lines of the instruction. The second is a soft request to skip reasoning; the
# recorded critic ignores it (its template always thinks), so it is one defense among several.
_CLOSING_LINES = (
    "Respond with ONLY the JSON object — no explanation, no markdown fences, "
    "no text before or after it.\n/no_think"
)

_DATA_URI_PREFIX = "data:image/png;base64,"


class VerdictParseError(ValueError):
    """The critic's reply holds no JSON object."""


# --------------------------------------------------------------------------------------------------
# Image encoding and verdict parsing
# --------------------------------------------------------------------------------------------------
def image_data_uri(path: str, max_px: int = 640) -> str:
    """Encode an image as a PNG data URI, downsampled so its long side is at most ``max_px``.

    Images larger than the cap are thumbnailed into a ``max_px`` x ``max_px`` box (aspect ratio
    kept, Pillow's default resampling) and re-encoded as PNG in memory. Smaller images, and any
    image Pillow cannot handle, are sent as their original bytes.

    Args:
        path: image file.
        max_px: long-side cap in pixels.

    Returns:
        ``"data:image/png;base64," + base64(bytes)``.

    Raises:
        OSError: the file cannot be read (the critique step's retry handles it).
    """
    with open(path, "rb") as handle:
        original = handle.read()
    payload = original
    try:
        from PIL import Image  # optional dependency, imported only when an image is encoded

        with Image.open(io.BytesIO(original)) as image:
            if max(image.size) > max_px:
                image.thumbnail((max_px, max_px))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                payload = buffer.getvalue()
    except Exception:  # Pillow missing or unable to decode: fall back to the original bytes
        payload = original
    return _DATA_URI_PREFIX + base64.b64encode(payload).decode("ascii")


def parse_verdict(text: str) -> dict[str, Any]:
    """Extract the verdict object from the critic's reply.

    The substring from the first ``{`` to the last ``}`` (inclusive, possibly spanning lines) is
    parsed as JSON; JSON errors propagate.

    Args:
        text: the critic's reply.

    Returns:
        The verdict dict.

    Raises:
        VerdictParseError: the reply contains no brace-delimited object.
        json.JSONDecodeError: the extracted text is not valid JSON.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        excerpt = repr(text[:200].replace("\n", " "))
        raise VerdictParseError(f"No JSON object found in VLM output (len={len(text)}): {excerpt}")
    return json.loads(text[start : end + 1])


def compose_critic_instruction(prompt: str) -> str:
    """The final instruction block of the critique request.

    It casts the model as a critic of 3D renders, quotes the design concept verbatim, asks for an
    independent judgment on two criteria, states the approval rule, fixes the strict JSON shape,
    and ends with the two exact closing lines.
    """
    return (
        "You are an expert critic of 3D model renders.\n"
        f'The intended design concept is: "{prompt}"\n'
        "The reference images above show related structures for context only. Evaluate the "
        "candidate render independently on two criteria:\n"
        '1. match_quality: how well the candidate realizes the design concept ("good", '
        '"partial" or "poor").\n'
        "2. physical_stability: whether the structure is physically coherent, connected and "
        'self-supporting ("stable" or "unstable").\n'
        'Set "approve" to true only if match_quality is "good" AND physical_stability is '
        '"stable"; otherwise set it to false.\n'
        "Answer in strict JSON with exactly these keys:\n"
        '{"match_quality": "good" | "partial" | "poor", '
        '"physical_stability": "stable" | "unstable", '
        '"comment": "<one sentence>", "approve": true | false}\n' + _CLOSING_LINES
    )


# --------------------------------------------------------------------------------------------------
# The critic component
# --------------------------------------------------------------------------------------------------
class RenderCritic:
    """Vision-language critic grounded by retrieved reference renders.

    Args:
        chat: chat endpoint (vision calls).
        gallery: reference-render gallery, or None for an ungrounded critique.
        settings: loop settings (reference count, image cap, budget, temperature, schema flag).
    """

    def __init__(
        self, chat: ChatEndpoint, gallery: ReferenceGallery | None, settings: AgentSettings
    ) -> None:
        self._chat = chat
        self._gallery = gallery
        self._settings = settings
        self._reference_cache: dict[str, str] = {}  # reference renders never change in a run

    def _reference_uri(self, path: str) -> str:
        """Data URI of a reference render, encoded once per run."""
        if path not in self._reference_cache:
            self._reference_cache[path] = image_data_uri(path, self._settings.vlm_image_max_px)
        return self._reference_cache[path]

    def build_blocks(self, prompt: str, render_png: str) -> list[dict[str, Any]]:
        """Content blocks: labeled references, the labeled candidate, then the instruction."""
        settings = self._settings
        if not render_png:
            raise FileNotFoundError("no render to critique")
        references = []
        if self._gallery is not None and settings.reference_top_k > 0:
            found = self._gallery.search(prompt, settings.reference_top_k)
            references = [r for r in found if r.exists and os.path.isfile(r.path)]
            references = references[: settings.reference_top_k]
        blocks: list[dict[str, Any]] = []
        for ordinal, reference in enumerate(references, start=1):
            blocks.append(
                {"type": "text", "text": f"Reference image {ordinal}: {reference.caption}"}
            )
            blocks.append(
                {"type": "image_url", "image_url": {"url": self._reference_uri(reference.path)}}
            )
        candidate_uri = image_data_uri(render_png, settings.vlm_image_max_px)
        blocks.append({"type": "text", "text": "Candidate render to evaluate:"})
        blocks.append({"type": "image_url", "image_url": {"url": candidate_uri}})
        blocks.append({"type": "text", "text": compose_critic_instruction(prompt)})
        return blocks

    def assess(self, prompt: str, render_png: str) -> dict[str, Any]:
        """Critique one render and return the parsed verdict (raises on any failure)."""
        settings = self._settings
        reply = self._chat.vision(
            self.build_blocks(prompt, render_png),
            temperature=settings.vlm_temperature,
            max_tokens=settings.vlm_max_tokens,
            response_format=VERDICT_RESPONSE_FORMAT if settings.verdict_schema else None,
        )
        verdict = parse_verdict(reply)
        if not isinstance(verdict, dict):  # defensive: brace extraction yields an object
            raise VerdictParseError("VLM verdict is not a JSON object")
        return verdict


# --------------------------------------------------------------------------------------------------
# The loop step
# --------------------------------------------------------------------------------------------------
class CritiqueStep:
    """Loop step ``critique``: judge the latest successful render (see the module docstring).

    Args:
        critic: an object with ``assess(prompt, render_png) -> dict`` (normally RenderCritic).
        settings: loop settings (number of attempts).
    """

    def __init__(self, critic: Any, settings: AgentSettings) -> None:
        self._critic = critic
        self._settings = settings

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Run the critique and return the state update."""
        attempts = self._settings.critique_attempts
        update: dict[str, Any] = {"critique_runs": int(state.get("critique_runs") or 0) + 1}
        last_error = "no attempt made"
        verdict: dict[str, Any] | None = None
        for attempt in range(1, attempts + 1):
            try:
                verdict = self._critic.assess(state.get("prompt") or "", state.get("render_png"))
                break
            except Exception as exc:  # any failure (transport, parse, image) consumes a try
                last_error = str(exc) or type(exc).__name__
                LOGGER.warning("critique error (try %d/%d): %s", attempt, attempts, last_error)
                event("critique_try_failed", attempt=attempt, error=last_error)

        if verdict is None:
            update.update(
                feedback=CRITIQUE_FAILED_PREFIX + last_error,
                approved=False,
                critique_failed=True,
            )  # "verdict" is left unchanged on purpose; critique_failed disambiguates it
            event("critique_failed", error=last_error)
            return update

        raw_approve = verdict.get("approve")
        approved = (
            raw_approve is True
        )  # only the JSON boolean true approves (not the string "true")
        if not isinstance(raw_approve, bool):
            LOGGER.warning("verdict 'approve' is not a boolean (%r); treated as false", raw_approve)
        match, stability = verdict.get("match_quality"), verdict.get("physical_stability")
        if approved != (match == "good" and stability == "stable"):
            LOGGER.warning(
                "verdict 'approve'=%r disagrees with match=%r / stability=%r; decision kept",
                raw_approve,
                match,
                stability,
            )
        update.update(
            verdict=verdict,
            feedback=str(verdict),  # Python str() of the dict is exactly what the refiner reads
            approved=approved,
            ever_approved=bool(state.get("ever_approved")) or approved,
            critique_failed=False,
        )
        if approved:
            update["best_artifact"] = state.get("stl_path") or state.get("render_png")
        LOGGER.info(
            "critique: approve=%s match=%s stability=%s comment=%s",
            approved,
            match,
            stability,
            verdict.get("comment"),
        )
        event(
            "critique_verdict",
            approve=approved,
            match=match,
            stability=stability,
            comment=verdict.get("comment"),
        )
        return update
