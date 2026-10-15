"""Consistent SQLite backups, encrypted for this Windows user, with verified restore."""

from __future__ import annotations

import hashlib
import io
import json
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
            return {"name": destination.name, "files": len(entries)}

    def restore(self, name):
        """Caller must stop Jarvis and its supervisor first. No arbitrary zip paths."""
        source = self.folder / name
        if source.resolve().parent != self.folder.resolve() or source.suffix != ".jbackup":
            raise ValueError("Respaldo inválido")
        with zipfile.ZipFile(io.BytesIO(protect(source.read_bytes(), True))) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            entries = {}
            for path, digest in manifest.items():
                target = self.config.project_root / path
                allowed = path == ".env" or (
                    Path(path).parent == Path(".data")
                    and (
                        path.endswith(".sqlite3")
                        or Path(path).name in {"preferences.json", "user_profile.json"}
                    )
                )
                if not allowed or not target.resolve().is_relative_to(
                    self.config.project_root.resolve()
                ):
                    raise ValueError("El respaldo contiene una ruta no permitida")
                content = archive.read(path)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError("El respaldo no pasó la verificación")
                entries[target] = content
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
