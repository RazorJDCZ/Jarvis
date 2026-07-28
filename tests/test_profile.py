from __future__ import annotations

import json
from pathlib import Path

from jarvis.services.profile import LocalProfileStore


def test_local_profile_is_validated_and_rendered_as_private_context(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juandi",
                "birth_date": "2004-09-28",
                "partner_name": "Alex",
                "partner_fun_fact": "Le encanta su sonrisa.",
                "degree": "Ingenieria en Ciencias de la Computacion",
                "semester": 9,
                "location": "Quito, Ecuador",
                "interests": ["los videojuegos", "tocar el ukelele"],
                "ignored_secret": "no debe salir",
            }
        ),
        encoding="utf-8",
    )

    profile = LocalProfileStore(path).load()
    context = profile.system_context()

    assert profile.preferred_name == "Juandi"
    assert profile.partner_name == "Alex"
    assert profile.age is not None
    assert "noveno semestre" in context
    assert "Quito, Ecuador" in context
    assert "no debe salir" not in context
    assert "No lo menciones fuera" in context
    assert LocalProfileStore(path).answer("¿Cómo se llama mi novia?") == (
        "Tu novia se llama Alex."
    )
    assert LocalProfileStore(path).answer("¿Qué te gusta de Alex?") == "Le encanta su sonrisa."
    assert "Quito, Ecuador" in (LocalProfileStore(path).answer("¿Qué sabes de mí?") or "")


def test_invalid_or_missing_profile_fails_closed(tmp_path: Path) -> None:
    missing = LocalProfileStore(tmp_path / "missing.json")
    broken_path = tmp_path / "broken.json"
    broken_path.write_text("{not json", encoding="utf-8")

    assert missing.system_context() == ""
    assert LocalProfileStore(broken_path).system_context() == ""
