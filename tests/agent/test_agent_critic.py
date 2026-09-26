"""
U-06 / U-07: the render critic and the critique step (abcad.agent.critic).

Image encoding (640-pixel cap), verdict parsing and its exact error message, the content-block
order, the exact closing lines and response_format, and the step's retry, failure marker,
approval rules and latch.
"""

from __future__ import annotations

import base64
import struct
import zlib

import pytest
from agent_fakes import FakeTransport, ScriptedCritic, chat_reply

from abcad.agent.chat import ChatEndpoint
from abcad.agent.critic import (
    CRITIQUE_FAILED_PREFIX,
    VERDICT_RESPONSE_FORMAT,
    CritiqueStep,
    RenderCritic,
    VerdictParseError,
    image_data_uri,
    parse_verdict,
)
from abcad.agent.retrieval import ReferenceImage

GOOD = {
    "match_quality": "good",
    "physical_stability": "stable",
    "comment": "Fine.",
    "approve": True,
}
PARTIAL = {
    "match_quality": "partial",
    "physical_stability": "stable",
    "comment": "Needs more fibers.",
    "approve": False,
}


def write_png(path, width, height):
    """Write a valid 8-bit grayscale PNG with the standard library only (no Pillow needed)."""

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = b"".join(b"\x00" + bytes([(x * 7) % 256 for x in range(width)]) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    payload += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    path.write_bytes(payload)
    return path


def png_size(data):
    """(width, height) from a PNG's IHDR chunk."""
    return struct.unpack(">II", data[16:24])


def decode_uri(uri):
    """Bytes of a data URI produced by image_data_uri()."""
    prefix = "data:image/png;base64,"
    assert uri.startswith(prefix)
    return base64.b64decode(uri[len(prefix) :])


# --------------------------------------------------------------------------------------------------
# U-06: image encoding and parsing
# --------------------------------------------------------------------------------------------------
def test_large_render_is_downsampled_to_640(tmp_path):
    pytest.importorskip("PIL")  # the downsampling itself needs Pillow
    image = write_png(tmp_path / "render.png", 1280, 720)
    assert png_size(decode_uri(image_data_uri(str(image)))) == (640, 360)


def test_small_image_is_sent_unchanged(tmp_path):
    image = write_png(tmp_path / "small.png", 300, 200)
    assert decode_uri(image_data_uri(str(image))) == image.read_bytes()


def test_undecodable_image_falls_back_to_original_bytes(tmp_path):
    bogus = tmp_path / "bogus.png"
    bogus.write_bytes(b"not an image at all")
    assert decode_uri(image_data_uri(str(bogus), max_px=10)) == b"not an image at all"


def test_missing_image_raises(tmp_path):
    with pytest.raises(OSError):
        image_data_uri(str(tmp_path / "absent.png"))


def test_parse_verdict_accepts_raw_and_wrapped_json():
    raw = (
        '{"match_quality": "good", "physical_stability": "stable", "comment": "c", "approve": true}'
    )
    assert parse_verdict(raw)["approve"] is True
    wrapped = 'Sure!\n```json\n{\n  "approve": false,\n  "comment": "x"\n}\n```\nbye'
    assert parse_verdict(wrapped) == {"approve": False, "comment": "x"}


def test_parse_verdict_errors():
    with pytest.raises(VerdictParseError) as info:
        parse_verdict("")
    assert str(info.value) == "No JSON object found in VLM output (len=0): ''"
    with pytest.raises(VerdictParseError, match=r"len=6"):
        parse_verdict("[1, 2]")
    with pytest.raises(VerdictParseError, match="line one line two"):
        parse_verdict("line one\nline two")
    with pytest.raises(ValueError):  # JSON errors propagate (JSONDecodeError is a ValueError)
        parse_verdict("{not: json}")


def test_verdict_response_format_is_exact():
    assert VERDICT_RESPONSE_FORMAT == {
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


class _FakeGallery:
    """Gallery returning two references, the second of which has no file."""

    def __init__(self, present, missing):
        self.results = [
            ReferenceImage(0, 0.9, "woven reference", str(present), True, "woven", "cubic"),
            ReferenceImage(1, 0.4, "missing reference", str(missing), False, "helicoidal", ""),
        ]
        self.queries = []

    def search(self, query, k):
        self.queries.append((query, k))
        return self.results[:k]


def test_assess_block_order_instruction_and_request(tmp_path, settings):
    reference = write_png(tmp_path / "ref.png", 32, 16)
    candidate = write_png(tmp_path / "cand.png", 48, 24)
    gallery = _FakeGallery(reference, tmp_path / "absent.png")
    json_text = (
        '{"match_quality": "good", "physical_stability": "stable", "comment": "ok", '
        '"approve": true}'
    )
    transport = FakeTransport([chat_reply(json_text)])
    critic = RenderCritic(ChatEndpoint(settings, transport), gallery, settings)
    verdict = critic.assess("a woven cubic lattice metamaterial", str(candidate))
    assert verdict == parse_verdict(json_text)
    assert gallery.queries == [("a woven cubic lattice metamaterial", 2)]

    body = transport.requests[0]["body"]
    blocks = body["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["text", "image_url", "text", "image_url", "text"]
    assert "Reference image 1" in blocks[0]["text"] and "woven reference" in blocks[0]["text"]
    assert decode_uri(blocks[1]["image_url"]["url"]) == reference.read_bytes()
    assert "candidate" in blocks[2]["text"].lower()
    assert decode_uri(blocks[3]["image_url"]["url"]) == candidate.read_bytes()
    instruction = blocks[4]["text"]
    assert '"a woven cubic lattice metamaterial"' in instruction
    assert instruction.splitlines()[-2:] == [
        "Respond with ONLY the JSON object — no explanation, no markdown fences, "
        "no text before or after it.",
        "/no_think",
    ]
    assert body["max_tokens"] == 3000 and body["temperature"] == 0.1
    assert body["response_format"] == VERDICT_RESPONSE_FORMAT


def test_schema_can_be_switched_off(tmp_path, make_settings):
    settings = make_settings(verdict_schema=False)
    candidate = write_png(tmp_path / "cand.png", 8, 8)
    transport = FakeTransport([chat_reply('{"approve": false}')])
    RenderCritic(ChatEndpoint(settings, transport), None, settings).assess("p", str(candidate))
    assert "response_format" not in transport.requests[0]["body"]


# --------------------------------------------------------------------------------------------------
# U-07: the critique step
# --------------------------------------------------------------------------------------------------
def base_state(**extra):
    """Minimal state after a successful execution."""
    state = {
        "prompt": "p",
        "render_png": "/r/render_fix_run_2.png",
        "stl_path": "/r/geom_fix_run_2.stl",
        "critique_runs": 0,
        "ever_approved": False,
        "verdict": None,
    }
    state.update(extra)
    return state


def test_failure_then_verdict(settings):
    critic = ScriptedCritic([VerdictParseError("bad"), PARTIAL])
    update = CritiqueStep(critic, settings)(base_state())
    assert update["critique_runs"] == 1 and len(critic.calls) == 2
    assert update["verdict"] == PARTIAL and update["critique_failed"] is False
    assert update["feedback"] == str(PARTIAL)
    assert update["approved"] is False


def test_two_failures_mark_the_critique_failed(settings, caplog):
    previous = dict(GOOD)
    critic = ScriptedCritic([RuntimeError("first"), VerdictParseError("second")])
    update = CritiqueStep(critic, settings)(base_state(verdict=previous, approved=True))
    assert update["feedback"] == CRITIQUE_FAILED_PREFIX + "second"
    assert update["feedback"].startswith("VLM CRITIQUE FAILED (no verdict): ")
    assert update["critique_failed"] is True and update["approved"] is False
    assert "verdict" not in update  # the previous verdict stays in the state
    assert "critique error (try 1/2): first" in caplog.text


def test_latch_survives_a_later_rejection(settings):
    step = CritiqueStep(ScriptedCritic([GOOD, PARTIAL]), settings)
    first = step(base_state())
    assert first["approved"] is True and first["ever_approved"] is True
    second = step(base_state(ever_approved=first["ever_approved"], critique_runs=1))
    assert second["approved"] is False and second["ever_approved"] is True
    assert second["critique_runs"] == 2


def test_string_approve_is_not_approval(settings, caplog):
    verdict = dict(GOOD, approve="false")
    update = CritiqueStep(ScriptedCritic([verdict]), settings)(base_state())
    assert update["approved"] is False
    assert "not a boolean" in caplog.text


def test_approve_mismatch_is_logged_but_kept(settings, caplog):
    verdict = dict(PARTIAL, approve=True)
    update = CritiqueStep(ScriptedCritic([verdict]), settings)(base_state())
    assert update["approved"] is True
    assert "disagrees" in caplog.text


def test_best_artifact_on_approval(settings):
    update = CritiqueStep(ScriptedCritic([GOOD]), settings)(base_state())
    assert update["best_artifact"] == "/r/geom_fix_run_2.stl"
    no_stl = CritiqueStep(ScriptedCritic([GOOD]), settings)(base_state(stl_path=None))
    assert no_stl["best_artifact"] == "/r/render_fix_run_2.png"
    rejected = CritiqueStep(ScriptedCritic([PARTIAL]), settings)(base_state())
    assert "best_artifact" not in rejected
