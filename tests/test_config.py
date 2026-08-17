from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import (
    Settings,
    _env_bool,
    _env_float,
    _env_int,
    build_private_person_prompt,
    build_self_analysis_prompt,
    build_system_prompt,
)
from jarvis.main import http_origin


def test_invalid_numeric_environment_values_use_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROKEN_INT", "nope")
    monkeypatch.setenv("BROKEN_FLOAT", "nope")

    assert _env_int("BROKEN_INT", 12) == 12
    assert _env_float("BROKEN_FLOAT", 1.5) == 1.5


@pytest.mark.parametrize("value", ["1", "true", "YES", "on", "sí"])
def test_boolean_environment_accepts_explicit_true_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("BOOL_VALUE", value)

    assert _env_bool("BOOL_VALUE", False) is True


def test_boolean_environment_defaults_and_rejects_other_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOL_VALUE", raising=False)
    assert _env_bool("BOOL_VALUE", True) is True

    monkeypatch.setenv("BOOL_VALUE", "definitely")
    assert _env_bool("BOOL_VALUE", True) is False


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "jarvis.example"])
def test_stage_one_rejects_non_loopback_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        Settings(host=host)


def test_model_paths_are_kept_inside_project_when_relative(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path, stt_model="custom")

    assert settings.piper_model == tmp_path / "models/piper/es_ES-sharvard-medium.onnx"
    assert settings.kokoro_model == tmp_path / "models/kokoro/kokoro-v1.0.onnx"
    assert settings.kokoro_voices == tmp_path / "models/kokoro/voices-v1.0.bin"
    assert settings.stt_model_reference == "custom"
    assert settings.data_dir == tmp_path / ".data"
    assert settings.user_profile_path == tmp_path / ".data" / "user_profile.json"
    assert settings.memory_path == tmp_path / ".data" / "memory.sqlite3"


def test_ipv6_loopback_origin_uses_brackets() -> None:
    assert http_origin("::1", 8765) == "http://[::1]:8765"


@pytest.mark.parametrize("rounds", [0, 5])
def test_agent_round_limit_is_strictly_bounded(rounds: int) -> None:
    with pytest.raises(ValueError, match="rondas"):
        Settings(agent_max_rounds=rounds)


@pytest.mark.parametrize("seconds", [29, 601])
def test_deep_analysis_confirmation_window_is_bounded(seconds: int) -> None:
    with pytest.raises(ValueError, match="análisis"):
        Settings(deep_analysis_confirmation_seconds=seconds)


@pytest.mark.parametrize(
    "url",
    [
        "http://appa.example/api",
        "ftp://localhost/api",
        "https://user:secret@appa.example/api",
        "https://appa.example/api?token=secret",
    ],
)
def test_appa_connector_configuration_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError, match="Appa"):
        Settings(appa_url=url)


def test_appa_connector_allows_https_and_loopback() -> None:
    assert Settings(appa_url="https://appa.example/api").appa_url.endswith("/api")
    assert Settings(appa_url="http://127.0.0.1:9000/api").appa_url.startswith("http://")


def test_appa_bridge_is_discovered_from_current_local_app_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = Settings(
        project_root=tmp_path,
        appa_auto_discover=True,
        appa_bridge_config="",
    )

    assert settings.appa_bridge_config_path == tmp_path / "Appa" / "jarvis-bridge.json"
    assert settings.appa_database_marker_path == tmp_path / "Appa" / "appa.db"


def test_appa_bridge_auto_discovery_can_be_disabled(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        appa_auto_discover=False,
        appa_bridge_config="",
    )

    assert settings.appa_bridge_config_path is None
    assert settings.appa_database_marker_path is None


def test_personality_prompt_separates_profile_memory_recent_dialogue_and_evidence() -> None:
    prompt = build_system_prompt(
        profile_context="Juandi vive en Quito.",
        memory_context="Le gusta el ukelele.",
        recent_context="Juandi: Estoy creando Jarvis.",
        verification_context="Fuente: Open-Meteo.",
    )

    assert "gentil, servicial, sereno" in prompt
    assert "una sola pregunta puntual" in prompt
    assert "<RECUERDOS_LOCALES>" in prompt
    assert "<CONVERSACION_RECIENTE>" in prompt
    assert "<EVIDENCIA_VERIFICADA>" in prompt
    assert "notas de contexto, no un guion" in prompt


def test_deep_analysis_prompt_expands_quality_without_exposing_hidden_reasoning() -> None:
    prompt = build_system_prompt(
        profile_context="Washo es un amigo tranquilo y atento.",
        deep_analysis=True,
    )

    assert "MODO DE ANÁLISIS PROFUNDO" in prompt
    assert "seis y diez párrafos" in prompt
    assert "si los datos son escasos" in prompt
    assert "No encadenes una inferencia" in prompt
    assert "No muestres razonamiento interno" in prompt
    assert "apuntes de referencia, no texto para copiar" in prompt


def test_private_person_prompt_places_strict_evidence_limits_last() -> None:
    prompt = build_private_person_prompt("Washo es tranquilo.", deep_analysis=True)

    assert "exactamente cuatro párrafos y entre 220 y 340 palabras" in prompt
    assert prompt.endswith("</EVIDENCIA_PERSONAL_PRIVADA>")
    assert "No conviertas una carrera o afición en personalidad" in prompt
    assert "Una aclaración sobre un apodo solo se aplica" in prompt
    assert "Washo es tranquilo" in prompt


def test_private_person_factual_and_normal_analysis_have_distinct_limits() -> None:
    factual = build_private_person_prompt("Emi es su mejor amiga.")
    analytical = build_private_person_prompt(
        "Emi es su mejor amiga.",
        analytical=True,
    )

    assert "no incluyas ninguna inferencia" in factual
    assert "Habla directamente con Juan Diego en segunda persona" in factual
    assert "Nunca traslades apodos" in factual
    assert "Conserva exactamente el estado académico" in factual
    assert "Respeta el género explícito" in factual
    assert "máximo una impresión moderada" in analytical
    assert "exactamente cuatro párrafos" not in factual
    assert "exactamente cuatro párrafos" not in analytical


def test_self_analysis_prompt_requires_synthesis_and_bounded_inference() -> None:
    normal = build_self_analysis_prompt(
        "[PROYECTOS] Desarrolla Jarvis.\n[OBJETIVOS] Quiere graduarse."
    )
    deep = build_self_analysis_prompt(
        "[PROYECTOS] Desarrolla Jarvis.\n[OBJETIVOS] Quiere graduarse.",
        deep_analysis=True,
    )

    assert "EVIDENCIA_PERSONAL_PROPIA" in normal
    assert "No recites el perfil" in normal
    assert "seis a nueve oraciones" in normal
    assert "No diagnostiques salud mental" in normal
    assert "no prueban por sí solos confianza" in normal
    assert "No calcules la fecha de graduación" in normal
    assert "entre cinco y siete párrafos" in deep
    assert "500 y 750 palabras" in deep
