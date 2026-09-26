"""
U-17: configuration loading (abcad.agent.settings).

Every ABCAD_* variable is parsed, invalid values name the variable, keyword overrides beat the
environment, derived paths are correct, and the manifest snapshot carries no secret.
"""

from __future__ import annotations

import os

import pytest

from abcad import resources
from abcad.agent.settings import (
    DEFAULT_PROMPT,
    AgentSettings,
    SettingsError,
    environment_variables,
    iter_env_bindings,
    load_settings,
)

# (variable, raw text, field, expected typed value) for every scalar environment binding. Path
# values are relative on purpose: they must resolve against the working directory at load time.
SCALAR_CASES = [
    ("ABCAD_OUT", "custom_out", "out_dir", "@cwd/custom_out"),
    ("ABCAD_AGENT_DEBUG_DIR", "dbg", "debug_dir", "@cwd/dbg"),
    ("ABCAD_KEEP_TEMP", "yes", "keep_temp", True),
    ("ABCAD_RUN_LOG", "off", "run_log", False),
    ("ABCAD_LOG_LEVEL", "debug", "log_level", "DEBUG"),
    ("ABCAD_BLENDER", "tools/blender", "blender_path", "@cwd/tools/blender"),
    ("ABCAD_BLENDER_TIMEOUT_S", "120.5", "blender_timeout_s", 120.5),
    ("ABCAD_BASE_MODEL", "org/base", "base_model", "org/base"),
    ("ABCAD_BASE_REVISION", "abc123", "base_revision", "abc123"),
    ("ABCAD_LORA_ADAPTER", "org/Adapter", "lora_adapter", "org/Adapter"),
    ("ABCAD_LORA_REVISION", "def456", "lora_revision", "def456"),
    ("ABCAD_EMIT_DEVICE", "cpu", "emit_device", "cpu"),
    ("ABCAD_EMIT_DTYPE", "bf16", "emit_dtype", "bfloat16"),
    ("ABCAD_EMIT_MODE", "DIRECT", "emit_mode", "direct"),
    ("ABCAD_EMIT_MAX_NEW_TOKENS", "1024", "emit_max_new_tokens", 1024),
    ("ABCAD_EMIT_TEMPERATURE", "0.3", "emit_temperature", 0.3),
    ("ABCAD_EMIT_TOP_P", "0.95", "emit_top_p", 0.95),
    ("ABCAD_EMIT_SEED", "7", "emit_seed", 7),
    ("ABCAD_EMIT_TIMEOUT_S", "900", "emit_timeout_s", 900.0),
    ("ABCAD_RAG", "0", "rag_enabled", False),
    ("ABCAD_EMBED_MODEL", "org/embed", "embed_model", "org/embed"),
    ("ABCAD_EMBED_REVISION", "e1", "embed_revision", "e1"),
    ("ABCAD_EMBED_DEVICE", "mps", "embed_device", "mps"),
    ("ABCAD_REFERENCE_IMAGE_ROOT", "imgs", "reference_image_root", "@cwd/imgs"),
    ("ABCAD_TEXT_TOP_K", "4", "text_top_k", 4),
    ("ABCAD_REFERENCE_TOP_K", "1", "reference_top_k", 1),
    ("ABCAD_LLM_BASE_URL", "http://127.0.0.1:9000/v1", "llm_base_url", "http://127.0.0.1:9000/v1"),
    ("ABCAD_LLM_API_KEY", "token", "llm_api_key", "token"),
    ("ABCAD_TEXT_MODEL", "coder:1b", "text_model", "coder:1b"),
    ("ABCAD_VLM_MODEL", "vision:2b", "vlm_model", "vision:2b"),
    ("ABCAD_LLM_TIMEOUT_S", "30", "llm_timeout_s", 30.0),
    ("ABCAD_LLM_MAX_RETRIES", "0", "llm_max_retries", 0),
    ("ABCAD_ALLOW_REMOTE_LLM", "true", "allow_remote_llm", True),
    ("ABCAD_EXPECTED_CONTEXT", "16384", "expected_context_length", 16384),
    ("ABCAD_VLM_TEMPERATURE", "0.2", "vlm_temperature", 0.2),
    ("ABCAD_VLM_MAX_TOKENS", "2500", "vlm_max_tokens", 2500),
    ("ABCAD_VLM_IMAGE_MAX_PX", "512", "vlm_image_max_px", 512),
    ("ABCAD_CRITIQUE_ATTEMPTS", "3", "critique_attempts", 3),
    ("ABCAD_VERDICT_SCHEMA", "no", "verdict_schema", False),
    ("ABCAD_REPAIR_ATTEMPTS", "5", "repair_attempts", 5),
    ("ABCAD_REPAIR_TEMPERATURES", "0.2, 0.6", "repair_temperature_ladder", (0.2, 0.6)),
    ("ABCAD_REFINE_TEMPERATURE", "0.4", "refine_temperature", 0.4),
    ("ABCAD_TEXT_MAX_TOKENS", "6000", "text_max_tokens", 6000),
    ("ABCAD_MAX_ITER", "0", "max_iter", 0),
    ("ABCAD_PRINT_PROCESS", "Resin", "print_process", "resin"),
    ("ABCAD_DEEP_AUDIT", "false", "deep_audit", False),
    ("ABCAD_TARGET_SIZE_MM", "58", "target_size_mm", 58.0),
    ("ABCAD_BUILD_VOLUME_MM", "250,210,210", "build_volume_mm", (250.0, 210.0, 210.0)),
    ("ABCAD_REQUIRE_DEEP_AUDIT", "on", "require_deep_audit", True),
    ("ABCAD_STEP_LIMIT", "40", "step_limit", 40),
]


