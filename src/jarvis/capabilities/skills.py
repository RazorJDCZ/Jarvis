from __future__ import annotations

import json
import math
import re
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.actions.models import (
    ActionName,
    ActionPlan,
    ActionSource,
    ActionWorkflowPlan,
)


class SkillValidationError(ValueError):
    """Raised when a declarative skill cannot be trusted."""


DEFAULT_SKILL_ACTIONS = frozenset(
    {
        ActionName.APP_OPEN,
        ActionName.APP_LIST,
        ActionName.BROWSER_OPEN,
        ActionName.BROWSER_SEARCH,
        ActionName.BROWSER_BACK,
        ActionName.BROWSER_FORWARD,
        ActionName.BROWSER_REFRESH,
        ActionName.BROWSER_NEW_TAB,
        ActionName.BROWSER_LIST_TABS,
        ActionName.BROWSER_SWITCH_TAB,
        ActionName.BROWSER_CLOSE_TAB,
        ActionName.BROWSER_READ,
        ActionName.VOLUME_SET,
        ActionName.VOLUME_CHANGE,
        ActionName.VOLUME_MUTE,
        ActionName.VOLUME_GET,
        ActionName.MEDIA_PLAY_PAUSE,
        ActionName.MEDIA_NEXT,
        ActionName.MEDIA_PREVIOUS,
        ActionName.MEDIA_STOP,
        ActionName.WINDOW_LIST,
        ActionName.WINDOW_FOCUS,
        ActionName.WINDOW_MINIMIZE,
        ActionName.WINDOW_MAXIMIZE,
        ActionName.WINDOW_RESTORE,
        ActionName.WINDOW_CURRENT,
        ActionName.SCREEN_LIST,
        ActionName.SCREEN_DESCRIBE,
        ActionName.SCREEN_ASK,
        ActionName.SCREEN_FIND,
        ActionName.DESKTOP_SHOW,
        ActionName.SYSTEM_STATUS,
        ActionName.PATH_OPEN_FOLDER,
    }
)

_SKILL_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_FORBIDDEN_KEYS = frozenset(
    {"cmd", "code", "command", "executable", "python", "script", "shell", "workflow"}
)
_BLOCKED_APP_NAMES = frozenset(
    {
        "cmd",
        "command prompt",
        "powershell",
        "pwsh",
        "python",
        "terminal",
        "windows terminal",
        "wsl",
    }
)
_SCRIPT_SUFFIXES = frozenset(
    {".bat", ".cmd", ".com", ".exe", ".hta", ".js", ".ps1", ".py", ".vbs", ".wsf"}
)


def _is_link_or_reparse(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return path.is_symlink() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        )
    except OSError:
        return True


@dataclass(frozen=True, slots=True)
class SkillStep:
    action: ActionName
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SkillManifest:
    skill_id: str
    name: str
    description: str
    steps: tuple[SkillStep, ...]
    source: str = "builtin"


_BUILTIN_PAYLOADS: tuple[dict[str, Any], ...] = (
    {
        "id": "diagnostico_rapido",
        "name": "Diagnóstico rápido",
        "description": "Consulta recursos y volumen sin modificar el equipo.",
        "steps": [
            {"action": "system.status", "arguments": {}},
            {"action": "volume.get", "arguments": {}},
        ],
    },
    {
        "id": "vista_de_trabajo",
        "name": "Vista de trabajo",
        "description": "Identifica la ventana actual y enumera las ventanas visibles.",
        "steps": [
            {"action": "window.current", "arguments": {}},
            {"action": "window.list", "arguments": {}},
        ],
    },
)


