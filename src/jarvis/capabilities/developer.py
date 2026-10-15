from __future__ import annotations

import difflib
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class WorkspaceSecurityError(ValueError):
    """Raised when a path or operation escapes the declared workspace policy."""


@dataclass(frozen=True, slots=True)
class WorkspaceRoot:
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    path: str
    is_directory: bool
    size: int


@dataclass(frozen=True, slots=True)
class WorkspaceDocument:
    path: str
    content: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class TestRunResult:
    command: tuple[str, ...]
    cwd: str
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return not self.timed_out and self.returncode == 0


@dataclass(frozen=True, slots=True)
class ProjectCreationResult:
    path: str
    template: str
    files: tuple[str, ...]


class DeveloperWorkspace:
    """Bounded developer workspace with explicit creation and test operations."""

    ALLOWED_TEST_COMMANDS = frozenset(
        {
            ("python", "-m", "pytest", "-q"),
            ("npm", "test", "--", "--runInBand"),
        }
    )
    TEXT_EXTENSIONS = frozenset(
        {
            ".c",
            ".cc",
            ".cfg",
            ".cpp",
            ".css",
            ".csv",
            ".go",
            ".h",
            ".hpp",
            ".html",
            ".ini",
            ".java",
            ".js",
            ".json",
            ".jsx",
            ".md",
            ".mjs",
            ".py",
            ".rs",
            ".toml",
            ".ts",
            ".tsx",
            ".txt",
            ".xml",
            ".yaml",
            ".yml",
        }
    )
    _BLOCKED_EXACT = frozenset(
        {
            ".aws",
            ".azure",
            ".git",
            ".gnupg",
            ".netrc",
            ".npmrc",
            ".pypirc",
            ".ssh",
            "credentials",
            "credentials.json",
            "id_ed25519",
            "id_rsa",
            "secrets",
            "secrets.json",
        }
    )
    _BLOCKED_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".pem"})
    _WINDOWS_RESERVED = frozenset(
        {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
    )

    def __init__(
        self,
        roots: Mapping[str, Path] | Iterable[WorkspaceRoot],
        *,
        max_file_bytes: int = 1_000_000,
        max_results: int = 200,
    ) -> None:
        if max_file_bytes < 1 or max_results < 1:
            raise ValueError("Los límites del workspace deben ser positivos")
        declared = (
            tuple(WorkspaceRoot(name, Path(path)) for name, path in roots.items())
            if isinstance(roots, Mapping)
            else tuple(roots)
        )
        if not declared:
            raise ValueError("Debe declararse al menos una raíz de workspace")
        self.max_file_bytes = max_file_bytes
        self.max_results = max_results
        self._roots: dict[str, WorkspaceRoot] = {}
        for item in declared:
            name = item.name.strip()
            if not name or name in self._roots or any(char in name for char in "/\\\0"):
                raise ValueError("El nombre de la raíz no es válido o está duplicado")
            original = Path(item.path)
            if self._is_link_or_reparse(original):
                raise WorkspaceSecurityError("Una raíz no puede ser un enlace o reparse point")
            try:
                resolved = original.resolve(strict=True)
            except OSError as exc:
                raise WorkspaceSecurityError(f"La raíz {name!r} no existe") from exc
            if not resolved.is_dir():
                raise WorkspaceSecurityError(f"La raíz {name!r} no es una carpeta")
            self._roots[name] = WorkspaceRoot(name, resolved)

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return path.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        except OSError:
            return False

    @classmethod
    def _blocked_name(cls, name: str) -> bool:
        normalized = name.casefold()
        return (
            normalized == ".env"
            or normalized.startswith(".env.")
            or normalized in cls._BLOCKED_EXACT
            or Path(normalized).suffix in cls._BLOCKED_SUFFIXES
            or normalized.endswith(("credentials.json", "secrets.json"))
        )

    def roots(self) -> tuple[WorkspaceRoot, ...]:
        return tuple(self._roots.values())

    def _root(self, name: str) -> WorkspaceRoot:
        try:
            return self._roots[name]
        except KeyError as exc:
            raise WorkspaceSecurityError(f"La raíz {name!r} no está autorizada") from exc

    def _resolve(
        self,
        root_name: str,
        relative_path: str = "",
        *,
        directory: bool | None = None,
    ) -> Path:
        root = self._root(root_name).path
        relative = Path(relative_path or ".")
        if (
            relative.is_absolute()
            or bool(relative.anchor)
            or bool(relative.drive)
            or ".." in relative.parts
            or "\0" in str(relative)
        ):
            raise WorkspaceSecurityError("La ruta debe ser relativa a la raíz autorizada")
        current = root
        for part in relative.parts:
            if part in {"", "."}:
                continue
            if self._blocked_name(part):
                raise WorkspaceSecurityError("La ruta contiene credenciales o metadatos privados")
            current = current / part
            if current.exists() and self._is_link_or_reparse(current):
                raise WorkspaceSecurityError("No se permiten enlaces dentro del workspace")
        try:
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceSecurityError("La ruta solicitada no existe") from exc
        if not resolved.is_relative_to(root):
            raise WorkspaceSecurityError("La ruta escapa de la raíz autorizada")
        if directory is True and not resolved.is_dir():
            raise WorkspaceSecurityError("La ruta no es una carpeta")
        if directory is False and not resolved.is_file():
            raise WorkspaceSecurityError("La ruta no es un archivo")
        return resolved

    def directory(self, root_name: str, relative_path: str = "") -> Path:
        """Return a revalidated existing directory for a trusted downstream sandbox."""
        return self._resolve(root_name, relative_path, directory=True)

    @classmethod
    def _valid_new_part(cls, part: str) -> bool:
        normalized = part.casefold().rstrip(". ")
        return bool(
            part
            and part not in {".", ".."}
            and part == part.rstrip(". ")
            and not cls._blocked_name(part)
            and normalized not in cls._WINDOWS_RESERVED
            and not any(character in part for character in '<>:"/\\|?*\0\r\n\t')
        )

    def _new_path(self, root_name: str, relative_path: str) -> tuple[Path, Path]:
        root = self._root(root_name).path
        relative = Path(relative_path)
        if (
            not relative_path.strip()
            or len(relative_path) > 500
            or relative.is_absolute()
            or relative.anchor
            or relative.drive
            or len(relative.parts) > 8
            or any(not self._valid_new_part(part) for part in relative.parts)
        ):
            raise WorkspaceSecurityError("La nueva ruta no es válida dentro del workspace")
        current = root
        for part in relative.parts:
            current = current / part
            if current.exists() and self._is_link_or_reparse(current):
                raise WorkspaceSecurityError("No se permiten enlaces dentro del workspace")
        candidate = current.resolve(strict=False)
        if not candidate.is_relative_to(root):
            raise WorkspaceSecurityError("La ruta escapa de la raíz autorizada")
        return root, candidate

    def create_folder(self, root_name: str, relative_path: str) -> WorkspaceEntry:
        root, target = self._new_path(root_name, relative_path)
        if target.exists():
            if not target.is_dir():
                raise WorkspaceSecurityError("Ya existe un archivo con ese nombre")
            raise WorkspaceSecurityError("La carpeta ya existe")
        try:
            target.mkdir(parents=True, exist_ok=False)
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceSecurityError("No se pudo crear la carpeta") from exc
        if not resolved.is_relative_to(root) or self._is_link_or_reparse(resolved):
            raise WorkspaceSecurityError("La carpeta creada no superó la validación final")
        return WorkspaceEntry(self._relative(root, resolved), True, 0)

    def create_project(
        self,
        root_name: str,
        name: str,
        *,
        template: str = "basic",
        description: str = "",
    ) -> ProjectCreationResult:
        if not self._valid_new_part(name) or len(name) > 80:
            raise WorkspaceSecurityError("El nombre del proyecto no es válido")
        template = template.casefold().strip()
        if template not in {"basic", "python", "web"}:
            raise WorkspaceSecurityError("La plantilla debe ser basic, python o web")
        if len(description) > 1000 or "\0" in description:
            raise WorkspaceSecurityError("La descripción del proyecto no es válida")
        root, target = self._new_path(root_name, name)
        if target.exists():
            raise WorkspaceSecurityError("Ya existe una carpeta con ese nombre")
        title = name.replace("-", " ").replace("_", " ").strip().title()
        summary = description.strip() or "Proyecto creado por Jarvis."
        files: dict[str, str] = {
            "README.md": f"# {title}\n\n{summary}\n",
            ".gitignore": ".env\n.venv/\nnode_modules/\n__pycache__/\ndist/\nbuild/\n",
        }
        if template == "python":
            module = re.sub(r"[^a-z0-9_]", "_", name.casefold().replace("-", "_"))
            module = re.sub(r"_+", "_", module).strip("_") or "app"
            package_name = re.sub(r"[^a-z0-9._-]+", "-", name.casefold()).strip(".-_")
            package_name = package_name or "project"
            files.update(
                {
                    "pyproject.toml": (
                        "[project]\n"
                        f'name = "{package_name}"\n'
                        'version = "0.1.0"\n'
                        'requires-python = ">=3.12"\n\n'
                        '[tool.pytest.ini_options]\npythonpath = ["src"]\n'
                    ),
                    f"src/{module}/__init__.py": "",
                    "tests/__init__.py": "",
                }
            )
        elif template == "web":
            package_name = re.sub(r"[^a-z0-9-]", "-", name.casefold().replace("_", "-"))
            files.update(
                {
                    "package.json": (
                        "{\n"
                        f'  "name": "{package_name}",\n'
                        '  "version": "0.1.0",\n'
                        '  "private": true,\n'
                        '  "scripts": {"start": "npx vite"}\n'
                        "}\n"
                    ),
                    "index.html": (
                        '<!doctype html>\n<html lang="es"><head><meta charset="UTF-8">'
                        f'<title>{title}</title></head><body><main id="app"></main>'
                        '<script type="module" src="/src/main.js"></script></body></html>\n'
                    ),
                    "src/main.js": f'document.querySelector("#app").textContent = "{title}";\n',
                }
            )
        try:
            target.mkdir(parents=False, exist_ok=False)
            for relative_name, content in files.items():
                destination = target / Path(relative_name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8", newline="\n")
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceSecurityError(
                "No se pudo completar el proyecto; revisa la carpeta antes de reintentarlo"
            ) from exc
        if not resolved.is_relative_to(root) or self._is_link_or_reparse(resolved):
            raise WorkspaceSecurityError("El proyecto creado no superó la validación final")
        return ProjectCreationResult(self._relative(root, resolved), template, tuple(sorted(files)))

    def _safe_walk(self, root: Path, start: Path) -> Iterable[Path]:
        stack = [start]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            directories: list[Path] = []
            for child in children:
                if self._blocked_name(child.name) or self._is_link_or_reparse(child):
                    continue
                try:
                    resolved = child.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(root):
                    continue
                yield resolved
                if resolved.is_dir():
                    directories.append(resolved)
            stack.extend(reversed(directories))

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        return path.relative_to(root).as_posix()

    def list_files(
        self,
        root_name: str,
        relative_path: str = "",
        *,
        recursive: bool = False,
        limit: int | None = None,
    ) -> tuple[WorkspaceEntry, ...]:
        root = self._root(root_name).path
        start = self._resolve(root_name, relative_path, directory=True)
        safe_limit = min(limit or self.max_results, self.max_results)
        candidates = (
            self._safe_walk(root, start)
            if recursive
            else (
                child
                for child in sorted(start.iterdir(), key=lambda item: item.name.casefold())
                if not self._blocked_name(child.name)
                and not self._is_link_or_reparse(child)
                and child.resolve(strict=True).is_relative_to(root)
            )
        )
        entries: list[WorkspaceEntry] = []
        for path in candidates:
            try:
                is_directory = path.is_dir()
                size = 0 if is_directory else path.stat().st_size
            except OSError:
                continue
            entries.append(WorkspaceEntry(self._relative(root, path), is_directory, size))
            if len(entries) >= safe_limit:
                break
        return tuple(entries)

    def read(self, root_name: str, relative_path: str) -> WorkspaceDocument:
        root = self._root(root_name).path
        path = self._resolve(root_name, relative_path, directory=False)
        if path.suffix.casefold() not in self.TEXT_EXTENSIONS:
            raise WorkspaceSecurityError("El archivo no pertenece a la lista de texto segura")
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceSecurityError("El archivo supera el tamaño máximo permitido")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise WorkspaceSecurityError("El archivo no es texto UTF-8 legible") from exc
        return WorkspaceDocument(self._relative(root, path), content)

    def search(
        self,
        root_name: str,
        query: str,
        relative_path: str = "",
        *,
        limit: int | None = None,
    ) -> tuple[SearchMatch, ...]:
        needle = query.strip().casefold()
        if not needle or len(needle) > 200:
            raise ValueError("La búsqueda debe contener entre 1 y 200 caracteres")
        root = self._root(root_name).path
        safe_limit = min(limit or self.max_results, self.max_results)
        matches: list[SearchMatch] = []
        for entry in self.list_files(
            root_name,
            relative_path,
            recursive=True,
            limit=self.max_results,
        ):
            if entry.is_directory or Path(entry.path).suffix.casefold() not in self.TEXT_EXTENSIONS:
                continue
            if entry.size > self.max_file_bytes:
                continue
            try:
                document = self.read(root_name, entry.path)
            except WorkspaceSecurityError:
                continue
            for line_number, line in enumerate(document.content.splitlines(), start=1):
                if needle in line.casefold():
                    matches.append(
                        SearchMatch(
                            self._relative(root, self._resolve(root_name, entry.path)),
                            line_number,
                            " ".join(line.split())[:300],
                        )
                    )
                    if len(matches) >= safe_limit:
                        return tuple(matches)
        return tuple(matches)

    def diff(self, root_name: str, relative_path: str, proposed_content: str) -> str:
        if not isinstance(proposed_content, str):
            raise TypeError("El contenido propuesto debe ser texto")
        if len(proposed_content.encode("utf-8")) > self.max_file_bytes:
            raise WorkspaceSecurityError("El contenido propuesto supera el límite permitido")
        current = self.read(root_name, relative_path)
        diff_lines = difflib.unified_diff(
            current.content.splitlines(),
            proposed_content.splitlines(),
            fromfile=f"a/{current.path}",
            tofile=f"b/{current.path}",
            lineterm="",
        )
        return "\n".join(diff_lines)[:200_000]

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = {
            "APPDATA",
            "COMSPEC",
            "LOCALAPPDATA",
            "PATH",
            "PATHEXT",
            "PROGRAMFILES",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "WINDIR",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(
            {
                "CI": "1",
                "NO_COLOR": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            }
        )
        return environment

    def _run_process(
        self,
        command: tuple[str, ...],
        cwd: Path,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - exact allowlist, no shell
            list(command),
            cwd=str(cwd),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=self._safe_environment(),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    @staticmethod
    def _output(value: str | bytes | None) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return (value or "")[-20_000:]

    @classmethod
    def _trusted_command(
        cls,
        command: tuple[str, ...],
        workspace_root: Path,
    ) -> tuple[str, ...]:
        if command[0] == "python":
            candidate = Path(sys.executable)
        else:
            npm_name = "npm.cmd" if os.name == "nt" else "npm"
            discovered = shutil.which(npm_name)
            if not discovered:
                raise WorkspaceSecurityError(
                    "No encontr\u00e9 una instalaci\u00f3n confiable de npm"
                )
            candidate = Path(discovered)
        try:
            executable = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceSecurityError("El ejecutable de pruebas no es v\u00e1lido") from exc
        if not executable.is_absolute() or not executable.is_file():
            raise WorkspaceSecurityError("El ejecutable de pruebas no es v\u00e1lido")
        if command[0] == "npm" and executable.is_relative_to(workspace_root):
            raise WorkspaceSecurityError("npm no puede resolverse desde el propio workspace")
        return (str(executable), *command[1:])

    def run_tests(
        self,
        root_name: str,
        command: Sequence[str] | str,
        *,
        relative_cwd: str = "",
        timeout: float = 120.0,
    ) -> TestRunResult:
        argv = tuple(command.split()) if isinstance(command, str) else tuple(command)
        if argv not in self.ALLOWED_TEST_COMMANDS:
            raise WorkspaceSecurityError("El comando de pruebas no pertenece a la lista exacta")
        if not 1 <= timeout <= 300:
            raise ValueError("El timeout debe estar entre 1 y 300 segundos")
        cwd = self._resolve(root_name, relative_cwd, directory=True)
        root = self._root(root_name).path
        trusted_argv = self._trusted_command(argv, root)
        try:
            completed = self._run_process(trusted_argv, cwd, timeout)
            return TestRunResult(
                argv,
                self._relative(root, cwd) or ".",
                completed.returncode,
                self._output(completed.stdout),
                self._output(completed.stderr),
            )
        except subprocess.TimeoutExpired as exc:
            return TestRunResult(
                argv,
                self._relative(root, cwd) or ".",
                None,
                self._output(exc.stdout),
                self._output(exc.stderr),
                timed_out=True,
            )


__all__ = [
    "DeveloperWorkspace",
    "ProjectCreationResult",
    "SearchMatch",
    "TestRunResult",
    "WorkspaceDocument",
    "WorkspaceEntry",
    "WorkspaceRoot",
    "WorkspaceSecurityError",
]
