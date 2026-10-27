"""Consistent SQLite backups, encrypted for this Windows user, with verified restore."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from jarvis.services.mail_store import protect


class Recovery:
    def __init__(self, config):
        self.config = config
        self.folder = config.data_dir / "backups"
        self.lock = threading.Lock()
        self._verified_cache: dict[str, object] = {}

    def _source(self, name: str) -> Path:
        source = self.folder / name
        if (
            source.resolve().parent != self.folder.resolve()
            or source.suffix != ".jbackup"
            or not source.is_file()
        ):
            raise ValueError("Respaldo inválido")
        return source

    def _allowed_target(self, path: str) -> Path:
        target = self.config.project_root / path
        allowed = path == ".env" or (
            Path(path).parent == Path(".data")
            and (
                path.endswith(".sqlite3")
                or Path(path).name in {"preferences.json", "user_profile.json"}
            )
        )
        if not allowed or not target.resolve().is_relative_to(self.config.project_root.resolve()):
            raise ValueError("El respaldo contiene una ruta no permitida")
        return target

    def _validated_entries(self, source: Path) -> tuple[dict[Path, bytes], int]:
        try:
            decrypted = protect(source.read_bytes(), True)
            with zipfile.ZipFile(io.BytesIO(decrypted)) as archive:
                members = archive.infolist()
                names = [item.filename for item in members]
                if (
                    len(names) != len(set(names))
                    or "manifest.json" not in names
                    or len(names) > 64
                    or sum(item.file_size for item in members) > 256 * 1024 * 1024
                ):
                    raise ValueError("El respaldo contiene una estructura inválida")
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict) or set(names) != {*manifest, "manifest.json"}:
                    raise ValueError("El manifiesto del respaldo no coincide")
                entries: dict[Path, bytes] = {}
                with tempfile.TemporaryDirectory(prefix="jarvis-verify-") as temporary:
                    for path, digest in manifest.items():
                        if not isinstance(path, str) or not isinstance(digest, str):
                            raise ValueError("El manifiesto del respaldo es inválido")
                        target = self._allowed_target(path)
                        content = archive.read(path)
                        if hashlib.sha256(content).hexdigest() != digest:
                            raise ValueError("El respaldo no pasó la verificación")
                        if path.endswith(".sqlite3"):
                            copy = Path(temporary) / Path(path).name
                            copy.write_bytes(content)
                            database = sqlite3.connect(copy)
                            try:
                                if database.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                                    raise ValueError("Una base de datos del respaldo está dañada")
                            finally:
                                database.close()
                        entries[target] = content
        except (
            OSError,
            KeyError,
            RuntimeError,
            json.JSONDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            raise ValueError("No se pudo abrir o verificar el respaldo") from exc
        return entries, len(decrypted)

    def verify(self, name: str) -> dict[str, object]:
        source = self._source(name)
        entries, decrypted_bytes = self._validated_entries(source)
        result: dict[str, object] = {
            "name": source.name,
            "verified": True,
            "files": len(entries),
            "databases": sum(1 for path in entries if path.suffix == ".sqlite3"),
            "bytes": source.stat().st_size,
            "decrypted_bytes": decrypted_bytes,
            "created": source.stat().st_mtime,
            "verified_at": time.time(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        self._verified_cache = result
        return result

    def status(self):
        files = sorted(self.folder.glob("jarvis-*.jbackup"), reverse=True)
        try:
            supervisor = json.loads((self.config.data_dir / "supervisor.json").read_text())
            if time.time() - supervisor["updated"] > 120:
                supervisor["state"] = "offline"
        except (OSError, ValueError, KeyError):
            supervisor = {"state": "not-installed"}
        return {
            "supervisor": supervisor,
            "backups": [
                {"name": p.name, "bytes": p.stat().st_size, "created": p.stat().st_mtime}
                for p in files[:14]
            ],
            "encrypted": True,
            "same_windows_user_required": True,
            "latest_verification": (
                self._verified_cache
                if files and self._verified_cache.get("name") == files[0].name
                else None
            ),
        }

    def diagnostics(self):
        started = time.perf_counter()
        status = self.status()
        checks: list[dict[str, object]] = []
        databases = sorted(self.config.data_dir.glob("*.sqlite3"))
        for source in databases:
            check = "error"
            detail = "No se pudo abrir la base de datos"
            try:
                database = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
                try:
                    result = database.execute("PRAGMA quick_check").fetchone()[0]
                finally:
                    database.close()
                check = "ok" if result == "ok" else "error"
                detail = "Integridad SQLite verificada" if result == "ok" else str(result)[:160]
            except sqlite3.Error:
                pass
            checks.append(
                {
                    "id": "database:" + source.name,
                    "name": source.name,
                    "status": check,
                    "detail": detail,
                }
            )
        free = shutil.disk_usage(self.config.data_dir).free
        checks.append(
            {
                "id": "storage",
                "name": "Espacio de almacenamiento",
                "status": "warning" if free < 2 * 1024**3 else "ok",
                "detail": f"{free / 1024**3:.1f} GB disponibles",
            }
        )
        writable = os.access(self.config.data_dir, os.W_OK)
        checks.append(
            {
                "id": "data-directory",
                "name": "Carpeta de datos",
                "status": "ok" if writable else "error",
                "detail": "Disponible para respaldos" if writable else "Sin permiso de escritura",
            }
        )
        backups = status["backups"]
        if backups:
            latest = backups[0]
            try:
                verification = self.verify(str(latest["name"]))
                age_hours = max(0.0, (time.time() - float(latest["created"])) / 3600)
                backup_state = "warning" if age_hours > 48 else "ok"
                backup_detail = (
                    f"Copia cifrada verificada hace {age_hours:.1f} h · "
                    f"{verification['files']} archivos"
                )
            except ValueError as exc:
                backup_state, backup_detail = "error", str(exc)
        else:
            backup_state, backup_detail = "warning", "Todavía no existe un respaldo"
        checks.append(
            {
                "id": "backup",
                "name": "Último respaldo",
                "status": backup_state,
                "detail": backup_detail,
            }
        )
        supervisor = status["supervisor"]
        supervisor_state = str(supervisor.get("state", "not-installed"))
        checks.append(
            {
                "id": "supervisor",
                "name": "Supervisor de Jarvis",
                "status": "ok" if supervisor_state in {"ready", "starting"} else "warning",
                "detail": supervisor_state,
            }
        )
        overall = (
            "error"
            if any(item["status"] == "error" for item in checks)
            else "warning"
            if any(item["status"] == "warning" for item in checks)
            else "ok"
        )
        return {
            **self.status(),
            "status": overall,
            "checks": checks,
            "checked_at": time.time(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    def daily(self):
        files = self.status()["backups"]
        if not files or time.time() - files[0]["created"] >= 86400:
            self.backup()

    def backup(self):
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            entries = {}
            with tempfile.TemporaryDirectory(prefix="jarvis-backup-") as temporary:
                for source in self.config.data_dir.glob("*.sqlite3"):
                    target = Path(temporary) / source.name
                    with sqlite3.connect(source) as original, sqlite3.connect(target) as copy:
                        original.backup(copy)
                        if copy.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("No se pudo verificar la base de datos")
                    original.close()
                    copy.close()
                    entries[".data/" + source.name] = target.read_bytes()
                for source in [
                    self.config.project_root / ".env",
                    self.config.data_dir / "preferences.json",
                    self.config.user_profile_path,
                ]:
                    if source.is_file() and source.resolve().is_relative_to(
                        self.config.project_root.resolve()
                    ):
                        entries[source.relative_to(self.config.project_root).as_posix()] = (
                            source.read_bytes()
                        )
                manifest = {
                    name: hashlib.sha256(data).hexdigest() for name, data in entries.items()
                }
                content = io.BytesIO()
                with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
                    for name, data in entries.items():
                        archive.writestr(name, data)
                    archive.writestr("manifest.json", json.dumps(manifest))
                encrypted = protect(content.getvalue())
                destination = self.folder / ("jarvis-" + str(time.time_ns()) + ".jbackup")
                temporary_path = destination.with_suffix(".tmp")
                temporary_path.write_bytes(encrypted)
                temporary_path.replace(destination)
            for old in sorted(self.folder.glob("jarvis-*.jbackup"), reverse=True)[14:]:
                if old.resolve().parent == self.folder.resolve():
                    old.unlink()
            verification = self.verify(destination.name)
            return {"name": destination.name, "files": len(entries), **verification}

    def restore(self, name):
        """Caller must stop Jarvis and its supervisor first. No arbitrary zip paths."""
        source = self._source(name)
        entries, _decrypted_bytes = self._validated_entries(source)
        self.backup()
        # Stage all files before replacing any of them.
        for target, content in entries.items():
            target.with_suffix(target.suffix + ".restore").write_bytes(content)
        for target in entries:
            if target.suffix == ".sqlite3":
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(target) + suffix)
                    if sidecar.exists():
                        sidecar.unlink()
            target.with_suffix(target.suffix + ".restore").replace(target)
        return {"restored": len(entries)}
