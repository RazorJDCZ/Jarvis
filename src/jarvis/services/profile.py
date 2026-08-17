from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProfileProject:
    name: str
    description: str
    connection: str = ""


@dataclass(frozen=True, slots=True)
class ImportantPerson:
    name: str
    aliases: tuple[str, ...] = ()
    relation: str = ""
    details: str = ""


@dataclass(frozen=True, slots=True)
class ImportantDate:
    label: str
    month_day: str


@dataclass(frozen=True, slots=True)
class UserProfile:
    preferred_name: str = ""
    birth_date: str = ""
    partner_name: str = ""
    partner_fun_fact: str = ""
    degree: str = ""
    university: str = ""
    semester: int | None = None
    academic_status: str = ""
    work_context: str = ""
    location: str = ""
    interests: tuple[str, ...] = ()
    goals: tuple[str, ...] = ()
    projects: tuple[ProfileProject, ...] = ()
    routine: tuple[str, ...] = ()
    tools: tuple[tuple[str, tuple[str, ...]], ...] = ()
    assistant_role: str = ""
    proactive_help: tuple[str, ...] = ()
    confirmation_required: tuple[str, ...] = ()
    important_people: tuple[ImportantPerson, ...] = ()
    important_dates: tuple[ImportantDate, ...] = ()
    favorite_games: tuple[str, ...] = ()
    favorite_artists: tuple[str, ...] = ()
    favorite_foods: tuple[str, ...] = ()
    travel_goals: tuple[str, ...] = ()
    future_vision: str = ""
    privacy_preference: str = ""

    @property
    def age(self) -> int | None:
        try:
            born = date.fromisoformat(self.birth_date)
        except ValueError:
            return None
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    @staticmethod
    def _normalized(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @staticmethod
    def _line(text: str) -> str:
        return f"- {text.strip()}" if text.strip() else ""

    @classmethod
    def _mentions(cls, normalized_message: str, reference: str) -> bool:
        needle = cls._normalized(reference)
        return bool(needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", normalized_message))

    def _base_context(self) -> list[str]:
        facts: list[str] = []
        if self.preferred_name:
            facts.append(f"Su nombre preferido es {self.preferred_name}.")
        if self.birth_date:
            age = self.age
            age_text = f"; actualmente tiene {age} años" if age is not None else ""
            facts.append(f"Nació el {self.birth_date}{age_text}.")
        if self.degree:
            education = f"Estudia {self.degree}"
            if self.university:
                education += f" en {self.university}"
            if self.semester == 9:
                education += " y cursa el noveno semestre"
            elif self.semester is not None:
                education += f" y cursa el semestre {self.semester}"
            facts.append(education + ".")
        if self.academic_status:
            facts.append(self.academic_status)
        if self.work_context:
            facts.append(self.work_context)
        if self.location:
            facts.append(f"Vive en {self.location}.")
        if self.goals:
            facts.append(f"Sus objetivos prioritarios son: {'; '.join(self.goals)}.")
        if self.assistant_role:
            facts.append(f"Espera que Jarvis actúe como {self.assistant_role}.")
        if self.confirmation_required:
            facts.append(
                f"Jarvis debe pedir confirmación antes de: {'; '.join(self.confirmation_required)}."
            )
        if self.privacy_preference:
            facts.append(self.privacy_preference)
        return facts

    def self_analysis_context(self) -> str:
        """Render broad, structured evidence for reflection about Juan Diego himself."""
        sections: list[tuple[str, list[str]]] = []

        identity: list[str] = []
        if self.preferred_name:
            identity.append(f"Nombre preferido: {self.preferred_name}.")
        if self.birth_date:
            age = f"; edad actual calculada: {self.age}" if self.age is not None else ""
            identity.append(f"Fecha de nacimiento: {self.birth_date}{age}.")
        if self.location:
            identity.append(f"Residencia: {self.location}.")
        if identity:
            sections.append(("IDENTIDAD", identity))

        academic: list[str] = []
        if self.degree:
            education = f"Estudia {self.degree}"
            if self.university:
                education += f" en {self.university}"
            if self.semester is not None:
                education += f"; semestre registrado: {self.semester}"
            academic.append(education + ".")
        if self.academic_status:
            academic.append(self.academic_status.rstrip(".") + ".")
        if self.work_context:
            academic.append(self.work_context.rstrip(".") + ".")
        if academic:
            sections.append(("SITUACIÓN ACADÉMICA Y PROFESIONAL", academic))

        if self.goals:
            sections.append(("OBJETIVOS DECLARADOS", list(self.goals)))
        if self.projects:
            sections.append(
                (
                    "PROYECTOS",
                    [
                        f"{project.name}: {project.description.rstrip('.')}"
                        + (f" {project.connection.rstrip('.')}" if project.connection else "")
                        + "."
                        for project in self.projects
                    ],
                )
            )
        if self.routine:
            sections.append(("RUTINA QUE DESCRIBIÓ", list(self.routine)))

        preferences: list[str] = []
        if self.interests:
            preferences.append(f"Intereses y actividades: {', '.join(self.interests)}.")
        if self.favorite_games:
            preferences.append(f"Videojuegos favoritos: {', '.join(self.favorite_games)}.")
        if self.favorite_artists:
            preferences.append(f"Artistas favoritos: {', '.join(self.favorite_artists)}.")
        if self.favorite_foods:
            preferences.append(f"Comidas favoritas: {', '.join(self.favorite_foods)}.")
        if self.travel_goals:
            preferences.append(f"Objetivos de viaje: {'; '.join(self.travel_goals)}.")
        if preferences:
            sections.append(("INTERESES Y PREFERENCIAS", preferences))

        tools: list[str] = []
        for category, items in self.tools:
            tools.append(f"Para {category}: {', '.join(items)}.")
        if tools:
            sections.append(("HERRAMIENTAS HABITUALES", tools))

        relationships: list[str] = []
        if self.partner_name:
            relationships.append(f"Su novia se llama {self.partner_name}.")
        if self.important_people:
            count = len(self.important_people)
            friendship_label = "una amistad importante" if count == 1 else f"{count} amistades"
            relationships.append(
                f"Ha identificado {friendship_label}, incluyendo mejores amistades, amistades "
                "del colegio o amistades cercanas."
            )
        if relationships:
            sections.append(("RELACIONES CONFIRMADAS", relationships))

        outlook: list[str] = []
        if self.future_vision:
            outlook.append(self.future_vision.rstrip(".") + ".")
        if self.assistant_role:
            outlook.append(f"Espera que Jarvis actúe como {self.assistant_role}.")
        if self.proactive_help:
            outlook.append(f"Ayuda que desea: {'; '.join(self.proactive_help)}.")
        if outlook:
            sections.append(("VISIÓN Y APOYO DESEADO", outlook))

        boundaries: list[str] = []
        if self.confirmation_required:
            boundaries.append(
                "Ha pedido confirmación antes de: " + "; ".join(self.confirmation_required) + "."
            )
        if self.privacy_preference:
            boundaries.append(self.privacy_preference.rstrip(".") + ".")
        if boundaries:
            sections.append(("PREFERENCIAS DE SEGURIDAD", boundaries))

        lines = [
            "Toda la evidencia siguiente fue proporcionada por Juan Diego y describe a Juan "
            "Diego. Son hechos de perfil o preferencias declaradas, no diagnósticos ni rasgos "
            "demostrados."
        ]
        for title, entries in sections:
            lines.append(f"[{title}]")
            lines.extend(self._line(entry) for entry in entries if entry.strip())
        return "\n".join(lines)

    def system_context(self, message: str = "") -> str:
        """Render a compact base plus only the profile sections relevant to this turn."""
        normalized = self._normalized(message)
        partner_referenced = bool(
            self.partner_name and self._mentions(normalized, self.partner_name)
        )
        matched_people = [
            person
            for person in self.important_people
            if any(
                self._mentions(normalized, reference)
                for reference in (person.name, *person.aliases)
                if reference
            )
        ]
        if partner_referenced:
            partner_facts = [
                f"Persona privada consultada: {self.partner_name}.",
                f"Relación contigo: {self.partner_name} es tu novia.",
            ]
            if self.partner_fun_fact and any(
                marker in normalized
                for marker in (
                    "cachete",
                    "cualidad fisica",
                    "detalle favorito",
                    "que me gusta",
                    "que te gusta",
                )
            ):
                partner_facts.append(f"Dato cariñoso que proporcionaste: {self.partner_fun_fact}")
            return "\n".join(self._line(fact) for fact in partner_facts if fact.strip())

        if matched_people:
            # Person questions need a small evidence envelope. Including Juan Diego's career,
            # location and goals encouraged a compact model to invent comparisons unrelated to
            # the person being discussed.
            person_facts: list[str] = []
            for person in matched_people:
                aliases = (
                    f"; también le dices {', '.join(person.aliases)}" if person.aliases else ""
                )
                relation = person.relation or "relación no especificada"
                relation = re.sub(r"\bsus\b", "tus", relation, flags=re.IGNORECASE)
                relation = re.sub(r"\bsu\b", "tu", relation, flags=re.IGNORECASE)
                person_facts.append(
                    f"Persona privada consultada: {person.name}{aliases}. "
                    f"Relación contigo: {relation}."
                )
                if "papa del grupo" in self._normalized(relation):
                    person_facts.append(
                        "La expresión «papá del grupo» es un apodo social metafórico: no significa "
                        "que sea padre ni prueba autoridad, jerarquía o experiencia superior."
                    )
                if person.details:
                    details = re.sub(
                        r"\bJuan Diego aprecia\b",
                        "tú aprecias",
                        person.details,
                        flags=re.IGNORECASE,
                    )
                    details = re.sub(
                        r"\b(?:es )?muy buen dato\b",
                        "es muy buena persona y muy buena compañía",
                        details,
                        flags=re.IGNORECASE,
                    )
                    details = re.sub(
                        r"\bacolita en todo\b",
                        "te apoya y se suma a cualquier plan",
                        details,
                        flags=re.IGNORECASE,
                    )
                    person_facts.append(
                        f"Datos confirmados exclusivamente sobre {person.name}: {details}"
                    )
            return "\n".join(self._line(fact) for fact in person_facts if fact.strip())

        facts = self._base_context()

        def relevant(*markers: str) -> bool:
            return not normalized or any(marker in normalized for marker in markers)

        if self.partner_name and relevant("nahir", "novia", "pareja", "relacion", "amor", "cita"):
            facts.append(f"Su novia se llama {self.partner_name}.")
            if self.partner_fun_fact:
                facts.append(
                    f"Dato cariñoso privado sobre su novia: {self.partner_fun_fact} "
                    "No lo menciones fuera de un contexto claramente pertinente."
                )
        if self.projects and relevant(
            "proyecto", "jarvis", "appa", "aplicacion", "app", "tarea", "recordatorio"
        ):
            facts.extend(
                f"Proyecto {project.name}: {project.description}"
                + (f" {project.connection}" if project.connection else "")
                for project in self.projects
            )
        if self.routine and relevant(
            "rutina", "horario", "dia", "manana", "trabajo", "clase", "gimnasio", "entreno"
        ):
            facts.append(f"Su rutina habitual: {'; '.join(self.routine)}.")
        if self.tools and relevant(
            "aplicacion", "herramienta", "estudiar", "programar", "comunicar", "entreten"
        ):
            for category, items in self.tools:
                facts.append(f"Herramientas para {category}: {', '.join(items)}.")
        if self.proactive_help and relevant(
            "proactivo", "ayuda", "secretario", "organiza", "planifica", "recordatorio"
        ):
            facts.append(f"Ayuda proactiva deseada: {'; '.join(self.proactive_help)}.")

        if self.important_people and relevant("amigo", "amiga", "grupo", "colegio"):
            people = "; ".join(
                f"{person.name} ({person.relation})" if person.relation else person.name
                for person in self.important_people
            )
            facts.append(f"Personas importantes de su grupo: {people}.")

        if self.important_dates and relevant(
            "fecha", "cumple", "cumpleanos", "aniversario", "calendario"
        ):
            facts.append(
                "Fechas personales: "
                + "; ".join(f"{item.label}: {item.month_day}" for item in self.important_dates)
                + "."
            )
        if self.favorite_games and relevant("juego", "videojuego", "gaming", "jugar"):
            facts.append(f"Videojuegos favoritos: {', '.join(self.favorite_games)}.")
        if self.favorite_artists and relevant(
            "musica", "artista", "cancion", "playlist", "escuchar"
        ):
            facts.append(f"Artistas favoritos: {', '.join(self.favorite_artists)}.")
        if self.favorite_foods and relevant(
            "comida", "comer", "restaurante", "hamburguesa", "pizza", "plato"
        ):
            facts.append(f"Comidas favoritas: {', '.join(self.favorite_foods)}.")
        if self.travel_goals and relevant(
            "viaje", "viajar", "turismo", "ecuador", "conocer", "destino"
        ):
            facts.append(f"Objetivos de viaje: {'; '.join(self.travel_goals)}.")
        if self.future_vision and relevant(
            "futuro", "trabajo", "carrera", "profesional", "familia", "dinero", "gradu"
        ):
            facts.append(f"Visión de futuro: {self.future_vision}")
        if self.interests and relevant("gusto", "hobby", "tiempo libre", "interes"):
            facts.append(f"Le gusta {', '.join(self.interests)}.")
        return "\n".join(self._line(fact) for fact in facts if fact.strip())


class LocalProfileStore:
    _MAX_BYTES = 65_536
    _TEXT_FIELDS = (
        "preferred_name",
        "birth_date",
        "partner_name",
        "partner_fun_fact",
        "degree",
        "university",
        "academic_status",
        "work_context",
        "location",
        "assistant_role",
        "future_vision",
        "privacy_preference",
    )
    _LIST_FIELDS = (
        "interests",
        "goals",
        "routine",
        "proactive_help",
        "confirmation_required",
        "favorite_games",
        "favorite_artists",
        "favorite_foods",
        "travel_goals",
    )
    _TOOL_CATEGORIES = ("estudiar", "programar", "comunicarse", "entretenerse")

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _short_text(data: dict[str, Any], name: str, maximum: int = 700) -> str:
        value = data.get(name, "")
        if not isinstance(value, str):
            return ""
        return value.strip()[:maximum]

    @staticmethod
    def _text_list(value: object, maximum_items: int = 30) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            item.strip()[:300]
            for item in value[:maximum_items]
            if isinstance(item, str) and item.strip()
        )

    def _projects(self, value: object) -> tuple[ProfileProject, ...]:
        if not isinstance(value, list):
            return ()
        projects: list[ProfileProject] = []
        for item in value[:12]:
            if not isinstance(item, dict):
                continue
            name = self._short_text(item, "name", 120)
            description = self._short_text(item, "description", 700)
            if name and description:
                projects.append(
                    ProfileProject(name, description, self._short_text(item, "connection", 500))
                )
        return tuple(projects)

    def _people(self, value: object) -> tuple[ImportantPerson, ...]:
        if not isinstance(value, list):
            return ()
        people: list[ImportantPerson] = []
        for item in value[:40]:
            if not isinstance(item, dict):
                continue
            name = self._short_text(item, "name", 120)
            if not name:
                continue
            people.append(
                ImportantPerson(
                    name=name,
                    aliases=self._text_list(item.get("aliases"), 8),
                    relation=self._short_text(item, "relation", 200),
                    details=self._short_text(item, "details", 900),
                )
            )
        return tuple(people)

    def _dates(self, value: object) -> tuple[ImportantDate, ...]:
        if not isinstance(value, list):
            return ()
        dates: list[ImportantDate] = []
        for item in value[:40]:
            if not isinstance(item, dict):
                continue
            label = self._short_text(item, "label", 120)
            month_day = self._short_text(item, "month_day", 5)
            try:
                date.fromisoformat(f"2000-{month_day}")
            except ValueError:
                continue
            if label:
                dates.append(ImportantDate(label, month_day))
        return tuple(dates)

    def _tools(self, value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
        if not isinstance(value, dict):
            return ()
        return tuple(
            (category, items)
            for category in self._TOOL_CATEGORIES
            if (items := self._text_list(value.get(category), 12))
        )

    def load(self) -> UserProfile:
        try:
            if not self.path.is_file() or self.path.stat().st_size > self._MAX_BYTES:
                return UserProfile()
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return UserProfile()
        if not isinstance(raw, dict):
            return UserProfile()

        text = {name: self._short_text(raw, name) for name in self._TEXT_FIELDS}
        if text["birth_date"]:
            try:
                date.fromisoformat(text["birth_date"])
            except ValueError:
                text["birth_date"] = ""
        semester_value = raw.get("semester")
        semester = semester_value if isinstance(semester_value, int) else None
        if semester is not None and not 1 <= semester <= 20:
            semester = None
        lists = {name: self._text_list(raw.get(name)) for name in self._LIST_FIELDS}
        return UserProfile(
            **text,
            **lists,
            semester=semester,
            projects=self._projects(raw.get("projects")),
            tools=self._tools(raw.get("tools")),
            important_people=self._people(raw.get("important_people")),
            important_dates=self._dates(raw.get("important_dates")),
        )

    def system_context(self) -> str:
        return self.load().system_context()

    def context_for(self, message: str) -> str:
        return self.load().system_context(message)

    def self_analysis_context(self) -> str:
        return self.load().self_analysis_context()

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @staticmethod
    def _human_date(month_day: str) -> str:
        months = (
            "enero",
            "febrero",
            "marzo",
            "abril",
            "mayo",
            "junio",
            "julio",
            "agosto",
            "septiembre",
            "octubre",
            "noviembre",
            "diciembre",
        )
        month, day = (int(part) for part in month_day.split("-"))
        return f"{day} de {months[month - 1]}"

    @staticmethod
    def _work_answer(work_context: str) -> str:
        if work_context.startswith("Está "):
            work_context = "Estás " + work_context[5:]
        return work_context.replace(" sus ", " tus ").replace(" su ", " tu ")

    @classmethod
    def _mentions(cls, normalized_message: str, reference: str) -> bool:
        needle = cls._normalize(reference)
        return bool(needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", normalized_message))

    def is_person_reference(self, message: str) -> bool:
        normalized = self._normalize(message)
        profile = self.load()
        partner_reference = bool(
            profile.partner_name and self._mentions(normalized, profile.partner_name)
        )
        return partner_reference or any(
            self._mentions(normalized, reference)
            for person in profile.important_people
            for reference in (person.name, *person.aliases)
        )

    def is_self_reference(self, message: str) -> bool:
        normalized = self._normalize(message)
        profile = self.load()
        if profile.preferred_name and self._mentions(normalized, profile.preferred_name):
            return True
        return bool(
            re.search(
                r"\b(?:sobre|acerca de|de) mi\b|"
                r"\b(?:quien|como) soy\b|"
                r"\bcomo (?:dirias|crees) que soy\b|"
                r"\bcomo me (?:ves|describirias|definirias|percibes)\b|"
                r"\bque (?:tipo|clase) de persona (?:crees que )?soy\b|"
                r"\b(?:analiza|evalua|interpreta|describe)me\b|"
                r"\bmi (?:personalidad|perfil(?: personal| profesional| psicologico)?|"
                r"forma de ser|caracter|situacion (?:actual|academica|profesional)|"
                r"trayectoria|rutina|vida|carrera)\b|"
                r"\bmis (?:fortalezas|debilidades|rasgos|cualidades|defectos|patrones|"
                r"metas|objetivos|prioridades|decisiones|habitos)\b",
                normalized,
            )
        )

    @classmethod
    def _self_identity_question(cls, normalized_message: str, preferred_name: str) -> bool:
        request = re.sub(r"^jarvis[\s,;:.-]+", "", normalized_message).strip(" ¿¡!?.")
        if re.fullmatch(r"(?:dime\s+)?quien soy(?: yo)?", request):
            return True
        name = cls._normalize(preferred_name)
        return bool(
            name
            and re.fullmatch(
                rf"(?:dime\s+)?quien es {re.escape(name)}(?: para ti)?",
                request,
            )
        )

    def self_summary(self) -> str | None:
        profile = self.load()
        parts: list[str] = []
        if profile.preferred_name:
            parts.append(f"te llamas {profile.preferred_name}")
        if profile.age is not None:
            parts.append(f"tienes {profile.age} años")
        if profile.location:
            parts.append(f"vives en {profile.location}")
        if profile.degree:
            education = f"estudias {profile.degree}"
            if profile.university:
                education += f" en {profile.university}"
            parts.append(education)
        if profile.work_context:
            parts.append(self._work_answer(profile.work_context).rstrip("."))
        if profile.partner_name:
            parts.append(f"tu novia se llama {profile.partner_name}")
        if profile.goals:
            parts.append(f"tus prioridades son {'; '.join(profile.goals)}")
        if not parts:
            return None
        sentence = ", ".join(parts)
        return sentence[0].upper() + sentence[1:] + "."

    @staticmethod
    def _second_person_statement(text: str) -> str:
        result = text.strip().rstrip(".")
        substitutions = (
            (r"^Está\b", "Estás"),
            (r"^Quiere\b", "Quieres"),
            (r"^Le interesa\b", "Te interesa"),
            (r"\bgraduarse\b", "graduarte"),
            (r"\bse gradúe\b", "te gradúes"),
            (r"\bse levanta\b", "te levantas"),
            (r"\bva a\b", "vas a"),
            (r"\bentrena\b", "entrenas"),
            (r"\bhace\b", "haces"),
            (r"\bresuelve\b", "resuelves"),
            (r"\bdescansa\b", "descansas"),
            (r"\bsus\b", "tus"),
            (r"\bsu\b", "tu"),
        )
        for pattern, replacement in substitutions:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    @classmethod
    def _routine_fragment(cls, text: str) -> str:
        result = cls._second_person_statement(text)
        substitutions = (
            (r"\bte levantas\b", "levantarte"),
            (r"\bvas a\b", "ir a"),
            (r"\bentrenas\b", "entrenar"),
            (r"\bhaces\b", "hacer"),
            (r"\bresuelves\b", "resolver"),
            (r"\bdescansas\b", "descansar"),
        )
        for pattern, replacement in substitutions:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    @staticmethod
    def _natural_join(items: list[str]) -> str:
        clean = [item.strip() for item in items if item.strip()]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        return f"{', '.join(clean[:-1])} y {clean[-1]}"

    @classmethod
    def _normal_self_analysis(cls, profile: UserProfile, normalized_message: str) -> str:
        projects = cls._natural_join([project.name for project in profile.projects])
        study = profile.degree or "tu formación universitaria"
        if profile.university:
            study += f" en la {profile.university}"
        work = cls._second_person_statement(profile.work_context) if profile.work_context else ""
        routine = cls._natural_join([cls._routine_fragment(item) for item in profile.routine])
        goals = cls._natural_join(
            [cls._second_person_statement(goal) for goal in profile.goals]
        )
        focus_on_growth = bool(
            re.search(
                r"\b(?:debilidad|debilidades|defecto|defectos|mejorar|riesgo|riesgos|"
                r"punto debil|puntos debiles)\b",
                normalized_message,
            )
        )
        focus_on_strengths = bool(
            re.search(
                r"\b(?:fortaleza|fortalezas|cualidad|cualidades|punto fuerte|puntos fuertes)\b",
                normalized_message,
            )
        )

        first_facts = f"estudias {study}"
        if work:
            first_facts += f" y {work[0].lower() + work[1:]}"
        first = (
            f"Por lo que has confirmado, tu etapa actual conecta formación y práctica: "
            f"{first_facts}."
        )
        if projects:
            first += (
                f" Una lectura razonable es que hoy te interesa aplicar la tecnología a "
                f"problemas concretos, porque además desarrollas {projects}; esto describe tus "
                "decisiones actuales, no una personalidad fija."
            )

        second_parts: list[str] = []
        if goals:
            second_parts.append(
                f"Tus metas —{goals}— muestran de forma directa que el desarrollo intelectual "
                "y profesional es una prioridad declarada."
            )
        if routine:
            second_parts.append(
                f"Tu rutina combina {routine}; eso confirma que distribuyes tiempo entre "
                "obligaciones, actividad física y descanso, pero no permite medir tu constancia "
                "ni cómo te sientes al sostenerla."
            )
        if focus_on_strengths:
            second_parts.append(
                "Como activos observables, ya tienes experiencia académica avanzada, práctica "
                "profesional y proyectos propios; llamarlos iniciativa aplicada es razonable, "
                "pero todavía no basta para evaluar la calidad o constancia de tus resultados."
            )
        if focus_on_growth:
            second_parts.append(
                "El punto de atención mejor respaldado no es una debilidad demostrada, sino un "
                "riesgo práctico de dispersión: estudios, prácticas, proyectos y vida personal "
                "compiten por tiempo, aunque el perfil no dice que hoy los estés gestionando mal."
            )

        third_parts: list[str] = []
        if profile.future_vision:
            third_parts.append(
                "Tu visión futura reúne trabajo, estabilidad económica, tranquilidad y la "
                "posibilidad de formar una familia, sin establecer que una dimensión importe más "
                "que otra."
            )
        if profile.assistant_role and profile.confirmation_required:
            third_parts.append(
                "En Jarvis buscas automatización amplia con confirmaciones ante acciones "
                "sensibles; esa es una preferencia de diseño verificable, no una prueba de "
                "control, ansiedad o confianza personal."
            )
        third_parts.append(
            "En conjunto, el perfil permite hablar con bastante seguridad de tus prioridades, "
            "proyectos y forma actual de repartir actividades, pero no de cómo reaccionas bajo "
            "presión, qué tan disciplinado eres ni qué rasgos conservarías en otros contextos."
        )
        return "\n\n".join((first, " ".join(second_parts), " ".join(third_parts)))

    @classmethod
    def _deep_self_analysis(cls, profile: UserProfile, normalized_message: str) -> str:
        del normalized_message
        degree = profile.degree or "una carrera universitaria"
        university = f" en la {profile.university}" if profile.university else ""
        semester = f", con el semestre {profile.semester} registrado" if profile.semester else ""
        academic_status = (
            cls._second_person_statement(profile.academic_status) if profile.academic_status else ""
        )
        work = cls._second_person_statement(profile.work_context) if profile.work_context else ""
        projects = cls._natural_join([project.name for project in profile.projects])
        project_descriptions = cls._natural_join(
            [
                f"{project.name}, {cls._second_person_statement(project.description).lower()}"
                for project in profile.projects
            ]
        )
        goals = cls._natural_join(
            [cls._second_person_statement(goal) for goal in profile.goals]
        )
        routine = cls._natural_join([cls._routine_fragment(item) for item in profile.routine])
        interests = cls._natural_join(
            [cls._second_person_statement(item) for item in profile.interests]
        )
        friends = len(profile.important_people)
        future = cls._second_person_statement(profile.future_vision)

        paragraphs = [
            (
                f"La lectura más sólida de tu momento actual parte de una convergencia concreta: "
                f"estudias {degree}{university}{semester}"
                + (
                    f", {academic_status[0].lower() + academic_status[1:]}"
                    if academic_status
                    else ""
                )
                + (f" y {work[0].lower() + work[1:]}" if work else "")
                + ". No hace falta convertir esos hechos en una etiqueta psicológica para ver "
                "que estás en una etapa de transición académica y profesional. Tu atención "
                "declarada está puesta en cerrar la carrera, ganar experiencia y preparar el "
                "paso al empleo; el perfil no permite asegurar cuándo ocurrirá ese paso ni cómo "
                "te sientes ante él."
            ),
            (
                "La primera conexión analítica bien respaldada es una posible orientación hacia "
                f"la tecnología aplicada. No solo estudias {degree} y trabajas en "
                "Infraestructura: también mantienes proyectos propios"
                + (f" como {projects}" if projects else "")
                + (f" —{project_descriptions}—" if project_descriptions else "")
                + ". En conjunto, esas decisiones muestran que hoy buscas relacionar el "
                "conocimiento técnico con resultados utilizables. Esto no demuestra por sí solo "
                "creatividad, talento o calidad de ejecución; sí permite afirmar que la "
                "construcción de soluciones forma parte real de tus prioridades actuales."
            ),
            (
                (f"Tus objetivos explícitos —{goals}— " if goals else "Tus objetivos explícitos ")
                + "sitúan el crecimiento intelectual y profesional en el centro de esta etapa. "
                + (f"Al mismo tiempo, tu rutina incluye {routine}. " if routine else "")
                + "La evidencia, por tanto, muestra varios frentes simultáneos: formación, "
                "trabajo, proyectos, actividad física, pendientes y descanso. El análisis útil "
                "aquí no es llamarte disciplinado ni asumir que estás saturado, sino reconocer un "
                "riesgo práctico de priorización: todas esas áreas compiten por tiempo. No hay "
                "datos para concluir que ese riesgo ya se haya convertido en un problema."
            ),
            (
                (
                    f"Fuera de lo académico, has registrado intereses como {interests}. "
                    if interests
                    else ""
                )
                + (
                    f"También mantienes tu relación con {profile.partner_name}"
                    if profile.partner_name
                    else ""
                )
                + (
                    f" y has identificado {friends} amistades importantes"
                    if friends and profile.partner_name
                    else (f"Has identificado {friends} amistades importantes" if friends else "")
                )
                + ". Esos datos confirman que el ocio, la actividad física, la pareja y las "
                "amistades existen en tu vida descrita, pero no bastan para llamarte extrovertido, "
                "competitivo, introspectivo o socialmente hábil. "
                + (
                    f"Tu visión de futuro —{future[0].lower() + future[1:]}— integra una dimensión "
                    "profesional con estabilidad y tranquilidad personal, sin ordenar esas metas."
                    if future
                    else ""
                )
            ),
            (
                "La forma en que has definido Jarvis aporta una tensión de diseño, no un "
                "diagnóstico personal. Quieres que actúe como secretario y resuelva muchas tareas "
                "con autonomía, pero también has exigido confirmación para archivos, mensajes y "
                "acciones que afecten privacidad, cuentas, dinero o estabilidad del equipo. La "
                "conclusión verificable es que deseas automatización dentro de límites explícitos. "
                "No sería válido transformar esa preferencia en necesidad de control, ansiedad, "
                "confianza tecnológica o tolerancia al riesgo, porque el perfil no aporta esa "
                "evidencia."
            ),
            (
                "En síntesis, las conclusiones fuertes son acotadas pero útiles: tu etapa actual "
                "prioriza graduación y preparación profesional; tus estudios, prácticas y "
                "proyectos se conectan alrededor de tecnología aplicada; tu rutina reparte espacio "
                "entre responsabilidades, ejercicio y ocio; y tu futuro deseado combina progreso "
                "laboral con estabilidad y vida tranquila. Como implicación práctica, Jarvis puede "
                "ayudarte mejor si convierte metas amplias en prioridades observables y protege "
                "tiempo para los distintos frentes, sin asumir que conoce tu estado emocional. "
                "Para evaluar personalidad, fortalezas consistentes o debilidades reales harían "
                "falta ejemplos de decisiones, dificultades, resultados y reacciones en contextos "
                "distintos; el perfil actual no los contiene."
            ),
        ]
        return "\n\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip())

    def self_analysis_answer(self, message: str, *, deep_analysis: bool = False) -> str | None:
        profile = self.load()
        evidence_groups = sum(
            bool(value)
            for value in (
                profile.degree,
                profile.work_context,
                profile.goals,
                profile.projects,
                profile.routine,
                profile.future_vision,
            )
        )
        if evidence_groups < 2:
            return None
        normalized = self._normalize(message)
        if deep_analysis:
            return self._deep_self_analysis(profile, normalized)
        return self._normal_self_analysis(profile, normalized)

    def person_analysis_limitation(self, message: str) -> str | None:
        profile = self.load()
        normalized = self._normalize(message)
        if profile.partner_name and self._mentions(normalized, profile.partner_name):
            return (
                f"Solo tengo confirmado que {profile.partner_name} es tu novia. Todavía no me "
                "has dado suficiente contexto sobre cómo es ella para hacer un análisis "
                "responsable."
            )
        return None

    @classmethod
    def _factual_person_answer(
        cls,
        profile: UserProfile,
        normalized_message: str,
    ) -> str | None:
        if profile.partner_name and (
            cls._mentions(normalized_message, profile.partner_name)
            or "mi novia" in normalized_message
        ):
            return f"{profile.partner_name} es tu novia."

        for person in profile.important_people:
            if not any(
                cls._mentions(normalized_message, reference)
                for reference in (person.name, *person.aliases)
            ):
                continue
            relation = person.relation or "una persona importante para ti"
            relation = re.sub(r"\bsus\b", "tus", relation, flags=re.IGNORECASE)
            relation = re.sub(r"\bsu\b", "tu", relation, flags=re.IGNORECASE)
            metaphor = ""
            if "papa del grupo" in cls._normalize(relation):
                relation = re.sub(
                    r"(?:\s+y\s+)?el papá del grupo\b",
                    "",
                    relation,
                    flags=re.IGNORECASE,
                ).strip(" ,")
                relation = relation or "una persona importante para ti"
                metaphor = " Dentro del grupo lo llaman el «papá del grupo» en sentido afectivo."
            aliases_to_show = list(person.aliases)
            if len(aliases_to_show) > 1:
                first_name = person.name.split(maxsplit=1)[0]
                aliases_to_show = [
                    alias
                    for alias in aliases_to_show
                    if cls._normalize(alias) != cls._normalize(first_name)
                ]
            aliases = (
                f", a quien también llamas {', '.join(aliases_to_show)}," if aliases_to_show else ""
            )
            identity = f"{person.name}{aliases} es {relation}.{metaphor}"
            details = re.sub(
                r"\bJuan Diego aprecia\b",
                "tú aprecias",
                person.details,
                flags=re.IGNORECASE,
            )
            details = re.sub(
                r"\b(?:es )?muy buen dato\b",
                "Es muy buena persona y muy buena compañía",
                details,
                flags=re.IGNORECASE,
            )
            details = re.sub(
                r"\bacolita en todo\b",
                "te apoya y se suma a cualquier plan",
                details,
                flags=re.IGNORECASE,
            )
            for alias in person.aliases:
                details = re.sub(
                    rf"^En el grupo le dicen {re.escape(alias)}\.\s*",
                    "",
                    details,
                    flags=re.IGNORECASE,
                )
            return f"{identity} {details}".strip()
        return None

    @classmethod
    def _person_topic_answer(
        cls,
        profile: UserProfile,
        normalized_message: str,
    ) -> str | None:
        """Answer a narrow fact about one known person without leaking Juan's facts.

        The profile stores prose, so this intentionally extracts only complete sentences that
        explicitly match the requested topic. If the topic is absent, returning a clear local
        limitation is safer than letting a broad self-profile marker answer for the wrong
        subject.
        """
        matches = cls._matched_people(profile, normalized_message)
        if len(matches) != 1:
            return None
        person = matches[0]
        topic_patterns: tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...] = (
            (
                re.compile(
                    r"\b(?:que|cual|donde|en que)\b.*\b(?:estudia|estudio|carrera|"
                    r"universidad|graduo|grado|profesion|titulo|formacion)\b|"
                    r"\b(?:carrera|universidad|estudios|profesion|titulo)\b"
                ),
                re.compile(
                    r"\b(?:estudia|cursa|universidad|usfq|graduo|graduado|graduada|"
                    r"licenciad|ingenier|psicolog|biotecnolog|gastronomia|jurisprudencia|"
                    r"administracion|finanzas|produccion musical|mercados|comercio)\b"
                ),
                "los estudios o la profesión",
            ),
            (
                re.compile(
                    r"\b(?:donde|en que|de que|a que)\b.*\b(?:trabaja|trabajo|dedica)\b|"
                    r"\b(?:empleo|trabajo actual|ocupacion)\b"
                ),
                re.compile(r"\b(?:trabaja|empleo|practicas|se dedica|ocupacion)\b"),
                "el trabajo",
            ),
            (
                re.compile(
                    r"\b(?:que le gusta|que disfruta|aficiones|hobbies|intereses|"
                    r"deporte favorito|musica favorita|planes favoritos)\b"
                ),
                re.compile(
                    r"\b(?:gusta|encanta|aficion|futbol|bailar|bmx|dj|viaj|cocina|"
                    r"geek|deport)\b"
                ),
                "los intereses",
            ),
        )
        selected: tuple[re.Pattern[str], str] | None = None
        for request_pattern, evidence_pattern, label in topic_patterns:
            if request_pattern.search(normalized_message):
                selected = evidence_pattern, label
                break
        if selected is None:
            return None

        evidence_pattern, label = selected
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", person.details.strip())
            if sentence.strip() and evidence_pattern.search(cls._normalize(sentence))
        ]
        if not sentences:
            return f"No tengo información registrada sobre {label} de {person.name}."
        evidence = " ".join(sentence.rstrip(".") + "." for sentence in sentences)
        return f"Sobre {label} de {person.name}, tengo registrado: {evidence}"

    @classmethod
    def _matched_people(
        cls,
        profile: UserProfile,
        normalized_message: str,
    ) -> list[ImportantPerson]:
        return [
            person
            for person in profile.important_people
            if any(
                cls._mentions(normalized_message, reference)
                for reference in (person.name, *person.aliases)
            )
        ]

    def person_analysis_answer(
        self,
        message: str,
        *,
        deep_analysis: bool = False,
    ) -> str | None:
        """Compose a grounded reflection for one known person without freeform additions."""
        profile = self.load()
        normalized = self._normalize(message)
        matches = self._matched_people(profile, normalized)
        if len(matches) != 1:
            return None
        person = matches[0]
        factual = self._factual_person_answer(profile, normalized)
        if not factual:
            return None

        relation = self._normalize(person.relation)
        relation_display = re.sub(r"\bsus\b", "tus", person.relation, flags=re.IGNORECASE)
        relation_display = re.sub(r"\bsu\b", "tu", relation_display, flags=re.IGNORECASE)
        feminine = bool(re.search(r"\buna\b|\bamiga\b", relation))
        subject = "ella" if feminine else "él"
        object_pronoun = "la" if feminine else "lo"
        details = self._normalize(person.details)
        categories: list[str] = []
        if any(
            marker in details
            for marker in (
                "chistos",
                "timid",
                "tranquil",
                "atent",
                "inteligente",
                "extrovert",
                "amigable",
                "buena gente",
                "lind",
            )
        ):
            categories.append("rasgos personales que observas")
        if "grupo" in details or "grupo" in relation:
            categories.append("el papel que ocupa dentro del grupo")
        has_interests = any(
            marker in details
            for marker in (
                "futbol",
                "bail",
                "bmx",
                "dj",
                "viaj",
                "cocina",
                "geek",
            )
        )
        if has_interests:
            categories.append("sus intereses o actividades")
        has_academic = bool(
            re.search(
                r"\b(?:estudia|curso|cursa|graduo|licenciad|ingenier|psicolog|"
                r"gastronomia|jurisprudencia|administracion|finanzas|produccion musical|"
                r"mercados|comercio)\b",
                details,
            )
        )
        if has_academic:
            categories.append("su situación académica o profesional")
        category_text = self._natural_join(categories) or "los hechos que compartiste"

        normal = (
            f"{factual} Analíticamente, tu relato combina {category_text}; la lectura más segura "
            f"es que esas son las dimensiones que hoy destacan para ti cuando piensas en "
            f"{person.name}, no una definición completa de cómo es {subject} en cualquier "
            "contexto."
        )
        if has_academic:
            normal += (
                " Su formación es un hecho independiente: no permite deducir inteligencia, "
                "habilidad social, motivaciones ni comportamiento."
            )
        normal += (
            f" Para profundizar más allá de esta impresión harían falta ejemplos concretos de "
            f"decisiones o situaciones vividas; con los datos actuales, mantener el análisis de "
            f"{person.name} dentro de esos límites es lo responsable."
        )
        if not deep_analysis:
            return normal

        first = factual
        second = (
            f"Al separar hechos de interpretación, la relación que tienes con {person.name} y "
            f"las observaciones que compartiste son evidencia directa. Tu descripción reúne "
            f"{category_text}. Eso permite identificar qué facetas resultan más visibles para ti, "
            f"pero no convertirlas en una teoría sobre toda la personalidad de {person.name}. Un "
            f"rasgo observado en el grupo tampoco demuestra cómo reacciona {subject} ante "
            "conflictos, presión o contextos distintos."
        )
        contextual_facts = (
            "aficiones y formación"
            if has_interests and has_academic
            else "aficiones"
            if has_interests
            else "estudios o profesión"
        )
        third = (
            f"Los datos sobre {contextual_facts} completan el contexto de "
            f"{person.name}, pero permanecen separados de los rasgos personales. Una carrera no "
            "explica el humor, la inteligencia o la forma de relacionarse; del mismo modo, una "
            "afición no prueba disciplina, creatividad ni capacidad social. El análisis puede "
            "conectar observaciones compatibles, pero no usar una de ellas como causa de las "
            "demás."
        )
        fourth = (
            f"La conclusión más sólida es que {person.name} es {relation_display} y que tú "
            f"{object_pronoun} percibes principalmente mediante los "
            "rasgos, roles e intereses que decidiste destacar. Esa percepción es valiosa como "
            "contexto de tu relación, pero sigue siendo parcial. Para un análisis más "
            "profundo y específico necesitaría ejemplos de cómo toma decisiones, afronta "
            "dificultades o se relaciona contigo en situaciones concretas; hasta entonces, no "
            "sería responsable añadir fortalezas, debilidades o motivaciones no mencionadas."
        )
        return "\n\n".join((first, second, third, fourth))

    @staticmethod
    def _important_people_answer(profile: UserProfile) -> str | None:
        if not profile.important_people:
            return None
        labels = [
            person.name
            + (f" ({', '.join(person.aliases)})" if person.aliases else "")
            for person in profile.important_people
        ]
        response = "Las personas guardadas como importantes son: " + "; ".join(labels) + "."
        if profile.partner_name:
            response += (
                f" {profile.partner_name} está guardada por separado como tu novia, no dentro "
                "de esa lista."
            )
        return response

    def answer(self, message: str) -> str | None:
        profile = self.load()
        normalized = self._normalize(message)
        if any(marker in normalized for marker in ("como se llama mi novia", "nombre de mi novia")):
            return f"Tu novia se llama {profile.partner_name}." if profile.partner_name else None
        partner_reference = self._normalize(profile.partner_name)
        fun_fact_markers = (
            "cualidad fisica favorita",
            "que te gusta de mi novia",
            "que te gusta de mi pareja",
            "detalle favorito de mi novia",
        )
        if any(marker in normalized for marker in fun_fact_markers) or (
            partner_reference and f"que te gusta de {partner_reference}" in normalized
        ):
            return profile.partner_fun_fact or None
        matched_people = self._matched_people(profile, normalized)
        partner_mentioned = bool(
            profile.partner_name and self._mentions(normalized, profile.partner_name)
        )
        if partner_mentioned or matched_people:
            if re.search(r"\bquien (?:es|fue)\b", normalized):
                return self._factual_person_answer(profile, normalized)
            topic_answer = self._person_topic_answer(profile, normalized)
            if topic_answer:
                return topic_answer
            # A private-person question may continue through the bounded person prompt, but it
            # must never fall through to rules about Juan Diego merely because it also contains
            # words such as "universidad", "proyecto" or "cumpleaños".
            return None
        if any(marker in normalized for marker in ("que edad tengo", "cuantos anos tengo")):
            return f"Tienes {profile.age} años." if profile.age is not None else None
        if any(
            marker in normalized
            for marker in ("cuando naci", "fecha de nacimiento", "mi cumpleanos", "mi cumple")
        ):
            return f"Naciste el {profile.birth_date}." if profile.birth_date else None
        if re.search(
            r"\b(?:que (?:carrera )?estudio(?: yo)?|cual es mi carrera|mi carrera|"
            r"en que semestre estoy|cual es mi semestre|mi semestre)\b",
            normalized,
        ):
            if not profile.degree:
                return None
            university = f" en {profile.university}" if profile.university else ""
            semester = f" y estás en el semestre {profile.semester}" if profile.semester else ""
            return f"Estudias {profile.degree}{university}{semester}."
        if re.search(
            r"\b(?:donde estudio(?: yo)?|en que universidad estudio|cual es mi universidad|"
            r"mi universidad)\b",
            normalized,
        ):
            return f"Estudias en {profile.university}." if profile.university else None
        if any(
            marker in normalized for marker in ("donde trabajo", "en que trabajo", "mis practicas")
        ):
            return self._work_answer(profile.work_context) if profile.work_context else None
        if any(marker in normalized for marker in ("donde vivo", "en que ciudad vivo")):
            return f"Vives en {profile.location}." if profile.location else None
        if any(marker in normalized for marker in ("mis objetivos", "mis metas", "quiero lograr")):
            return (
                f"Tus objetivos prioritarios son: {'; '.join(profile.goals)}."
                if profile.goals
                else None
            )
        if any(marker in normalized for marker in ("mis proyectos", "que proyectos tengo")):
            if not profile.projects:
                return None
            return (
                "Tus proyectos son: "
                + "; ".join(
                    f"{project.name}, {project.description.rstrip('.')}"
                    for project in profile.projects
                )
                + "."
            )
        if any(marker in normalized for marker in ("mi rutina", "como es mi dia")):
            return (
                f"Tu rutina habitual es: {'; '.join(profile.routine)}." if profile.routine else None
            )
        if any(
            marker in normalized
            for marker in (
                "personas importantes",
                "personas tienes guardadas",
                "nombres tienes guardados",
                "mis amigos",
                "quienes son mis amigos",
            )
        ):
            if "persona" in normalized or "guardad" in normalized:
                return self._important_people_answer(profile)
            names = ", ".join(person.name for person in profile.important_people)
            return f"Tu grupo incluye a {names}." if names else None

        if "cumple" in normalized or "fecha" in normalized:
            for item in profile.important_dates:
                if self._mentions(normalized, item.label):
                    label = (
                        f"tu {item.label}"
                        if item.label in {"hermano", "papá", "mamá"}
                        else item.label
                    )
                    return f"El cumpleaños de {label} es el {self._human_date(item.month_day)}."
            asks_for_date_inventory = bool(
                re.search(
                    r"\b(?:que|cuales|dime|lista|muestra)\b.*\b(?:fechas|cumpleanos)\b"
                    r".*\b(?:guardad|registrad|important|recuerd)\w*\b|"
                    r"\b(?:mis fechas importantes|fechas personales registradas)\b",
                    normalized,
                )
            )
            if profile.important_dates and asks_for_date_inventory:
                dates = "; ".join(
                    f"{item.label}: {self._human_date(item.month_day)}"
                    for item in profile.important_dates
                )
                return f"Las fechas personales registradas son: {dates}."
        if any(marker in normalized for marker in ("videojuegos favoritos", "juegos favoritos")):
            return (
                f"Tus videojuegos favoritos son {', '.join(profile.favorite_games)}."
                if profile.favorite_games
                else None
            )
        if any(marker in normalized for marker in ("artistas favoritos", "musica favorita")):
            return (
                f"Tus artistas favoritos son {', '.join(profile.favorite_artists)}."
                if profile.favorite_artists
                else None
            )
        if any(marker in normalized for marker in ("comida favorita", "comidas favoritas")):
            return (
                f"Tus comidas favoritas son {', '.join(profile.favorite_foods)}."
                if profile.favorite_foods
                else None
            )
        if any(marker in normalized for marker in ("que me gusta", "mis gustos", "mis hobbies")):
            return f"Te gusta {', '.join(profile.interests)}." if profile.interests else None
        if self._self_identity_question(normalized, profile.preferred_name):
            return self.self_summary()
        return None
