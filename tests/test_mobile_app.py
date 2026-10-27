from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "mobile" / "android" / "app"


def test_android_shell_waits_for_real_microphone_and_authentication_state() -> None:
    source = (
        ANDROID / "src" / "main" / "java" / "com" / "juandi" / "jarvis" / "MainActivity.java"
    ).read_text(encoding="utf-8")

    assert 'addJavascriptInterface(new NativeBridge(), "JarvisNative")' in source
    assert "webConnectionReady" in source
    assert "pendingVoiceSubmit" in source
    assert '"recording".equals(voiceState)' in source
    assert "waitForAmbientStop" in source
    assert "Desbloquea Jarvis con tu biometría" in source


def test_android_ambient_voice_stops_cleanly_when_session_expires() -> None:
    source = (
        ANDROID
        / "src"
        / "main"
        / "java"
        / "com"
        / "juandi"
        / "jarvis"
        / "AmbientVoiceService.java"
    ).read_text(encoding="utf-8")

    assert "VoiceRequestException" in source
    assert "error.statusCode == 401 || error.statusCode == 403" in source
    assert "showProblemNotification" in source
    assert "Abre Jarvis y desbloquéalo con tu biometría" in source


def test_android_release_and_web_cache_versions_are_current() -> None:
    gradle = (ANDROID / "build.gradle.kts").read_text(encoding="utf-8")
    manifest = (ANDROID / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    app = (ROOT / "src" / "jarvis" / "web" / "app.js").read_text(encoding="utf-8")
    worker = (ROOT / "src" / "jarvis" / "web" / "service-worker.js").read_text(
        encoding="utf-8"
    )

    assert "versionCode = 6" in gradle
    assert 'versionName = "1.3.1"' in gradle
    assert "android.permission.MODIFY_AUDIO_SETTINGS" in manifest
    assert "syncNativeConnectionState" in app
    assert 'notifyNative("onVoiceState", "recording"' in app
    assert "jarvis-assistant-interface-v32" in worker
