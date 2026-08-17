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
    assert LocalProfileStore(path).answer("¿Cómo se llama mi novia?") == ("Tu novia se llama Alex.")
    assert LocalProfileStore(path).answer("¿Qué te gusta de Alex?") == "Le encanta su sonrisa."
    assert "Quito, Ecuador" in (LocalProfileStore(path).self_summary() or "")
    assert LocalProfileStore(path).answer("¿Qué sabes de mí?") is None
    assert "Quito, Ecuador" in (LocalProfileStore(path).answer("¿Quién soy?") or "")


def test_invalid_or_missing_profile_fails_closed(tmp_path: Path) -> None:
    missing = LocalProfileStore(tmp_path / "missing.json")
    broken_path = tmp_path / "broken.json"
    broken_path.write_text("{not json", encoding="utf-8")

    assert missing.system_context() == ""
    assert LocalProfileStore(broken_path).system_context() == ""


def test_extended_profile_retrieves_only_relevant_personal_context(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "degree": "Ingeniería en Ciencias de la Computación",
                "university": "USFQ",
                "goals": ["graduarse", "conseguir un gran trabajo"],
                "projects": [
                    {
                        "name": "Appa",
                        "description": "Gestión de tareas y recordatorios.",
                        "connection": "Quiere conectarla con Jarvis.",
                    }
                ],
                "confirmation_required": ["enviar mensajes"],
                "important_people": [
                    {
                        "name": "Emi Vaca",
                        "aliases": ["Emi"],
                        "relation": "su mejor amiga",
                        "details": "Estudia Biotecnología.",
                    },
                    {
                        "name": "María Emilia",
                        "aliases": [],
                        "relation": "una gran amiga",
                        "details": "Es psicóloga.",
                    },
                ],
                "important_dates": [
                    {"label": "hermano", "month_day": "03-16"},
                ],
                "favorite_games": ["Minecraft", "Rocket League"],
                "favorite_artists": ["Milo J"],
            }
        ),
        encoding="utf-8",
    )
    store = LocalProfileStore(path)

    friend_context = store.context_for("Cuéntame algo sobre María Emilia")
    game_context = store.context_for("Recomiéndame un videojuego")

    assert "María Emilia" in friend_context
    assert "Es psicóloga" in friend_context
    assert "Estudia Biotecnología" not in friend_context
    assert "conseguir un gran trabajo" not in friend_context
    assert "Minecraft" in game_context
    assert "Milo J" not in game_context
    assert "Appa" in store.context_for("¿Cómo podríamos combinar Appa con Jarvis?")
    assert store.answer("¿Quién es Emi?") == (
        "Emi Vaca, a quien también llamas Emi, es tu mejor amiga. Estudia Biotecnología."
    )
    normal_analysis = store.person_analysis_answer("Cuéntame sobre Emi") or ""
    deep_analysis = store.person_analysis_answer(
        "Analiza a fondo a Emi",
        deep_analysis=True,
    ) or ""
    important_people = store.answer("¿Qué personas importantes tienes guardadas?") or ""
    assert "Emi Vaca" in normal_analysis
    assert "lectura más segura" in normal_analysis
    assert "no permite deducir inteligencia" in normal_analysis
    assert len(deep_analysis.split("\n\n")) == 4
    assert "Emi Vaca es tu mejor amiga" in deep_analysis
    assert "no sería responsable añadir" in deep_analysis
    assert store.person_analysis_answer("Compara a Emi con María Emilia") is None
    assert "Emi Vaca (Emi)" in important_people
    assert "María Emilia" in important_people
    assert store.is_person_reference("¿Quién es Emi?") is True
    assert store.is_person_reference("¿Quién es María Emilia?") is True
    assert store.is_person_reference("¿Quién es Alex?") is False
    assert store.is_person_reference("¿Qué sabes de una persona desconocida?") is False
    assert store.answer("¿Cuándo es el cumpleaños de mi hermano?") == (
        "El cumpleaños de tu hermano es el 16 de marzo."
    )
    assert "enviar mensajes" in store.context_for("hola")


