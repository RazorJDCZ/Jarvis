from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.actions.models import ActionName, ActionSource, ActionWorkflowPlan
from jarvis.capabilities.skills import SkillRegistry, SkillValidationError


def write_manifest(directory: Path, name: str, payload: object) -> None:
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_builtin_skills_are_inert_typed_workflows() -> None:
    registry = SkillRegistry()

    assert {skill.skill_id for skill in registry.list()} == {
        "diagnostico_rapido",
        "vista_de_trabajo",
    }
    manifest = registry.get("DIAGNOSTICO_RAPIDO")
    workflow = registry.compile("diagnostico_rapido")

    assert manifest is not None and manifest.source == "builtin"
    assert isinstance(workflow, ActionWorkflowPlan)
    assert workflow.source is ActionSource.DETERMINISTIC
    assert [step.name for step in workflow.steps] == [
        ActionName.SYSTEM_STATUS,
        ActionName.VOLUME_GET,
    ]


def test_json_manifest_loads_only_from_explicit_directory(tmp_path: Path) -> None:
    manifests = tmp_path / "skills"
    manifests.mkdir()
    write_manifest(
        manifests,
        "estudio.json",
        {
            "id": "modo_estudio",
            "name": "Modo estudio",
            "description": "Abre notas y consulta las ventanas.",
            "steps": [
                {"action": "app.open", "arguments": {"app": "notepad"}},
                {"action": "window.list", "arguments": {}},
            ],
        },
    )

    registry = SkillRegistry((manifests,), include_builtins=False)
    workflow = registry.compile("modo_estudio")

    assert registry.get("modo_estudio") is not None
    assert workflow.steps[0].arguments == {"app": "notepad"}


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": "accion_prohibida",
            "name": "Acción prohibida",
            "steps": [
                {"action": "pointer.click", "arguments": {"x": 1, "y": 2}},
                {"action": "window.list", "arguments": {}},
            ],
        },
        {
            "id": "skill_anidada",
            "name": "Skill anidada",
            "steps": [
                {"action": "workflow.run", "arguments": {"steps": []}},
                {"action": "window.list", "arguments": {}},
            ],
        },
        {
            "id": "con_script",
            "name": "Con script",
            "steps": [
                {"action": "system.status", "arguments": {"script": "do.ps1"}},
                {"action": "window.list", "arguments": {}},
            ],
        },
        {
            "id": "abre_shell",
            "name": "Abre shell",
            "steps": [
                {"action": "app.open", "arguments": {"app": "powershell"}},
                {"action": "window.list", "arguments": {}},
            ],
        },
    ],
)
def test_manifest_rejects_unsafe_actions_scripts_and_nesting(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    write_manifest(tmp_path, "unsafe.json", payload)

    with pytest.raises(SkillValidationError):
        SkillRegistry((tmp_path,), include_builtins=False)


def test_manifest_enforces_five_step_limit_and_exact_schema(tmp_path: Path) -> None:
    write_manifest(
        tmp_path,
        "too-many.json",
        {
            "id": "demasiados_pasos",
            "name": "Demasiados pasos",
            "unexpected": True,
            "steps": [{"action": "window.list", "arguments": {}} for _ in range(6)],
        },
    )

    with pytest.raises(SkillValidationError):
        SkillRegistry((tmp_path,), include_builtins=False)


def test_custom_action_allowlist_is_authoritative(tmp_path: Path) -> None:
    write_manifest(
        tmp_path,
        "custom.json",
        {
            "id": "solo_estado",
            "name": "Solo estado",
            "steps": [
                {"action": "system.status", "arguments": {}},
                {"action": "window.list", "arguments": {}},
            ],
        },
    )

    with pytest.raises(SkillValidationError, match="window.list"):
        SkillRegistry(
            (tmp_path,),
            include_builtins=False,
            allowed_actions={ActionName.SYSTEM_STATUS},
        )
