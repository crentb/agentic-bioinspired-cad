"""
U-05: the OpenAI-compatible chat endpoint (abcad.agent.chat).

Request shapes, response handling (null content, reasoning fallbacks), retries with backoff, the
loopback guard, and the standard-library transport against a throwaway loopback HTTP server.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from agent_fakes import FakeTransport, chat_reply

from abcad.agent.chat import (
    ChatEndpoint,
    ChatError,
    HttpJsonTransport,
    HttpStatusError,
    TransportConnectionError,
    is_loopback_host,
    release_resident_models,
)
from abcad.agent.settings import SettingsError


def endpoint(settings, responses):
    """Endpoint over a scripted transport with backoff disabled."""
    transport = FakeTransport(responses)
    return ChatEndpoint(settings, transport, sleep=lambda seconds: None), transport


def test_text_request_shape(settings):
    chat, transport = endpoint(settings, [chat_reply("  import bpy  ")])
    assert chat.text("fix this", temperature=0.5, max_tokens=5000) == "import bpy"
    [request] = transport.requests
    assert request["url"] == "http://localhost:11434/v1/chat/completions"
    assert set(request["body"]) == {"model", "messages", "temperature", "max_tokens"}
    assert request["body"]["model"] == "qwen2.5-coder:7b"
    assert request["body"]["messages"] == [{"role": "user", "content": "fix this"}]
    assert request["body"]["temperature"] == 0.5 and request["body"]["max_tokens"] == 5000
    assert request["headers"]["Authorization"] == "Bearer local"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["timeout_s"] == settings.llm_timeout_s


def test_vision_sends_content_list_and_optional_response_format(settings):
    blocks = [{"type": "text", "text": "look"}]
    chat, transport = endpoint(settings, [chat_reply("{}"), chat_reply("{}")])
    chat.vision(blocks, temperature=0.1, max_tokens=3000)
    chat.vision(blocks, temperature=0.1, max_tokens=3000, response_format={"type": "json_object"})
    first, second = (r["body"] for r in transport.requests)
    assert first["model"] == "qwen3-vl:8b"
    assert first["messages"] == [{"role": "user", "content": blocks}]
    assert "response_format" not in first
    assert second["response_format"] == {"type": "json_object"}


def test_null_content_and_reasoning_fallbacks(settings):
    chat, _ = endpoint(
        settings,
        [
            chat_reply(None, reasoning="thinking only"),
            chat_reply("", reasoning='  {"approve": true}  '),
            chat_reply(None, reasoning_content="second fallback"),
            chat_reply(None),
        ],
    )
    # Text calls never use the reasoning channel.
    assert chat.text("p", temperature=0.1, max_tokens=10) == ""
    assert chat.vision([], temperature=0.1, max_tokens=10) == '{"approve": true}'
    assert chat.vision([], temperature=0.1, max_tokens=10) == "second fallback"
    assert chat.vision([], temperature=0.1, max_tokens=10) == ""


def test_retries_on_5xx_then_succeeds(settings):
    delays = []
    transport = FakeTransport(
        [HttpStatusError(500, "boom"), HttpStatusError(503, "busy"), chat_reply("ok")]
    )
    chat = ChatEndpoint(settings, transport, sleep=delays.append)
    assert chat.text("p", temperature=0.1, max_tokens=10) == "ok"
    assert len(transport.requests) == 3
    assert delays == [1.0, 2.0]  # exponential backoff


def test_connection_errors_are_retried_then_raise(settings):
    chat, transport = endpoint(settings, [TransportConnectionError("refused")] * 3)
    with pytest.raises(ChatError, match="refused"):
        chat.text("p", temperature=0.1, max_tokens=10)
    assert len(transport.requests) == 3  # one attempt + llm_max_retries (2)


def test_client_error_fails_at_once_with_status_and_excerpt(settings):
    chat, transport = endpoint(settings, [HttpStatusError(400, "x" * 500)])
    with pytest.raises(ChatError) as info:
        chat.text("p", temperature=0.1, max_tokens=10)
    assert len(transport.requests) == 1
    message = str(info.value)
    assert "400" in message and "x" * 200 in message and "x" * 201 not in message


@pytest.mark.parametrize("status", [408, 409, 429])
def test_retryable_client_statuses(settings, status):
    chat, transport = endpoint(settings, [HttpStatusError(status, ""), chat_reply("ok")])
    assert chat.text("p", temperature=0.1, max_tokens=10) == "ok"
    assert len(transport.requests) == 2


def test_missing_choices_raise(settings):
    chat, _ = endpoint(settings, [{"id": "x"}, {"choices": [{"text": "no message"}]}])
    with pytest.raises(ChatError):
        chat.text("p", temperature=0.1, max_tokens=10)
    with pytest.raises(ChatError):
        chat.vision([], temperature=0.1, max_tokens=10)


def test_loopback_guard(make_settings):
    with pytest.raises(SettingsError, match="loopback"):
        ChatEndpoint(make_settings(llm_base_url="http://10.0.0.5:11434/v1"))
    remote = ChatEndpoint(
        make_settings(llm_base_url="http://10.0.0.5:11434/v1", allow_remote_llm=True),
        FakeTransport([]),
    )
    assert remote.url == "http://10.0.0.5:11434/v1/chat/completions"
    for host in ("localhost", "127.0.0.1", "127.8.9.1", "::1"):
        assert is_loopback_host(host)
    for host in ("10.0.0.5", "example.com", "", None):
        assert not is_loopback_host(host)
    ChatEndpoint(make_settings(llm_base_url="http://[::1]:11434/v1/"), FakeTransport([]))


def test_stdlib_transport_refuses_other_schemes():
    with pytest.raises(ChatError):
        HttpJsonTransport().post_json("file:///etc/hosts", {}, {}, 1.0)


class _Handler(BaseHTTPRequestHandler):
    """Loopback test server: echoes the request as an OpenAI-style reply, or fails on /fail."""

    def do_POST(self):  # noqa: N802 - name required by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        if self.path.startswith("/fail"):
            body, status = b"server exploded", 500
        else:
            reply = {"echo": request, "auth": self.headers.get("Authorization")}
            body, status = json.dumps(chat_reply(json.dumps(reply))).encode(), 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output quiet
        pass


@pytest.fixture
def loopback_server():
    """A throwaway HTTP server on 127.0.0.1 (no external network is involved)."""
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_stdlib_transport_round_trip(loopback_server, make_settings):
    chat = ChatEndpoint(make_settings(llm_base_url=loopback_server + "/v1", llm_timeout_s=10))
    reply = json.loads(chat.text("hello", temperature=0.2, max_tokens=7))
    assert reply["auth"] == "Bearer local"
    assert reply["echo"]["messages"] == [{"role": "user", "content": "hello"}]


def test_stdlib_transport_http_error(loopback_server, make_settings):
    chat = ChatEndpoint(
        make_settings(llm_base_url=loopback_server + "/fail", llm_max_retries=0, llm_timeout_s=10)
    )
    with pytest.raises(ChatError, match="500"):
        chat.text("hello", temperature=0.2, max_tokens=7)


class _DaemonTransport:
    """Fake Ollama native API: lists resident models and records the unload requests."""

    def __init__(self, models, fail=None):
        self.models, self.fail, self.urls, self.bodies = models, fail, [], []

    def get_json(self, url, timeout_s):
        self.urls.append(url)
        if self.fail is not None:
            raise self.fail
        return {"models": [{"name": name} for name in self.models]}

    def post_json(self, url, body, headers, timeout_s):
        self.urls.append(url)
        self.bodies.append(body)
        return {"done": True}


def test_release_resident_models_unloads_each_resident_model():
    daemon = _DaemonTransport(["qwen3-vl:8b"])
    released = release_resident_models("http://127.0.0.1:11435/v1", transport=daemon)
    assert released == ["qwen3-vl:8b"]
    # The native API sits beside the OpenAI-compatible /v1 root.
    assert daemon.urls == ["http://127.0.0.1:11435/api/ps", "http://127.0.0.1:11435/api/generate"]
    assert daemon.bodies == [{"model": "qwen3-vl:8b", "keep_alive": 0}]


def test_release_resident_models_with_nothing_resident_sends_no_unload():
    daemon = _DaemonTransport([])
    assert release_resident_models("http://127.0.0.1:11434/v1", transport=daemon) == []
    assert daemon.bodies == []


@pytest.mark.parametrize(
    "failure", [TransportConnectionError("refused"), HttpStatusError(404, "not found")]
)
def test_release_resident_models_is_best_effort(failure):
    daemon = _DaemonTransport(["qwen3-vl:8b"], fail=failure)
    assert release_resident_models("http://127.0.0.1:1/v1", transport=daemon) == []
