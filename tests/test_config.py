from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.config import Settings, _env_bool, _env_float, _env_int
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
    assert settings.stt_model_reference == "custom"
    assert settings.data_dir == tmp_path / ".data"


def test_ipv6_loopback_origin_uses_brackets() -> None:
    assert http_origin("::1", 8765) == "http://[::1]:8765"
