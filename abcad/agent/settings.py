"""
abcad.agent.settings — configuration of the agentic design loop in one immutable object.

PURPOSE
    Collects every knob of the loop (paths, Blender, the Phase-1 code emitter, retrieval, the local
    chat endpoint, the render critic, repair and refine, the manufacturability gate and the runner)
    in a single frozen dataclass, ``AgentSettings``. ``load_settings()`` reads the ``ABCAD_*``
    environment variables ONCE, validates them and returns the object. Components receive the
    settings object and never read the environment themselves; the single exception is the gate's
    target-size bridge (see ``gate.target_size_env``), which exists because the moved gate module
    reads ``ABCAD_TARGET_SIZE_MM`` directly.

PRECEDENCE (highest first)
    explicit keyword overrides  >  ABCAD_* environment variables  >  the dataclass defaults

PARSING RULES
    booleans      1/0, true/false, yes/no, on/off (case-insensitive)
    numbers       parsed strictly (no silent truncation); malformed or out-of-range values raise
                  SettingsError naming the variable
    path lists    split on os.pathsep (":" on macOS and Linux)
    number lists  split on ","
    empty string  counts as unset
    paths         "~" is expanded and relative paths resolve against the working directory at
                  load time; shipped data (corpora, renders) is located only through
                  abcad.resources, never through the working directory

INPUTS / OUTPUTS
    Input:  a mapping of environment variables (default ``os.environ``) plus keyword overrides
            keyed by field name.
    Output: ``AgentSettings``. ``AgentSettings.paths`` derives the output folders,
            ``AgentSettings.snapshot()`` returns the secret-free subset recorded in the run
            manifest, and ``AgentSettings.to_env()`` renders the settings back into ``ABCAD_*``
            variables so the Phase-1 child process sees exactly the parent's configuration.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields
from typing import Any, NamedTuple

import abcad
from abcad import resources

LOGGER = logging.getLogger("abcad.agent")

# --------------------------------------------------------------------------------------------------
# Constants shared with other modules (defaults that are also referenced by the CLI and the tests)
# --------------------------------------------------------------------------------------------------
# Prompt used when the command line gives none (a helicoidal family member the corpora cover).
DEFAULT_PROMPT = "a double-twist helical Bouligand structure"

# Standard location of the Blender executable inside the macOS application bundle. It is the LAST
# fallback of the discovery order (ABCAD_BLENDER, then `blender` on PATH, then this bundle path).
MACOS_BLENDER_PATH = "/Applications/Blender.app/Contents/MacOS/Blender"

# Hugging Face identifiers of the Phase-1 models. They are external interface constants: the local
# model cache keys on the exact strings, so the casing must never be normalized.
DEFAULT_BASE_MODEL = "meta-llama/Llama-3.2-3B-Instruct"
DEFAULT_LORA_ADAPTER = "rachelkluu/Bioinspired3D"
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Fields that must never be written to a manifest or a log (the bearer token for the endpoint).
_SECRET_FIELDS = frozenset({"llm_api_key"})

# Valid choices of the enumerated settings.
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_DTYPE_ALIASES = {
    "float16": "float16",
    "fp16": "float16",
    "bfloat16": "bfloat16",
    "bf16": "bfloat16",
}


class SettingsError(ValueError):
    """A configuration value is malformed, out of range, or violates a guard (names the variable)."""


class AgentPaths(NamedTuple):
    """Absolute output locations derived from ``AgentSettings.out_dir`` (and ``debug_dir``).

    Attributes:
        out_dir: repository-wide output root (``ABCAD_OUT``).
        runs_dir: one sub-folder per run; the dashboard reads ``<runs_dir>/*/run_manifest.json``.
        tmp_dir: Blender job files and the Phase-1 hand-off file.
        debug_dir: copies of repair and refine candidates, written before they execute.
        handoff_path: file through which the Phase-1 child hands its script to the parent.
    """

    out_dir: str
    runs_dir: str
    tmp_dir: str
    debug_dir: str
    handoff_path: str


# --------------------------------------------------------------------------------------------------
# Default factories (evaluated per instance so that AgentSettings() is complete on its own)
# --------------------------------------------------------------------------------------------------
def discover_blender() -> str:
    """Return the Blender executable to use when ``ABCAD_BLENDER`` is unset.

    Discovery order: ``blender`` on ``PATH``, then the standard macOS application bundle. When
    neither exists the bare name ``blender`` is returned; the run preflight then reports a clear
    error instead of failing later inside the executor.
    """
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    if os.path.isfile(MACOS_BLENDER_PATH):
        return MACOS_BLENDER_PATH
    return "blender"


def _default_text_corpora() -> tuple[str, ...]:
    """The shipped code-exemplar corpus, located through abcad.resources (works from a wheel)."""
    return (str(resources.text_corpus_path()),)


def _default_vlm_corpora() -> tuple[str, ...]:
    """The shipped reference-render corpus, located through abcad.resources."""
    return (str(resources.vlm_corpus_path()),)


# --------------------------------------------------------------------------------------------------
# The settings object
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class AgentSettings:
    """Every configurable value of the loop. Construct it with :func:`load_settings`.

    The field groups follow the configuration table in docs/AGENT.md (A: paths and I/O, B: Blender,
    C: Phase-1 emitter, D: retrieval, E: chat endpoint, F: critic, G: repair and refine, H: gate,
    I: runner). Units: seconds for ``*_s``, millimetres for ``*_mm``, pixels for ``*_px``.
    """

    # ---- A. paths and I/O ------------------------------------------------------------------------
    out_dir: str = "out"  # output root; runs, job files and debug copies live below it
    debug_dir: str | None = None  # None -> <out_dir>/agent_debug
    keep_temp: bool = False  # keep Blender job files after each execution (debugging aid)
    run_log: bool = True  # tee all console output of a run into <run_dir>/run.log
    log_level: str = "INFO"  # level of the "abcad.agent" logger

    # ---- B. Blender ------------------------------------------------------------------------------
    blender_path: str = field(default_factory=discover_blender)
    blender_timeout_s: float = 300.0  # hard cap per script execution (a hung script cannot stall)
    render_resolution: tuple[int, int] = (1280, 720)  # render size; the critic downsamples it
    render_samples: int = 64  # anti-aliasing samples of the real-time renderer

    # ---- C. Phase-1 code emitter (fine-tuned LoRA on a local base model) --------------------------
    base_model: str = DEFAULT_BASE_MODEL
    base_revision: str = "main"  # pin a commit hash to freeze the weights
    lora_adapter: str = DEFAULT_LORA_ADAPTER  # exact casing: the cache keys on the string
    lora_revision: str = "main"
    emit_device: str = "auto"  # auto -> mps, else cuda:0, else cpu (resolved inside the child)
    emit_dtype: str = "float16"  # float16 | bfloat16 (aliases fp16 / bf16 accepted)
    emit_mode: str = "design"  # prompt framing: "design" or "direct"
    emit_max_new_tokens: int = 2048  # generation parameters the adapter was exercised with
    emit_temperature: float = 0.1
    emit_top_p: float = 0.9
    emit_seed: int | None = None  # unset -> stochastic emits (the documented default)
    emit_timeout_s: float = 1800.0  # cap on the whole Phase-1 child process

    # ---- D. retrieval ----------------------------------------------------------------------------
    rag_enabled: bool = True  # code-exemplar retrieval for the emitter, repair and refine
    embed_model: str = DEFAULT_EMBED_MODEL
    embed_revision: str = "main"
    embed_device: str = "cpu"  # CPU keeps the Metal allocator out of the Phase-2 parent
    text_corpora: tuple[str, ...] = field(default_factory=_default_text_corpora)
    vlm_corpora: tuple[str, ...] = field(default_factory=_default_vlm_corpora)
    reference_image_root: str | None = None  # extra base directory for legacy image paths
    text_top_k: int = 2  # exemplars per context block
    reference_top_k: int = 2  # reference renders per critique (fits the 8192-token context)

    # ---- E. chat endpoint (local OpenAI-compatible server) ----------------------------------------
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = field(default="local", repr=False)  # placeholder bearer token
    text_model: str = "qwen2.5-coder:7b"  # repair and refine (non-thinking coder model)
    vlm_model: str = "qwen3-vl:8b"  # render critic
    llm_timeout_s: float = 600.0  # per request; covers cold model loads
    llm_max_retries: int = 2  # transport-level retries with exponential backoff
    allow_remote_llm: bool = False  # sovereignty guard: loopback endpoints only unless true
    expected_context_length: int = 8192  # daemon context the run assumes (recorded)

    # ---- F. critic -------------------------------------------------------------------------------
    vlm_temperature: float = 0.1
    vlm_max_tokens: int = 3000  # thinking and verdict share this budget
    vlm_image_max_px: int = 640  # long-side cap of every image sent to the critic
    critique_attempts: int = 2  # one retry on any critique failure
    verdict_schema: bool = True  # send the JSON-schema response_format

    # ---- G. repair and refine --------------------------------------------------------------------
    repair_attempts: int = 3  # attempts per repair visit
    repair_temperature_ladder: tuple[float, ...] = (0.1, 0.5, 0.8)  # start, then escalations
    refine_temperature: float = 0.1
    text_max_tokens: int = 5000  # a full script plus any hidden reasoning
    max_iter: int = 3  # cap on refine visits per run

    # ---- H. manufacturability gate ---------------------------------------------------------------
    print_process: str = "fdm"  # fdm | resin
    deep_audit: bool = True  # quantitative STL audit (+ auto-scale) once per approved design
    target_size_mm: float | None = None  # optional largest-dimension normalization before audit
    build_volume_mm: tuple[float, float, float] = (220.0, 220.0, 250.0)
    require_deep_audit: bool = False  # abort before Phase 1 when the deep audit is unavailable

    # ---- I. runner -------------------------------------------------------------------------------
    step_limit: int = 25  # safety cap on step executions (legitimate runs use at most 13)
    default_prompt: str = DEFAULT_PROMPT

    # ------------------------------------------------------------------------------------------
    # Derived views
    # ------------------------------------------------------------------------------------------
    @property
    def paths(self) -> AgentPaths:
        """Absolute output locations derived from ``out_dir`` and ``debug_dir``."""
        out = os.path.abspath(self.out_dir)
        tmp = os.path.join(out, "agent_tmp")
        debug = (
            os.path.abspath(self.debug_dir) if self.debug_dir else os.path.join(out, "agent_debug")
        )
        return AgentPaths(
            out_dir=out,
            runs_dir=os.path.join(out, "agent_runs"),
            tmp_dir=tmp,
            debug_dir=debug,
            handoff_path=os.path.join(tmp, "generated_code.py"),
        )

    def snapshot(self) -> dict[str, Any]:
        """Return the configuration block of the run manifest.

        Every field except secrets (the API key) is included, tuples are rendered as lists so the
        block is plain JSON, and the package version is prepended. The Blender version is not a
        setting; the manifest builder adds it from the harness output.

        Returns:
            A new JSON-serializable dict.
        """
        block: dict[str, Any] = {"package_version": abcad.__version__}
        for spec in fields(self):
            if spec.name in _SECRET_FIELDS:
                continue
            value = getattr(self, spec.name)
            block[spec.name] = list(value) if isinstance(value, tuple) else value
        return block

    def to_env(self) -> dict[str, str]:
        """Render these settings as ``ABCAD_*`` variables (the inverse of :func:`load_settings`).

        Used to start the Phase-1 child: keyword overrides given to the parent would otherwise be
        invisible to a process that re-reads its environment. Unset optional values map to "",
        which the loader treats as unset.

        Returns:
            Mapping of variable name to string value, for every environment-backed field.
        """
        env: dict[str, str] = {}
        for var in _ENV_VARS:
            env[var.env] = _to_text(getattr(self, var.field))
        # Composite corpus lists: first entry is the primary corpus, the rest are extras.
        for primary_var, extra_var, name in _CORPUS_VARS:
            corpora = getattr(self, name)
            env[primary_var] = corpora[0] if corpora else ""
            env[extra_var] = os.pathsep.join(corpora[1:])
        if not self.text_corpora:
            # An empty exemplar list means "no retrieval"; an empty variable would instead mean
            # "use the shipped corpus", so disable retrieval explicitly for the child.
            env["ABCAD_RAG"] = "0"
        return env


# --------------------------------------------------------------------------------------------------
# Value parsers. Each takes the variable name (for the error message) and the raw text, and
# returns the typed value or raises SettingsError. They are shared by the environment path and the
# keyword-override path so that both obey identical rules.
# --------------------------------------------------------------------------------------------------
Parser = Callable[[str, str], Any]


def _fail(name: str, expected: str, raw: str) -> SettingsError:
    """Build a SettingsError naming the variable, the expectation and the offending text."""
    return SettingsError(f"{name}: expected {expected}, got {raw!r}")


def _parse_text(name: str, raw: str) -> str:
    """Free text (model ids, revisions, devices); surrounding whitespace is dropped."""
    return raw.strip()


def _parse_bool(name: str, raw: str) -> bool:
    """Accept 1/0, true/false, yes/no, on/off in any letter case."""
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise _fail(name, "a boolean (1/0, true/false, yes/no, on/off)", raw)


def _int_parser(minimum: int | None) -> Parser:
    """Strict base-10 integer parser with an optional inclusive lower bound."""

    def parse(name: str, raw: str) -> int:
        try:
            value = int(raw.strip(), 10)  # rejects "3.0" and "3x": no silent truncation
        except ValueError:
            raise _fail(name, "an integer", raw) from None
        if minimum is not None and value < minimum:
            raise _fail(name, f"an integer >= {minimum}", raw)
        return value

    return parse


def _float_parser(minimum: float, *, strict: bool = False, maximum: float | None = None) -> Parser:
    """Finite float parser with a lower bound (exclusive when ``strict``) and optional maximum."""

    def parse(name: str, raw: str) -> float:
        try:
            value = float(raw.strip())
        except ValueError:
            raise _fail(name, "a number", raw) from None
        if not math.isfinite(value):
            raise _fail(name, "a finite number", raw)
        too_small = value <= minimum if strict else value < minimum
        if too_small or (maximum is not None and value > maximum):
            relation = ">" if strict else ">="
            bound = f"{relation} {minimum:g}" + (
                f" and <= {maximum:g}" if maximum is not None else ""
            )
            raise _fail(name, f"a number {bound}", raw)
        return value

    return parse


def _float_list_parser(*, length: int | None, minimum: float, strict: bool) -> Parser:
    """Comma-separated list of finite floats, each bounded below; optional exact length."""
    item = _float_parser(minimum, strict=strict)

    def parse(name: str, raw: str) -> tuple[float, ...]:
        parts = [p for p in (s.strip() for s in raw.split(",")) if p]
        if not parts or (length is not None and len(parts) != length):
            count = f"{length} " if length is not None else "one or more "
            raise _fail(name, f"{count}comma-separated numbers", raw)
        return tuple(item(name, p) for p in parts)

    return parse


def _int_pair_parser(name: str, raw: str) -> tuple[int, int]:
    """Two comma-separated positive integers (render resolution in pixels)."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        raise _fail(name, "two comma-separated integers", raw)
    positive = _int_parser(1)
    return (positive(name, parts[0]), positive(name, parts[1]))


def _choice_parser(*choices: str) -> Parser:
    """Case-insensitive choice among fixed lowercase values."""

    def parse(name: str, raw: str) -> str:
        value = raw.strip().lower()
        if value not in choices:
            raise _fail(name, "one of " + ", ".join(choices), raw)
        return value

    return parse


def _parse_log_level(name: str, raw: str) -> str:
    """A standard logging level name."""
    value = raw.strip().upper()
    if value not in _LOG_LEVELS:
        raise _fail(name, "one of " + ", ".join(_LOG_LEVELS), raw)
    return value


def _parse_dtype(name: str, raw: str) -> str:
    """Emitter dtype. Unknown values fall back to float16 with a warning (reference behavior)."""
    value = raw.strip().lower()
    if value in _DTYPE_ALIASES:
        return _DTYPE_ALIASES[value]
    LOGGER.warning("%s=%r is not a supported dtype; falling back to float16", name, raw)
    return "float16"


def _parse_path(name: str, raw: str) -> str:
    """One filesystem path: "~" expanded, relative paths anchored at the working directory."""
    return os.path.abspath(os.path.expanduser(raw.strip()))


def _parse_path_list(name: str, raw: str) -> tuple[str, ...]:
    """os.pathsep-separated path list; empty entries (e.g. a trailing separator) are ignored."""
    return tuple(_parse_path(name, p) for p in raw.split(os.pathsep) if p.strip())


def _parse_executable(name: str, raw: str) -> str:
    """Blender executable: a path is anchored at the working directory; a bare name uses PATH."""
    value = os.path.expanduser(raw.strip())
    if os.sep in value or (os.altsep and os.altsep in value):
        return os.path.abspath(value)
    return shutil.which(value) or value  # unresolved names are reported by the preflight


def _parse_http_url(name: str, raw: str) -> str:
    """An http(s) URL with a host. The loopback guard itself is applied by the chat endpoint."""
    value = raw.strip()
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _fail(name, "an http:// or https:// URL with a host", raw)
    return value


class _EnvVar(NamedTuple):
    """Binding of one settings field to its environment variable and parser."""

    field: str
    env: str
    parse: Parser


# Every environment-backed scalar setting. The corpus lists are composite (a primary variable plus
# an "extra" list variable) and are handled by _CORPUS_VARS below.
_ENV_VARS: tuple[_EnvVar, ...] = (
    # A. paths and I/O
    _EnvVar("out_dir", "ABCAD_OUT", _parse_path),
    _EnvVar("debug_dir", "ABCAD_AGENT_DEBUG_DIR", _parse_path),
    _EnvVar("keep_temp", "ABCAD_KEEP_TEMP", _parse_bool),
    _EnvVar("run_log", "ABCAD_RUN_LOG", _parse_bool),
    _EnvVar("log_level", "ABCAD_LOG_LEVEL", _parse_log_level),
    # B. Blender
    _EnvVar("blender_path", "ABCAD_BLENDER", _parse_executable),
    _EnvVar("blender_timeout_s", "ABCAD_BLENDER_TIMEOUT_S", _float_parser(0.0, strict=True)),
    # C. Phase-1 emitter
    _EnvVar("base_model", "ABCAD_BASE_MODEL", _parse_text),
    _EnvVar("base_revision", "ABCAD_BASE_REVISION", _parse_text),
    _EnvVar("lora_adapter", "ABCAD_LORA_ADAPTER", _parse_text),
    _EnvVar("lora_revision", "ABCAD_LORA_REVISION", _parse_text),
    _EnvVar("emit_device", "ABCAD_EMIT_DEVICE", _parse_text),
    _EnvVar("emit_dtype", "ABCAD_EMIT_DTYPE", _parse_dtype),
    _EnvVar("emit_mode", "ABCAD_EMIT_MODE", _choice_parser("design", "direct")),
    _EnvVar("emit_max_new_tokens", "ABCAD_EMIT_MAX_NEW_TOKENS", _int_parser(1)),
    _EnvVar("emit_temperature", "ABCAD_EMIT_TEMPERATURE", _float_parser(0.0)),
    _EnvVar("emit_top_p", "ABCAD_EMIT_TOP_P", _float_parser(0.0, strict=True, maximum=1.0)),
    _EnvVar("emit_seed", "ABCAD_EMIT_SEED", _int_parser(0)),
    _EnvVar("emit_timeout_s", "ABCAD_EMIT_TIMEOUT_S", _float_parser(0.0, strict=True)),
    # D. retrieval (corpus lists: see _CORPUS_VARS)
    _EnvVar("rag_enabled", "ABCAD_RAG", _parse_bool),
    _EnvVar("embed_model", "ABCAD_EMBED_MODEL", _parse_text),
    _EnvVar("embed_revision", "ABCAD_EMBED_REVISION", _parse_text),
    _EnvVar("embed_device", "ABCAD_EMBED_DEVICE", _parse_text),
    _EnvVar("reference_image_root", "ABCAD_REFERENCE_IMAGE_ROOT", _parse_path),
    _EnvVar("text_top_k", "ABCAD_TEXT_TOP_K", _int_parser(0)),
    _EnvVar("reference_top_k", "ABCAD_REFERENCE_TOP_K", _int_parser(0)),
    # E. chat endpoint
    _EnvVar("llm_base_url", "ABCAD_LLM_BASE_URL", _parse_http_url),
    _EnvVar("llm_api_key", "ABCAD_LLM_API_KEY", _parse_text),
    _EnvVar("text_model", "ABCAD_TEXT_MODEL", _parse_text),
    _EnvVar("vlm_model", "ABCAD_VLM_MODEL", _parse_text),
    _EnvVar("llm_timeout_s", "ABCAD_LLM_TIMEOUT_S", _float_parser(0.0, strict=True)),
    _EnvVar("llm_max_retries", "ABCAD_LLM_MAX_RETRIES", _int_parser(0)),
    _EnvVar("allow_remote_llm", "ABCAD_ALLOW_REMOTE_LLM", _parse_bool),
    _EnvVar("expected_context_length", "ABCAD_EXPECTED_CONTEXT", _int_parser(1)),
    # F. critic
    _EnvVar("vlm_temperature", "ABCAD_VLM_TEMPERATURE", _float_parser(0.0)),
    _EnvVar("vlm_max_tokens", "ABCAD_VLM_MAX_TOKENS", _int_parser(1)),
    _EnvVar("vlm_image_max_px", "ABCAD_VLM_IMAGE_MAX_PX", _int_parser(1)),
    _EnvVar("critique_attempts", "ABCAD_CRITIQUE_ATTEMPTS", _int_parser(1)),
    _EnvVar("verdict_schema", "ABCAD_VERDICT_SCHEMA", _parse_bool),
    # G. repair and refine
    _EnvVar("repair_attempts", "ABCAD_REPAIR_ATTEMPTS", _int_parser(1)),
    _EnvVar(
        "repair_temperature_ladder",
        "ABCAD_REPAIR_TEMPERATURES",
        _float_list_parser(length=None, minimum=0.0, strict=False),
    ),
    _EnvVar("refine_temperature", "ABCAD_REFINE_TEMPERATURE", _float_parser(0.0)),
    _EnvVar("text_max_tokens", "ABCAD_TEXT_MAX_TOKENS", _int_parser(1)),
    _EnvVar("max_iter", "ABCAD_MAX_ITER", _int_parser(0)),
    # H. manufacturability gate
    _EnvVar("print_process", "ABCAD_PRINT_PROCESS", _choice_parser("fdm", "resin")),
    _EnvVar("deep_audit", "ABCAD_DEEP_AUDIT", _parse_bool),
    _EnvVar("target_size_mm", "ABCAD_TARGET_SIZE_MM", _float_parser(0.0, strict=True)),
    _EnvVar(
        "build_volume_mm",
        "ABCAD_BUILD_VOLUME_MM",
        _float_list_parser(length=3, minimum=0.0, strict=True),
    ),
    _EnvVar("require_deep_audit", "ABCAD_REQUIRE_DEEP_AUDIT", _parse_bool),
    # I. runner
    _EnvVar("step_limit", "ABCAD_STEP_LIMIT", _int_parser(1)),
)

# Composite corpus lists: (primary variable, extras variable, field name).
_CORPUS_VARS: tuple[tuple[str, str, str], ...] = (
    ("ABCAD_TEXT_CORPUS", "ABCAD_TEXT_CORPORA_EXTRA", "text_corpora"),
    ("ABCAD_VLM_CORPUS", "ABCAD_VLM_CORPORA_EXTRA", "vlm_corpora"),
)

# Parsers for fields that have no environment variable but may be overridden by keyword.
_OVERRIDE_ONLY: dict[str, Parser] = {
    "render_resolution": _int_pair_parser,
    "render_samples": _int_parser(1),
    "default_prompt": _parse_text,
    "text_corpora": _parse_path_list,
    "vlm_corpora": _parse_path_list,
}

_FIELD_PARSERS: dict[str, Parser] = {v.field: v.parse for v in _ENV_VARS} | _OVERRIDE_ONLY
_PATH_LIST_FIELDS = frozenset({"text_corpora", "vlm_corpora"})


def environment_variables() -> tuple[str, ...]:
    """Every ``ABCAD_*`` variable :func:`load_settings` reads (documentation and tests)."""
    names = [v.env for v in _ENV_VARS]
    for primary, extra, _ in _CORPUS_VARS:
        names.extend((primary, extra))
    return tuple(names)


# --------------------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------------------
def _to_text(value: Any, *, path_list: bool = False) -> str:
    """Render a typed value in the textual form its parser accepts (None -> "" = unset)."""
    if value is None:
        return ""
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)  # repr round-trips floats exactly
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, (tuple, list)):
        items = [_to_text(v) for v in value]
        return os.pathsep.join(items) if path_list else ",".join(items)
    return str(value)


def _corpus_list(env: Mapping[str, str], primary_var: str, extra_var: str, name: str) -> tuple:
    """Compose a corpus list: the primary (variable or shipped default) followed by the extras."""
    raw_primary = env.get(primary_var, "")
    if raw_primary.strip():
        primary: tuple[str, ...] = (_parse_path(primary_var, raw_primary),)
    else:
        default = _default_text_corpora() if name == "text_corpora" else _default_vlm_corpora()
        primary = default
    extras = _parse_path_list(extra_var, env.get(extra_var, ""))
    return primary + extras


def load_settings(env: Mapping[str, str] | None = None, **overrides: Any) -> AgentSettings:
    """Build validated settings from the environment and keyword overrides.

    Args:
        env: environment mapping to read; defaults to ``os.environ``. It is read once.
        **overrides: values keyed by ``AgentSettings`` field name. They take precedence over the
            environment. Typed values (bool, int, float, tuple, path) and strings are both
            accepted and pass through the same validation as environment values; ``None`` means
            "use the default".

    Returns:
        An immutable :class:`AgentSettings`.

    Raises:
        SettingsError: an unknown override name, or a malformed or out-of-range value. The
            message names the environment variable (or the field, for overrides).
    """
    source: Mapping[str, str] = os.environ if env is None else env
    known = {f.name for f in fields(AgentSettings)}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise SettingsError("unknown setting(s): " + ", ".join(unknown))

    values: dict[str, Any] = {}

    # ---- environment layer: only non-empty variables count (empty string == unset) -------------
    for var in _ENV_VARS:
        raw = source.get(var.env, "")
        if raw.strip():
            values[var.field] = var.parse(var.env, raw)
    for primary_var, extra_var, name in _CORPUS_VARS:
        values[name] = _corpus_list(source, primary_var, extra_var, name)

    # ---- override layer: same parsers, applied to the textual form of each value --------------
    for name, value in overrides.items():
        if value is None:
            values.pop(name, None)  # fall back to the dataclass default
            continue
        text = _to_text(value, path_list=name in _PATH_LIST_FIELDS)
        label = f"{name} (keyword override)"
        if not text.strip() and name not in _PATH_LIST_FIELDS:
            values.pop(name, None)
            continue
        values[name] = _FIELD_PARSERS[name](label, text)

    # ---- defaults that depend on the working directory are anchored now ------------------------
    values.setdefault("out_dir", os.path.abspath("out"))
    return AgentSettings(**values)


def iter_env_bindings() -> Iterable[tuple[str, str]]:
    """Yield ``(field, variable)`` pairs for the scalar environment bindings (for tests/docs)."""
    for var in _ENV_VARS:
        yield var.field, var.env