class SkillRegistry:
    """Loads inert JSON recipes and compiles them into typed action plans.

    A skill never imports code or executes an action. The regular action engine remains
    responsible for catalog validation, risk escalation and confirmation.
    """

    def __init__(
        self,
        manifest_directories: Iterable[Path] = (),
        *,
        allowed_actions: Iterable[ActionName] = DEFAULT_SKILL_ACTIONS,
        include_builtins: bool = True,
        max_steps: int = 5,
    ) -> None:
        if not 2 <= max_steps <= 5:
            raise ValueError("max_steps debe estar entre 2 y 5")
        self.max_steps = max_steps
        self.allowed_actions = frozenset(allowed_actions) - {
            ActionName.WORKFLOW_RUN,
            ActionName.DIALOG_CHOOSE,
        }
        if not self.allowed_actions:
            raise ValueError("La lista de acciones permitidas no puede estar vacía")
        self._skills: dict[str, SkillManifest] = {}
        if include_builtins:
            for payload in _BUILTIN_PAYLOADS:
                self._register(self._parse_payload(payload, "builtin"))
        for directory in manifest_directories:
            self._load_directory(Path(directory))

    @staticmethod
    def _plain_json(value: Any) -> Any:
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise SkillValidationError("Los argumentos deben ser JSON válido") from exc
        if len(encoded.encode("utf-8")) > 16_384:
            raise SkillValidationError("Los argumentos de la skill son demasiado grandes")
        return json.loads(encoded)

    @classmethod
    def _validate_arguments(cls, action: ActionName, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise SkillValidationError("Cada paso necesita un objeto JSON de argumentos")
        plain = cls._plain_json(arguments)

        def inspect(value: Any, depth: int = 0) -> None:
            if depth > 8:
                raise SkillValidationError("Los argumentos tienen demasiados niveles")
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized_key = str(key).strip().casefold()
                    if normalized_key in _FORBIDDEN_KEYS:
                        raise SkillValidationError(
                            f"El campo {key!r} puede ejecutar código y no está permitido"
                        )
                    inspect(item, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    inspect(item, depth + 1)
            elif isinstance(value, float) and not math.isfinite(value):
                raise SkillValidationError("Los números deben ser finitos")

        inspect(plain)
        if action is ActionName.APP_OPEN:
            app = plain.get("app")
            if isinstance(app, str) and app.strip().casefold() in _BLOCKED_APP_NAMES:
                raise SkillValidationError("Una skill no puede abrir una terminal o intérprete")
        for key in ("path", "file"):
            raw_path = plain.get(key)
            if isinstance(raw_path, str) and Path(raw_path).suffix.casefold() in _SCRIPT_SUFFIXES:
                raise SkillValidationError("Una skill no puede apuntar a scripts o ejecutables")
        return plain

    def _parse_payload(self, payload: Any, source: str) -> SkillManifest:
        if not isinstance(payload, dict):
            raise SkillValidationError("El manifiesto debe ser un objeto JSON")
        extras = set(payload) - {"id", "name", "description", "steps"}
        if extras:
            raise SkillValidationError(
                "El manifiesto contiene campos no permitidos: " + ", ".join(sorted(extras))
            )
        skill_id = payload.get("id")
        name = payload.get("name")
        description = payload.get("description", "")
        raw_steps = payload.get("steps")
        if not isinstance(skill_id, str) or _SKILL_ID.fullmatch(skill_id) is None:
            raise SkillValidationError("El identificador de la skill no es válido")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
            raise SkillValidationError("El nombre de la skill no es válido")
        if not isinstance(description, str) or len(description.strip()) > 500:
            raise SkillValidationError("La descripción de la skill no es válida")
        if not isinstance(raw_steps, list) or not 2 <= len(raw_steps) <= self.max_steps:
            raise SkillValidationError(f"Una skill debe contener entre 2 y {self.max_steps} pasos")

        steps: list[SkillStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict) or set(raw_step) != {"action", "arguments"}:
                raise SkillValidationError("Cada paso debe contener únicamente action y arguments")
            try:
                action = ActionName(raw_step["action"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SkillValidationError("La acción de la skill no existe") from exc
            if action not in self.allowed_actions:
                raise SkillValidationError(
                    f"La acción {action.value} no está permitida dentro de skills"
                )
            arguments = self._validate_arguments(action, raw_step["arguments"])
            steps.append(SkillStep(action, arguments))
        return SkillManifest(
            skill_id=skill_id,
            name=name.strip(),
            description=description.strip(),
            steps=tuple(steps),
            source=source,
        )

    def _register(self, manifest: SkillManifest) -> None:
        if manifest.skill_id in self._skills:
            raise SkillValidationError(f"La skill {manifest.skill_id!r} está duplicada")
        self._skills[manifest.skill_id] = manifest

    def _load_directory(self, directory: Path) -> None:
        if _is_link_or_reparse(directory):
            raise SkillValidationError("La carpeta de skills no puede ser un enlace")
        try:
            root = directory.resolve(strict=True)
        except OSError as exc:
            raise SkillValidationError("La carpeta de skills no existe") from exc
        if not root.is_dir():
            raise SkillValidationError("La ruta de skills no es una carpeta")
        for path in sorted(root.glob("*.json"), key=lambda item: item.name.casefold()):
            if _is_link_or_reparse(path):
                raise SkillValidationError(f"El manifiesto {path.name} no puede ser un enlace")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or resolved.stat().st_size > 64 * 1024:
                raise SkillValidationError(f"El manifiesto {path.name} no es seguro")
            try:
                payload = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SkillValidationError(f"No pude leer {path.name} como JSON") from exc
            self._register(self._parse_payload(payload, str(resolved)))

    def list(self) -> tuple[SkillManifest, ...]:
        return tuple(sorted(self._skills.values(), key=lambda item: item.skill_id))

    def list_skills(self) -> tuple[SkillManifest, ...]:
        return self.list()

    def get(self, skill_id: str) -> SkillManifest | None:
        return self._skills.get(skill_id.strip().casefold())

    def compile(self, skill_id: str) -> ActionWorkflowPlan:
        manifest = self.get(skill_id)
        if manifest is None:
            raise KeyError(f"No existe la skill {skill_id!r}")
        return ActionWorkflowPlan(
            steps=tuple(
                ActionPlan(
                    name=step.action,
                    arguments=dict(step.arguments),
                    source=ActionSource.DETERMINISTIC,
                )
                for step in manifest.steps
            ),
            source=ActionSource.DETERMINISTIC,
            confidence=1.0,
        )


__all__ = [
    "DEFAULT_SKILL_ACTIONS",
    "SkillManifest",
    "SkillRegistry",
    "SkillStep",
    "SkillValidationError",
]
