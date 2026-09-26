"""
abcad.agent.chat — client for a local OpenAI-compatible chat-completions endpoint (Ollama).

PURPOSE
    The repairer, the refiner and the render critic talk to local models served by Ollama through
    its OpenAI-compatible HTTP API (``POST {base}/chat/completions``). This module implements the
    two request shapes the loop needs, the response handling rules, retries, timeouts and the
    sovereignty guard, with nothing but the standard library:

      text call    {"model", "messages": [{"role": "user", "content": <str>}], "temperature",
                    "max_tokens"}; no system message, no streaming, no response_format
      vision call  the same with a content LIST of text and image_url blocks, plus an optional
                    "response_format" (JSON-schema constrained decoding of the critic verdict)

    Response: ``choices[0].message.content`` (null counts as ""), stripped. For vision calls
    only, an empty content falls back to the non-standard ``reasoning`` field and then
    ``reasoning_content``: a thinking model can spend its budget reasoning and leave the answer
    in the reasoning channel. Text calls never use that fallback (reasoning text is not code).

SECURITY / SOVEREIGNTY
    Only http and https URLs are ever contacted (http.client is used directly, so no other URL
    scheme handler exists). Unless ``allow_remote_llm`` is set, the endpoint host must be a
    loopback address; anything else raises SettingsError at construction. Every request has an
    explicit timeout.

INPUTS / OUTPUTS
    ChatEndpoint(settings, transport=None).text(...) / .vision(...) -> reply text (str).
    Failures after the retries raise ChatError (message includes the HTTP status and an excerpt
    of at most 200 characters of the response body).
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import ssl
import time
import urllib.parse
from collections.abc import Callable
from typing import Any, Protocol

from abcad.agent.settings import AgentSettings, SettingsError

LOGGER = logging.getLogger("abcad.agent")

# HTTP statuses worth retrying: request timeout, conflict (model busy loading), rate limiting, and
# every 5xx server error. Other 4xx statuses are caller errors and fail at once.
_RETRYABLE_STATUS = frozenset({408, 409, 429})
_EXCERPT_CHARS = 200


class ChatError(RuntimeError):
    """Transport, HTTP or protocol failure of a chat request (after retries)."""


class HttpStatusError(Exception):
    """Non-2xx HTTP response raised by a transport (the endpoint decides whether to retry)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


class TransportConnectionError(Exception):
    """Connection-level failure (refused, reset, DNS, timeout) raised by a transport."""