def test_self_reference_and_analysis_context_cover_the_full_profile(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "birth_date": "2004-09-28",
                "degree": "Ingeniería en Ciencias de la Computación",
                "university": "USFQ",
                "semester": 9,
                "work_context": "Está terminando sus prácticas en Infraestructura.",
                "location": "Quito, Ecuador",
                "goals": ["graduarse", "fortalecer su perfil profesional"],
                "projects": [
                    {
                        "name": "Jarvis",
                        "description": "Un asistente personal local.",
                    },
                    {
                        "name": "Appa",
                        "description": "Una aplicación de tareas.",
                    },
                ],
                "routine": ["entrena en el gimnasio", "descansa jugando videojuegos"],
                "favorite_games": ["Minecraft"],
                "future_vision": "Quiere una vida tranquila y estabilidad económica.",
                "confirmation_required": ["enviar mensajes"],
                "important_people": [
                    {
                        "name": "Emi",
                        "relation": "su mejor amiga",
                        "details": "Estudia Biotecnología.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = LocalProfileStore(path)

    for request in (
        "¿Qué sabes de mí?",
        "Jarvis, analízame",
        "¿Cómo me describirías?",
        "¿Cómo me percibes?",
        "¿Qué clase de persona crees que soy?",
        "Analiza mi perfil profesional",
        "¿Qué opinas de mis metas?",
        "¿Cuáles son mis fortalezas?",
        "¿Qué opinas de Juan Diego?",
    ):
        assert store.is_self_reference(request) is True

    context = store.self_analysis_context()

    assert "SITUACIÓN ACADÉMICA Y PROFESIONAL" in context
    assert "Jarvis: Un asistente personal local" in context
    assert "Appa: Una aplicación de tareas" in context
    assert "Minecraft" in context
    assert "vida tranquila" in context
    assert "enviar mensajes" in context
    assert "una amistad importante" in context
    assert "Estudia Biotecnología" not in context

    normal = store.self_analysis_answer("¿Qué impresión tienes de mí?") or ""
    deep = store.self_analysis_answer("Analízame a fondo", deep_analysis=True) or ""

    assert len(normal.split("\n\n")) == 3
    assert "te interesa aplicar la tecnología a problemas concretos" in normal
    assert "no una personalidad fija" in normal
    assert "disciplinado eres" in normal
    assert len(deep.split("\n\n")) == 6
    assert "posible orientación hacia la tecnología aplicada" in deep
    assert "riesgo práctico de priorización" in deep
    assert "No hay datos para concluir" in deep
    assert "juegas solo" not in deep
    assert "dependencia digital" not in deep


def test_self_identity_is_factual_but_reflective_phrasing_is_left_for_analysis(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "degree": "Computación",
                "location": "Quito",
            }
        ),
        encoding="utf-8",
    )
    store = LocalProfileStore(path)

    assert store.answer("Jarvis, ¿quién soy?") == (
        "Te llamas Juan Diego, vives en Quito, estudias Computación."
    )
    assert store.answer("¿Quién es Juan Diego para ti?") == (
        "Te llamas Juan Diego, vives en Quito, estudias Computación."
    )
    assert store.answer("Cuéntame sobre mí") is None
    assert store.answer("¿Qué impresión tienes de mí?") is None


def test_person_context_marks_group_parent_as_metaphorical(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "degree": "Computación",
                "important_people": [
                    {
                        "name": "Washington",
                        "aliases": ["Washo"],
                        "relation": "un amigo cercano y el papá del grupo",
                        "details": "Es muy buen dato, tranquilo y suele cuidar a los demás.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    context = LocalProfileStore(path).context_for("Analiza a Washo")

    assert "apodo social metafórico" in context
    assert "no significa que sea padre" in context
    assert "muy buena persona y muy buena compañía" in context
    assert "buen dato" not in context
    assert "Estudia Computación" not in context
    assert LocalProfileStore(path).answer("¿Quién es Washo?") == (
        "Washington, a quien también llamas Washo, es un amigo cercano. "
        "Dentro del grupo lo llaman el «papá del grupo» en sentido afectivo. "
        "Es muy buena persona y muy buena compañía, tranquilo y suele cuidar a los demás."
    )


def test_partner_name_uses_the_private_person_route_without_unrelated_details(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "partner_name": "Nahir",
                "partner_fun_fact": "Le encantan sus cachetes.",
                "degree": "Computación",
            }
        ),
        encoding="utf-8",
    )
    store = LocalProfileStore(path)

    identity_context = store.context_for("¿Quién es Nahir para mí?")
    affectionate_context = store.context_for("¿Qué te gusta de los cachetes de Nahir?")

    assert store.is_person_reference("¿Quién es Nahir?") is True
    assert store.answer("¿Quién es Nahir para mí?") == "Nahir es tu novia."
    assert "suficiente contexto" in (store.person_analysis_limitation("Cuéntame sobre Nahir") or "")
    assert store.person_analysis_limitation("Cuéntame sobre Paula") is None
    assert "Nahir es tu novia" in identity_context
    assert "cachetes" not in identity_context
    assert "Computación" not in identity_context
    assert "cachetes" in affectionate_context


def test_ecuadorian_person_descriptions_are_normalized_for_the_model(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "important_people": [
                    {
                        "name": "Paula",
                        "relation": "una amiga",
                        "details": "Es chistosa y acolita en todo.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    context = LocalProfileStore(path).context_for("¿Quién es Paula?")

    assert "te apoya y se suma a cualquier plan" in context
    assert "acolita" not in context


def test_person_questions_never_fall_through_to_juan_diegos_facts(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "preferred_name": "Juan Diego",
                "degree": "Ciencias de la Computación",
                "university": "USFQ",
                "projects": [
                    {"name": "Jarvis", "description": "Un asistente personal."},
                ],
                "important_people": [
                    {
                        "name": "Emi Vaca",
                        "aliases": ["Emi"],
                        "relation": "su mejor amiga",
                        "details": "Estudia Ingeniería en Biotecnología en la USFQ.",
                    }
                ],
                "important_dates": [
                    {"label": "hermano", "month_day": "03-16"},
                ],
            }
        ),
        encoding="utf-8",
    )
    store = LocalProfileStore(path)

    education = store.answer("¿Qué carrera estudia Emi?") or ""
    university = store.answer("¿En qué universidad estudia Emi?") or ""

    assert "Biotecnología" in education
    assert "Biotecnología" in university
    assert "Ciencias de la Computación" not in education
    assert store.answer("¿Qué proyectos tiene Emi?") is None
    assert store.answer("¿Cuándo cumple años Emi?") is None
    assert store.answer("¿Cuándo cumple años Alex?") is None
    assert store.answer("¿Qué carrera estudio yo?") == (
        "Estudias Ciencias de la Computación en USFQ."
    )
    assert "hermano: 16 de marzo" in (
        store.answer("¿Qué fechas importantes tienes guardadas?") or ""
    )