def _expected(value, cwd):
    """Replace the "@cwd/" marker by the working directory."""
    if isinstance(value, str) and value.startswith("@cwd/"):
        return os.path.join(cwd, value[len("@cwd/") :])
    return value


def test_every_scalar_binding_has_a_case():
    covered = {case[0] for case in SCALAR_CASES}
    assert covered == {env for _, env in iter_env_bindings()}


@pytest.mark.parametrize("var, raw, field, expected", SCALAR_CASES)
def test_each_variable_is_parsed(tmp_path, monkeypatch, var, raw, field, expected):
    monkeypatch.chdir(tmp_path)
    settings = load_settings(env={var: raw})
    assert getattr(settings, field) == _expected(expected, os.getcwd())


def test_all_variables_at_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = {var: raw for var, raw, _, _ in SCALAR_CASES}
    settings = load_settings(env=env)
    for _, _, field, expected in SCALAR_CASES:
        assert getattr(settings, field) == _expected(expected, os.getcwd()), field


def test_corpus_lists_compose_primary_and_extras(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = {
        "ABCAD_TEXT_CORPORA_EXTRA": os.pathsep.join(["a.jsonl", "b.jsonl", ""]),
        "ABCAD_VLM_CORPUS": "mine.jsonl",
        "ABCAD_VLM_CORPORA_EXTRA": "extra.jsonl",
    }
    settings = load_settings(env=env)
    assert settings.text_corpora == (
        str(resources.text_corpus_path()),
        str(tmp_path / "a.jsonl"),
        str(tmp_path / "b.jsonl"),
    )
    assert settings.vlm_corpora == (str(tmp_path / "mine.jsonl"), str(tmp_path / "extra.jsonl"))
    names = set(environment_variables())
    assert {"ABCAD_TEXT_CORPUS", "ABCAD_TEXT_CORPORA_EXTRA"} <= names
    assert {"ABCAD_VLM_CORPUS", "ABCAD_VLM_CORPORA_EXTRA"} <= names


def test_defaults_and_shipped_corpora():
    settings = load_settings(env={})
    assert settings.text_corpora == (str(resources.text_corpus_path()),)
    assert settings.vlm_corpora == (str(resources.vlm_corpus_path()),)
    assert settings.default_prompt == DEFAULT_PROMPT
    assert settings.repair_temperature_ladder == (0.1, 0.5, 0.8)
    assert settings.build_volume_mm == (220.0, 220.0, 250.0)
    assert settings.max_iter == 3 and settings.step_limit == 25
    assert settings.llm_base_url == "http://localhost:11434/v1"
    assert settings.emit_seed is None and settings.target_size_mm is None


@pytest.mark.parametrize(
    "var, raw",
    [
        ("ABCAD_MAX_ITER", "three"),
        ("ABCAD_MAX_ITER", "3.0"),
        ("ABCAD_MAX_ITER", "-1"),
        ("ABCAD_KEEP_TEMP", "maybe"),
        ("ABCAD_BLENDER_TIMEOUT_S", "0"),
        ("ABCAD_BLENDER_TIMEOUT_S", "nan"),
        ("ABCAD_EMIT_TOP_P", "1.5"),
        ("ABCAD_BUILD_VOLUME_MM", "220,220"),
        ("ABCAD_REPAIR_TEMPERATURES", "0.1,x"),
        ("ABCAD_PRINT_PROCESS", "sls"),
        ("ABCAD_EMIT_MODE", "creative"),
        ("ABCAD_LOG_LEVEL", "LOUD"),
        ("ABCAD_LLM_BASE_URL", "ftp://localhost/v1"),
        ("ABCAD_TARGET_SIZE_MM", "-5"),
    ],
)
def test_invalid_values_name_the_variable(var, raw):
    with pytest.raises(SettingsError, match=var):
        load_settings(env={var: raw})


def test_empty_string_counts_as_unset():
    settings = load_settings(env={"ABCAD_MAX_ITER": "", "ABCAD_TARGET_SIZE_MM": "  "})
    assert settings.max_iter == 3 and settings.target_size_mm is None


def test_unknown_dtype_falls_back_to_float16(caplog):
    settings = load_settings(env={"ABCAD_EMIT_DTYPE": "int8"})
    assert settings.emit_dtype == "float16"
    assert "ABCAD_EMIT_DTYPE" in caplog.text


def test_keyword_overrides_beat_the_environment(tmp_path):
    env = {"ABCAD_MAX_ITER": "5", "ABCAD_DEEP_AUDIT": "1", "ABCAD_TARGET_SIZE_MM": "40"}
    settings = load_settings(env=env, max_iter=2, deep_audit=False, target_size_mm=None)
    assert settings.max_iter == 2
    assert settings.deep_audit is False
    assert settings.target_size_mm is None  # None falls back to the default (off)
    typed = load_settings(env={}, repair_temperature_ladder=[0.2, 0.9], out_dir=tmp_path)
    assert typed.repair_temperature_ladder == (0.2, 0.9)
    assert typed.out_dir == str(tmp_path)


def test_invalid_or_unknown_overrides_raise():
    with pytest.raises(SettingsError, match="max_iter"):
        load_settings(env={}, max_iter="many")
    with pytest.raises(SettingsError, match="no_such_field"):
        load_settings(env={}, no_such_field=1)


def test_derived_paths(tmp_path):
    settings = load_settings(env={"ABCAD_OUT": str(tmp_path / "o")})
    paths = settings.paths
    assert paths.out_dir == str(tmp_path / "o")
    assert paths.runs_dir == str(tmp_path / "o" / "agent_runs")
    assert paths.tmp_dir == str(tmp_path / "o" / "agent_tmp")
    assert paths.debug_dir == str(tmp_path / "o" / "agent_debug")
    assert paths.handoff_path == str(tmp_path / "o" / "agent_tmp" / "generated_code.py")
    custom = load_settings(env={"ABCAD_OUT": str(tmp_path / "o"), "ABCAD_AGENT_DEBUG_DIR": "/x/d"})
    assert custom.paths.debug_dir == os.path.abspath("/x/d")


def test_snapshot_omits_the_api_key_and_is_plain_json():
    settings = load_settings(env={"ABCAD_LLM_API_KEY": "s3cret"})
    snapshot = settings.snapshot()
    assert "llm_api_key" not in snapshot
    assert "s3cret" not in repr(snapshot)
    assert "s3cret" not in repr(settings)  # the dataclass repr hides it too
    assert snapshot["package_version"]
    assert snapshot["repair_temperature_ladder"] == [0.1, 0.5, 0.8]
    for key in ("base_model", "lora_adapter", "embed_model", "text_model", "vlm_model"):
        assert key in snapshot


def test_to_env_round_trips_through_the_loader(tmp_path):
    original = load_settings(
        env={},
        out_dir=tmp_path,
        emit_seed=11,
        target_size_mm=58.0,
        text_corpora=[str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")],
        repair_temperature_ladder=(0.1, 0.4),
        blender_path=str(tmp_path / "blender"),
    )
    again = load_settings(env=original.to_env())
    for field in AgentSettings.__dataclass_fields__:
        if field in ("render_resolution", "render_samples", "default_prompt"):
            continue  # no environment variable; not needed by the Phase-1 child
        assert getattr(again, field) == getattr(original, field), field
