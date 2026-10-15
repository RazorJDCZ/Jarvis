"""Recover only the Jarvis process owned by this supervisor; never kill unrelated servers."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from jarvis.capabilities.connectors import ConnectorError, load_appa_bridge_descriptor
from jarvis.config import Settings


def stop_owned(child):
    if child is None or child.poll() is not None:
        return
    if os.name == "nt":
        # The venv redirector has a Python child; terminate the owned tree together.
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
            check=False,
        )
    else:
        child.terminate()
    try:
        child.wait(timeout=15)
    except subprocess.TimeoutExpired:
        child.kill()


def appa_executable(config: Settings) -> Path | None:
    configured = os.getenv("JARVIS_APPA_EXECUTABLE", "").strip()
    candidates = []
    if configured:
        path = Path(configured)
        if path.is_absolute():
            candidates.append(path)
    candidates.extend(
        (
            Path.home() / "Desktop" / "Appa Jarvis.exe",
            config.project_root.parent / "appa" / "src-tauri" / "target" / "release" / "appa.exe",
        )
    )
    return next((path for path in candidates if path.is_file()), None)


def appa_health(config: Settings, client: httpx.Client) -> tuple[bool, bool]:
    path = config.appa_bridge_config_path
    installed = bool(
        (path is not None and path.is_file())
        or (
            config.appa_database_marker_path is not None
            and config.appa_database_marker_path.is_file()
        )
    )
    if path is None or not path.is_file():
        return installed, False
    try:
        descriptor = load_appa_bridge_descriptor(path)
        response = client.get(
            descriptor.base_url + "/health",
            headers={"Authorization": f"Bearer {descriptor.token}"},
        )
        payload = response.json() if response.is_success else {}
        return installed, bool(
            payload.get("status") == "ok" and payload.get("service") == "appa-jarvis-bridge"
        )
    except (ConnectorError, httpx.HTTPError, ValueError):
        return installed, False


def main():
    config = Settings()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    # Keep a loopback socket open so a second login/start cannot duplicate the supervisor.
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 18765))
        lock.listen(1)
    except OSError:
        return
    child = None
    appa_child = None
    appa_last_launch = 0.0
    failed = 0
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    status = config.data_dir / "supervisor.json"
    paused = config.data_dir / "supervisor.pause"
    with httpx.Client(timeout=5, trust_env=False) as client:
        while True:
            if paused.exists():
                if child and child.poll() is None:
                    stop_owned(child)
                child = None
                status.write_text(json.dumps({"state": "paused", "updated": time.time()}))
                time.sleep(10)
                continue
            try:
                response = client.get(f"http://127.0.0.1:{config.port}/api/health")
                healthy = response.is_success
            except httpx.HTTPError:
                healthy = False
            if healthy:
                failed = 0
            else:
                failed += 1
                if child and child.poll() is None and failed >= 4:
                    stop_owned(child)
                    child = None
                if (child is None or child.poll() is not None) and failed >= 2:
                    # Do not launch over an unrelated process occupying the configured port.
                    with socket.socket() as probe:
                        occupied = probe.connect_ex(("127.0.0.1", config.port)) == 0
                    if not occupied:
                        log = config.data_dir / "supervised-server.log"
                        if log.exists() and log.stat().st_size > 5_000_000:
                            log.replace(log.with_suffix(".previous.log"))
                        with log.open("ab") as output:
                            child = subprocess.Popen(
                                [sys.executable, "-m", "jarvis.main"],
                                cwd=config.project_root,
                                stdout=output,
                                stderr=output,
                                creationflags=flags,
                            )
                        failed = 0
            appa_installed, appa_ready = appa_health(config, client)
            if appa_installed and not appa_ready and time.monotonic() - appa_last_launch >= 60:
                executable = appa_executable(config)
                if executable is not None:
                    with socket.socket() as probe:
                        appa_port_occupied = probe.connect_ex(("127.0.0.1", 47651)) == 0
                    if not appa_port_occupied:
                        appa_child = subprocess.Popen(
                            [str(executable)],
                            cwd=executable.parent,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=flags,
                        )
                        appa_last_launch = time.monotonic()
            # Ollama is independent and optional, used only for local semantic embeddings.
            ollama_required = config.semantic_enabled
            if ollama_required:
                try:
                    client.get(config.ollama_url + "/api/tags").raise_for_status()
                except httpx.HTTPError:
                    executable = config.project_root / ".tools" / "ollama" / "ollama.exe"
                    if (
                        config.ollama_url in {"http://127.0.0.1:11434", "http://localhost:11434"}
                        and executable.exists()
                    ):
                        with socket.socket() as probe:
                            occupied = probe.connect_ex(("127.0.0.1", 11434)) == 0
                        if not occupied:
                            env = {
                                **os.environ,
                                "OLLAMA_MODELS": str(config.project_root / "models" / "ollama"),
                            }
                            subprocess.Popen(
                                [str(executable), "serve"],
                                env=env,
                                cwd=executable.parent,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=flags,
                            )
            status.write_text(
                json.dumps(
                    {
                        "state": "ready" if healthy else "recovering",
                        "updated": time.time(),
                        "pid": child.pid if child else None,
                        "appa": "ready"
                        if appa_ready
                        else ("recovering" if appa_installed else "not-installed"),
                        "appa_pid": (
                            appa_child.pid
                            if appa_child is not None and appa_child.poll() is None
                            else None
                        ),
                    }
                )
            )
            time.sleep(20)


if __name__ == "__main__":
    main()