class ChatTransport(Protocol):
    """Injection point for the HTTP layer (tests use a scripted fake)."""

    def post_json(
        self, url: str, body: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        """POST ``body`` as JSON and return the decoded JSON object.

        Raises:
            HttpStatusError: the server answered with a non-2xx status.
            TransportConnectionError: the request could not be completed.
            ChatError: the response was not a JSON object.
        """
        ...


# --------------------------------------------------------------------------------------------------
# URL guard
# --------------------------------------------------------------------------------------------------
def is_loopback_host(host: str | None) -> bool:
    """True for ``localhost`` and every loopback IP literal (127.0.0.0/8, ::1)."""
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a DNS name other than localhost is not provably local


def validate_base_url(url: str, *, allow_remote: bool) -> None:
    """Apply the scheme check and the loopback guard to the endpoint URL.

    Args:
        url: the configured base URL (for example ``http://localhost:11434/v1``).
        allow_remote: when True, non-loopback hosts are accepted.

    Raises:
        SettingsError: the URL is not http(s), has no host, or is remote without permission.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SettingsError(f"ABCAD_LLM_BASE_URL: expected an http(s) URL with a host, got {url!r}")
    if not allow_remote and not is_loopback_host(parts.hostname):
        raise SettingsError(
            f"ABCAD_LLM_BASE_URL: {parts.hostname!r} is not a loopback address; the loop only "
            "talks to local models unless ABCAD_ALLOW_REMOTE_LLM=1"
        )


# --------------------------------------------------------------------------------------------------
# Standard-library transport
# --------------------------------------------------------------------------------------------------
class HttpJsonTransport:
    """``ChatTransport`` over ``http.client`` (http and https only, explicit timeout)."""

    def get_json(self, url: str, timeout_s: float) -> dict[str, Any]:
        """GET a JSON document (used for the daemon's native model list)."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ChatError(f"refusing to contact a non-http(s) URL: {url!r}")
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.hostname, parts.port, timeout=timeout_s, context=ssl.create_default_context()
            )
        else:
            connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout_s)
        try:
            connection.request("GET", parts.path or "/")
            response = connection.getresponse()
            status, raw = response.status, response.read()
        except (OSError, http.client.HTTPException) as exc:
            raise TransportConnectionError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            connection.close()
        text = raw.decode("utf-8", errors="replace")
        if not 200 <= status < 300:
            raise HttpStatusError(status, text)
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ChatError(f"unexpected JSON from {url!r}")
        return data

    def post_json(
        self, url: str, body: dict[str, Any], headers: dict[str, str], timeout_s: float
    ) -> dict[str, Any]:
        """POST JSON and decode the JSON reply (see :class:`ChatTransport`)."""
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ChatError(f"refusing to contact a non-http(s) URL: {url!r}")
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(
                parts.hostname, parts.port, timeout=timeout_s, context=ssl.create_default_context()
            )
        else:
            connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout_s)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        payload = json.dumps(body).encode("utf-8")
        try:
            connection.request("POST", target, body=payload, headers=headers)
            response = connection.getresponse()
            status = response.status
            raw = response.read()
        except (OSError, http.client.HTTPException) as exc:  # refused, reset, timeout, bad reply
            raise TransportConnectionError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            connection.close()
        text = raw.decode("utf-8", errors="replace")
        if not 200 <= status < 300:
            raise HttpStatusError(status, text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ChatError(
                f"invalid JSON from the chat endpoint (HTTP {status}): {text[:_EXCERPT_CHARS]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise ChatError(f"unexpected JSON from the chat endpoint: {text[:_EXCERPT_CHARS]!r}")
        return data


def release_resident_models(
    base_url: str, *, transport: HttpJsonTransport | None = None, timeout_s: float = 10.0
) -> list[str]:
    """Ask a local Ollama daemon to unload every model it holds; return the names released.

    Phase 1 loads the code emitter (about 8 GB) and relies on no chat model being resident. A
    run started within the daemon's keep-alive after an earlier run would otherwise load the
    emitter next to the critic (about 6 GB) and push a 16 GB machine deep into swap. Ollama's
    native API sits beside its OpenAI-compatible one: ``GET /api/ps`` lists resident models,
    and a generate request with ``keep_alive: 0`` unloads one. Best effort by design: another
    kind of server, or no server, is skipped quietly. The caller has already validated that the
    endpoint is a loopback address (or explicitly allowed).
    """
    transport = transport or HttpJsonTransport()
    root = base_url.rstrip("/")
    root = root[: -len("/v1")] if root.endswith("/v1") else root
    try:
        listed = transport.get_json(root + "/api/ps", timeout_s).get("models") or []
        names = [str(m.get("name") or m.get("model")) for m in listed if isinstance(m, dict)]
        for name in names:
            transport.post_json(
                root + "/api/generate",
                {"model": name, "keep_alive": 0},
                {"Content-Type": "application/json"},
                timeout_s,
            )
    except (ChatError, HttpStatusError, TransportConnectionError, ValueError) as exc:
        LOGGER.debug("no resident chat models released (%s)", exc)
        return []
    return names


# --------------------------------------------------------------------------------------------------
# Response helpers
# --------------------------------------------------------------------------------------------------
def _first_message(data: dict[str, Any]) -> dict[str, Any]:
    """``choices[0].message`` of a chat-completions response, or ChatError."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ChatError("chat response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ChatError("chat response has no choices[0].message")
    return message


def _as_text(value: Any) -> str:
    """Message field as text: null -> "", a list of content parts -> their joined text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):  # some servers return content parts
        return "".join(str(part.get("text", "")) for part in value if isinstance(part, dict))
    return str(value)


# --------------------------------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------------------------------
class ChatEndpoint:
    """Text and vision calls against the configured OpenAI-compatible endpoint.

    Args:
        settings: loop settings (URL, API key, models, timeout, retries, remote permission).
        transport: HTTP layer; defaults to :class:`HttpJsonTransport`.
        sleep: backoff sleeper (tests pass a no-op).

    Raises:
        SettingsError: at construction, when the URL fails the scheme check or loopback guard.
    """

    #: First backoff delay in seconds; attempt i waits BACKOFF_BASE_S * 2**i (1 s, 2 s, ...).
    BACKOFF_BASE_S = 1.0

    def __init__(
        self,
        settings: AgentSettings,
        transport: ChatTransport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        validate_base_url(settings.llm_base_url, allow_remote=settings.allow_remote_llm)
        self._settings = settings
        self._transport: ChatTransport = transport or HttpJsonTransport()
        self._sleep = sleep
        self.url = settings.llm_base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        """JSON content type plus the placeholder bearer token OpenAI-style servers expect."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.llm_api_key}",
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST with retries on connection errors and on HTTP 408/409/429/5xx."""
        attempts = 1 + max(0, self._settings.llm_max_retries)
        last_failure = "no attempt made"
        for attempt in range(attempts):
            try:
                return self._transport.post_json(
                    self.url, body, self._headers(), self._settings.llm_timeout_s
                )
            except HttpStatusError as exc:
                excerpt = exc.body[:_EXCERPT_CHARS]
                last_failure = f"HTTP {exc.status}: {excerpt!r}"
                if not (exc.status in _RETRYABLE_STATUS or exc.status >= 500):
                    raise ChatError(f"chat request failed with {last_failure}") from exc
            except TransportConnectionError as exc:
                last_failure = f"connection error: {exc}"
            if attempt < attempts - 1:
                delay = self.BACKOFF_BASE_S * (2**attempt)
                LOGGER.warning(
                    "chat request failed (%s); retry %d/%d in %.0f s",
                    last_failure,
                    attempt + 1,
                    attempts - 1,
                    delay,
                )
                self._sleep(delay)
        raise ChatError(f"chat request failed after {attempts} attempt(s): {last_failure}")

    def text(
        self, prompt: str, *, temperature: float, max_tokens: int, model: str | None = None
    ) -> str:
        """Single-turn text completion.

        Args:
            prompt: the user message.
            temperature: sampling temperature.
            max_tokens: completion budget.
            model: model name; defaults to ``settings.text_model``.

        Returns:
            The stripped message content ("" when the content is null).
        """
        body = {
            "model": model or self._settings.text_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        message = _first_message(self._post(body))
        return _as_text(message.get("content")).strip()

    def vision(
        self,
        blocks: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> str:
        """Single-turn multimodal completion with the reasoning-field fallback.

        Args:
            blocks: content blocks (``{"type": "text", ...}`` / ``{"type": "image_url", ...}``).
            temperature: sampling temperature.
            max_tokens: completion budget (reasoning and answer share it).
            response_format: optional structured-output specification; sent only when given.
            model: model name; defaults to ``settings.vlm_model``.

        Returns:
            The stripped content, or the stripped ``reasoning`` / ``reasoning_content`` text when
            the content is empty.
        """
        body: dict[str, Any] = {
            "model": model or self._settings.vlm_model,
            "messages": [{"role": "user", "content": blocks}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            body["response_format"] = response_format
        message = _first_message(self._post(body))
        content = _as_text(message.get("content")).strip()
        if content:
            return content
        for key in ("reasoning", "reasoning_content"):
            fallback = _as_text(message.get(key)).strip()
            if fallback:
                LOGGER.info("vision reply had empty content; using the %r field", key)
                return fallback
        return ""
