"""Bounded, read-only discovery of files stored on the local computer."""

from __future__ import annotations

import ctypes
import heapq
import os
import re
import stat
import time
import unicodedata
from collections import deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


@dataclass(frozen=True, slots=True)
class FileSearchResult:
    name: str
    path: str
    extension: str
    size: int
    modified_at: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class ComputerFileSearch:
    """Locate file names without opening, changing, indexing or deleting any file.

    The scanner deliberately avoids reparse points and noisy system/application trees.
    A time and directory budget keeps a request from monopolising the assistant on large
    disks. Search results contain metadata only; file contents are never read here.
    """

    _SKIPPED_DIRECTORIES = frozenset(
        {
            "$recycle.bin",
            ".git",
            ".hg",
            ".svn",
            ".tox",
            ".venv",
            "__pycache__",
            "appdata",
            "application data",
            "cache",
            "inetcache",
            "msocache",
            "node_modules",
            "packages",
            "program files",
            "program files (x86)",
            "programdata",
            "recovery",
            "system volume information",
            "temp",
            "tmp",
            "windows",
            "windows.old",
        }
    )
    _QUERY_FILLERS = frozenset(
        {
            "archivo",
            "archivos",
            "computador",
            "computadora",
            "documento",
            "documentos",
            "equipo",
            "llamado",
            "llamada",
            "llamados",
            "llamadas",
            "pc",
            "sobre",
        }
    )

    def __init__(
        self,
        roots: Iterable[Path] | None = None,
        *,
        timeout_seconds: float = 5.0,
        max_directories: int = 60_000,
    ) -> None:
        candidates = tuple(roots) if roots is not None else self.default_roots()
        self.roots = self._deduplicate_roots(candidates)
        self.timeout_seconds = max(0.25, min(float(timeout_seconds), 30.0))
        self.max_directories = max(100, min(int(max_directories), 500_000))

    @classmethod
    def default_roots(cls) -> tuple[Path, ...]:
        roots: list[Path] = []
        profile = os.getenv("USERPROFILE", "").strip()
        if profile:
            roots.append(Path(profile))
        else:
            roots.append(Path.home())
        if os.name == "nt":
            try:
                drives = ctypes.windll.kernel32.GetLogicalDrives()
                get_type = ctypes.windll.kernel32.GetDriveTypeW
                for index in range(26):
                    if not drives & (1 << index):
                        continue
                    root = f"{chr(ord('A') + index)}:\\"
                    # DRIVE_FIXED (3) and DRIVE_REMOVABLE (2) are local media. Network
                    # shares are intentionally excluded from a "mi computadora" search.
                    if get_type(root) in {2, 3}:
                        roots.append(Path(root))
            except (AttributeError, OSError):
                pass
        return cls._deduplicate_roots(roots)

    @staticmethod
    def _deduplicate_roots(candidates: Iterable[Path]) -> tuple[Path, ...]:
        resolved: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            try:
                path = Path(candidate).expanduser().absolute()
                if not path.exists() or not path.is_dir():
                    continue
                key = os.path.normcase(str(path.resolve()))
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            resolved.append(path)
        # Prefer broad drive roots before nested folders to avoid scanning twice.
        resolved.sort(key=lambda item: (len(item.parts), str(item).casefold()))
        result: list[Path] = []
        for candidate in resolved:
            if any(
                candidate == root or root in candidate.parents
                for root in result
            ):
                continue
            result.append(candidate)
        return tuple(result)

    @staticmethod
    def _is_reparse_or_link(entry: os.DirEntry[str]) -> bool:
        try:
            information = entry.stat(follow_symlinks=False)
        except OSError:
            return True
        return entry.is_symlink() or bool(
            getattr(information, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )

    @classmethod
    def _terms(cls, query: str) -> tuple[str, tuple[str, ...]]:
        phrase = _normalized(query)
        terms = tuple(
            dict.fromkeys(
                term
                for term in phrase.split()
                if term not in cls._QUERY_FILLERS and len(term) >= 2
            )
        )
        return " ".join(terms), terms

    @staticmethod
    def _score(name: str, path: str, phrase: str, terms: tuple[str, ...], modified: float) -> float:
        normalized_name = _normalized(name)
        stem = _normalized(Path(name).stem)
        normalized_path = _normalized(path)
        score = 0.0
        if phrase == stem:
            score += 70
        elif phrase == normalized_name:
            score += 65
        elif phrase and phrase in stem:
            score += 45
        elif phrase and phrase in normalized_name:
            score += 38
        matched_name = sum(term in normalized_name for term in terms)
        matched_path = sum(term in normalized_path for term in terms)
        score += matched_name * 12 + (matched_path - matched_name) * 3
        if matched_name == len(terms):
            score += 18
        elif matched_path == len(terms):
            score += 8
        try:
            age_days = max(0.0, (time.time() - modified) / 86_400)
            score += max(0.0, 4.0 - min(age_days, 365.0) / 100.0)
        except (TypeError, ValueError):
            pass
        return score

    def search(self, query: str, *, limit: int = 20) -> dict[str, object]:
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("La búsqueda de archivos debe contener entre 1 y 300 caracteres.")
        phrase, terms = self._terms(query)
        if not terms:
            raise ValueError("Indica parte del nombre o tipo del archivo que quieres encontrar.")
        safe_limit = max(1, min(int(limit), 50))
        deadline = time.monotonic() + self.timeout_seconds
        queue = deque(self.roots)
        heap: list[tuple[float, int, FileSearchResult]] = []
        scanned_directories = 0
        scanned_files = 0
        denied = 0
        sequence = 0
        truncated = False

        while queue:
            if time.monotonic() >= deadline or scanned_directories >= self.max_directories:
                truncated = True
                break
            directory = queue.popleft()
            scanned_directories += 1
            try:
                iterator = os.scandir(directory)
            except (OSError, PermissionError):
                denied += 1
                continue
            try:
                with iterator:
                    for entry in iterator:
                        if scanned_files % 256 == 0 and time.monotonic() >= deadline:
                            truncated = True
                            break
                        try:
                            if self._is_reparse_or_link(entry):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() not in self._SKIPPED_DIRECTORIES:
                                    queue.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            scanned_files += 1
                            normalized_path = _normalized(entry.path)
                            if not all(term in normalized_path for term in terms):
                                continue
                            information = entry.stat(follow_symlinks=False)
                            score = self._score(
                                entry.name,
                                entry.path,
                                phrase,
                                terms,
                                information.st_mtime,
                            )
                            item = FileSearchResult(
                                name=entry.name,
                                path=str(Path(entry.path).absolute()),
                                extension=Path(entry.name).suffix.casefold(),
                                size=max(0, int(information.st_size)),
                                modified_at=datetime.fromtimestamp(
                                    information.st_mtime, UTC
                                ).isoformat(),
                                score=round(score, 2),
                            )
                            sequence += 1
                            ranked = (score, sequence, item)
                            if len(heap) < safe_limit:
                                heapq.heappush(heap, ranked)
                            elif ranked[:2] > heap[0][:2]:
                                heapq.heapreplace(heap, ranked)
                        except (OSError, PermissionError, ValueError):
                            denied += 1
                    if truncated:
                        break
            except (OSError, PermissionError):
                denied += 1

        ordered = [item for _score, _sequence, item in sorted(heap, reverse=True)]
        return {
            "query": query.strip(),
            "items": [item.as_dict() for item in ordered],
            "count": len(ordered),
            "scanned_files": scanned_files,
            "scanned_directories": scanned_directories,
            "unreadable_locations": denied,
            "truncated": truncated,
            "read_only": True,
            "roots": [str(root) for root in self.roots],
        }
