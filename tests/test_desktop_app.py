import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = PROJECT_ROOT / "desktop"


def test_desktop_shell_uses_existing_private_service() -> None:
    source = (DESKTOP_ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    assert 'const JARVIS_URL: &str = "http://127.0.0.1:8765"' in source
    assert "supervise_assistant.py" in source
    assert "WebviewUrl::App" in source
    assert "allowed_navigation" in source
    assert "NewWindowResponse::Deny" in source
    assert "gmail" not in source.casefold()
    assert "token" not in source.casefold()
    assert "supervisor.shutdown" in source
    assert "Cerrar Jarvis completamente" in source
    assert "mantener el núcleo en segundo plano" in source


def test_desktop_shell_has_minimal_local_capability() -> None:
    capability = json.loads(
        (DESKTOP_ROOT / "src-tauri" / "capabilities" / "default.json").read_text(
            encoding="utf-8"
        )
    )
    assert capability["windows"] == ["main"]
    assert capability["permissions"] == ["core:default"]


def test_desktop_loader_contains_no_inline_script_or_remote_assets() -> None:
    loader = (DESKTOP_ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert '<script src="loader.js" defer></script>' in loader
    assert "https://" not in loader
    assert "<script>" not in loader


def test_tauri_configuration_does_not_bundle_private_data() -> None:
    config = json.loads(
        (DESKTOP_ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert config["identifier"] == "com.juandi.jarvis.desktop"
    assert config["build"]["frontendDist"] == "../ui"
    assert config["app"]["windows"] == []
    serialized = json.dumps(config).casefold()
    assert ".env" not in serialized
    assert ".data" not in serialized
    assert "token" not in serialized


def test_supervisor_supports_a_graceful_desktop_shutdown() -> None:
    supervisor = (PROJECT_ROOT / "scripts" / "supervise_assistant.py").read_text(
        encoding="utf-8"
    )
    server = (PROJECT_ROOT / "src" / "jarvis" / "main.py").read_text(encoding="utf-8")
    assert 'SUPERVISOR_SHUTDOWN = "supervisor.shutdown"' in supervisor
    assert 'SERVER_SHUTDOWN = "server.shutdown"' in supervisor
    assert "close_for_desktop_request" in supervisor
    assert 'settings.data_dir / "server.shutdown"' in server
    assert "server.should_exit = True" in server
