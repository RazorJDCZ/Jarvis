from __future__ import annotations

import json
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class GameLibraryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GameInfo:
    game_id: str
    name: str
    platform: str
    launch_target: str
    install_path: str | None = None


class GameLibrary:
    """Reads manifests from caller-provided roots and never launches a process."""

    _MAX_MANIFEST_BYTES = 2 * 1024 * 1024
    _MAX_MANIFESTS = 5_000
    _VDF_PAIR = re.compile(r'"(?P<key>[^"\\]+)"\s+"(?P<value>(?:\\.|[^"\\])*)"')
    _EPIC_APP = re.compile(r"^[A-Za-z0-9._-]{1,200}$")

    def __init__(
        self,
        *,
        steam_roots: Iterable[Path] = (),
        epic_manifest_roots: Iterable[Path] = (),
    ) -> None:
        self.steam_roots = self._validate_roots(steam_roots, "Steam")
        self.epic_manifest_roots = self._validate_roots(epic_manifest_roots, "Epic")

    @staticmethod
    def _is_link_or_reparse(path: Path) -> bool:
        try:
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            return path.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        except OSError:
            return True

    @classmethod
    def _validate_roots(cls, roots: Iterable[Path], label: str) -> tuple[Path, ...]:
        validated: list[Path] = []
        for raw_root in roots:
            path = Path(raw_root)
            if cls._is_link_or_reparse(path):
                raise GameLibraryError(f"La raíz de {label} no puede ser un enlace")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise GameLibraryError(f"La raíz de {label} no existe") from exc
            if not resolved.is_dir():
                raise GameLibraryError(f"La raíz de {label} no es una carpeta")
            if resolved not in validated:
                validated.append(resolved)
        return tuple(validated)

    @classmethod
    def _read_small_text(cls, path: Path, root: Path) -> str | None:
        try:
            resolved = path.resolve(strict=True)
            if (
                cls._is_link_or_reparse(path)
                or not resolved.is_relative_to(root)
                or not resolved.is_file()
                or resolved.stat().st_size > cls._MAX_MANIFEST_BYTES
            ):
                return None
            return resolved.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return None

    @staticmethod
    def _unescape_vdf(value: str) -> str:
        return value.replace(r"\"", '"').replace(r"\\", "\\")

    @classmethod
    def _steam_game(cls, manifest: Path, root: Path) -> GameInfo | None:
        content = cls._read_small_text(manifest, root)
        if content is None:
            return None
        values = {
            match.group("key").casefold(): cls._unescape_vdf(match.group("value"))
            for match in cls._VDF_PAIR.finditer(content)
        }
        app_id = values.get("appid", "").strip()
        name = values.get("name", "").strip()
        install_dir = values.get("installdir", "").strip()
        filename_id = re.fullmatch(r"appmanifest_(\d{1,12})\.acf", manifest.name.casefold())
        if (
            not app_id.isdigit()
            or len(app_id) > 12
            or filename_id is None
            or filename_id.group(1) != app_id
            or not 1 <= len(name) <= 300
            or any(character in name for character in "\r\n\0")
        ):
            return None
        install_path: str | None = None
        if (
            install_dir
            and not Path(install_dir).is_absolute()
            and ".." not in Path(install_dir).parts
        ):
            candidate = (root / "steamapps" / "common" / install_dir).resolve()
            if candidate.is_relative_to(root):
                install_path = str(candidate)
        return GameInfo(
            game_id=app_id,
            name=name,
            platform="steam",
            launch_target=f"steam://rungameid/{app_id}",
            install_path=install_path,
        )

    @classmethod
    def _safe_walk_items(cls, root: Path) -> Iterable[Path]:
        stack = [root]
        yielded = 0
        while stack and yielded < cls._MAX_MANIFESTS:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            directories: list[Path] = []
            for child in children:
                if cls._is_link_or_reparse(child):
                    continue
                try:
                    resolved = child.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(root):
                    continue
                if resolved.is_dir():
                    directories.append(resolved)
                elif resolved.suffix.casefold() == ".item":
                    yielded += 1
                    yield resolved
                    if yielded >= cls._MAX_MANIFESTS:
                        return
            stack.extend(reversed(directories))

    @classmethod
    def _epic_game(cls, manifest: Path, root: Path) -> GameInfo | None:
        content = cls._read_small_text(manifest, root)
        if content is None:
            return None
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict) or payload.get("bIsIncompleteInstall") is True:
            return None
        app_name = payload.get("AppName")
        display_name = payload.get("DisplayName")
        if (
            not isinstance(app_name, str)
            or cls._EPIC_APP.fullmatch(app_name) is None
            or not isinstance(display_name, str)
            or not 1 <= len(display_name.strip()) <= 300
            or any(character in display_name for character in "\r\n\0")
        ):
            return None
        encoded = quote(app_name, safe="")
        return GameInfo(
            game_id=app_name,
            name=display_name.strip(),
            platform="epic",
            launch_target=(f"com.epicgames.launcher://apps/{encoded}?action=launch&silent=true"),
        )

    def inventory(self) -> tuple[GameInfo, ...]:
        games: dict[tuple[str, str], GameInfo] = {}
        for root in self.steam_roots:
            steamapps = root / "steamapps"
            if not steamapps.is_dir() or self._is_link_or_reparse(steamapps):
                continue
            for manifest in sorted(steamapps.glob("appmanifest_*.acf"))[: self._MAX_MANIFESTS]:
                game = self._steam_game(manifest, root)
                if game is not None:
                    games[(game.platform, game.game_id)] = game
        for root in self.epic_manifest_roots:
            for manifest in self._safe_walk_items(root):
                game = self._epic_game(manifest, root)
                if game is not None:
                    games[(game.platform, game.game_id)] = game
        return tuple(sorted(games.values(), key=lambda item: (item.name.casefold(), item.platform)))

    def get(self, game_id: str, *, platform: str | None = None) -> GameInfo | None:
        normalized_platform = platform.strip().casefold() if platform else None
        matches = [
            game
            for game in self.inventory()
            if game.game_id == game_id
            and (normalized_platform is None or game.platform == normalized_platform)
        ]
        return matches[0] if len(matches) == 1 else None

    def launch_target(self, game_id: str, *, platform: str | None = None) -> str | None:
        game = self.get(game_id, platform=platform)
        return game.launch_target if game is not None else None


__all__ = ["GameInfo", "GameLibrary", "GameLibraryError"]
