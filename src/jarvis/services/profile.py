from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class UserProfile:
    preferred_name: str = ""
    birth_date: str = ""
    partner_name: str = ""
    partner_fun_fact: str = ""
    degree: str = ""
    semester: int | None = None
    location: str = ""
    interests: tuple[str, ...] = ()

    @property
    def age(self) -> int | None:
        try:
            born = date.fromisoformat(self.birth_date)
        except ValueError:
            return None
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    def system_context(self) -> str:
        facts: list[str] = []
        if self.preferred_name:
            facts.append(f"Su nombre preferido es {self.preferred_name}.")
        if self.birth_date:
            age = self.age
            age_text = f"; actualmente tiene {age} años" if age is not None else ""
            facts.append(f"Nació el {self.birth_date}{age_text}.")
        if self.partner_name:
            facts.append(f"Su novia se llama {self.partner_name}.")
        if self.partner_fun_fact:
            facts.append(
                f"Dato cariñoso privado sobre su novia: {self.partner_fun_fact} "
                "No lo menciones fuera de un contexto claramente pertinente."
            )
        if self.degree:
            semester = " y cursa el noveno semestre" if self.semester == 9 else ""
            if self.semester not in {None, 9}:
                semester = f" y cursa el semestre {self.semester}"
            facts.append(f"Estudia {self.degree}{semester}.")
        if self.location:
            facts.append(f"Vive en {self.location}.")
        if self.interests:
            facts.append(f"Le gusta {', '.join(self.interests)}.")
        return "\n".join(f"- {fact}" for fact in facts)


class LocalProfileStore:
    _MAX_BYTES = 16_384
    _TEXT_FIELDS = (
        "preferred_name",
        "birth_date",
        "partner_name",
        "partner_fun_fact",
        "degree",
        "location",
    )

    def __init__(self, path: Path) -> None:
        self.path = path

    @staticmethod
    def _short_text(data: dict[str, Any], name: str, maximum: int = 500) -> str:
        value = data.get(name, "")
        if not isinstance(value, str):
            return ""
        return value.strip()[:maximum]

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
        raw_interests = raw.get("interests", [])
        interests = (
            tuple(
                item.strip()[:120]
                for item in raw_interests[:20]
                if isinstance(item, str) and item.strip()
            )
            if isinstance(raw_interests, list)
            else ()
        )
        return UserProfile(**text, semester=semester, interests=interests)

    def system_context(self) -> str:
        return self.load().system_context()

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

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
        if any(marker in normalized for marker in ("que edad tengo", "cuantos anos tengo")):
            return f"Tienes {profile.age} años." if profile.age is not None else None
        if any(
            marker in normalized
            for marker in ("cuando naci", "fecha de nacimiento", "cumpleanos")
        ):
            return f"Naciste el {profile.birth_date}." if profile.birth_date else None
        if any(marker in normalized for marker in ("que estudio", "que carrera", "semestre")):
            if not profile.degree:
                return None
            semester = f" y estás en el semestre {profile.semester}" if profile.semester else ""
            return f"Estudias {profile.degree}{semester}."
        if any(marker in normalized for marker in ("donde vivo", "en que ciudad vivo")):
            return f"Vives en {profile.location}." if profile.location else None
        if any(marker in normalized for marker in ("que me gusta", "mis gustos", "mis hobbies")):
            return f"Te gusta {', '.join(profile.interests)}." if profile.interests else None
        if any(marker in normalized for marker in ("que sabes de mi", "sobre mi", "quien soy")):
            parts: list[str] = []
            if profile.preferred_name:
                parts.append(f"Te llamas {profile.preferred_name}")
            if profile.age is not None:
                parts.append(f"tienes {profile.age} años")
            if profile.location:
                parts.append(f"vives en {profile.location}")
            if profile.degree:
                parts.append(f"estudias {profile.degree}")
            if profile.semester:
                semester = "noveno" if profile.semester == 9 else str(profile.semester)
                parts.append(f"cursas el {semester} semestre")
            if profile.partner_name:
                parts.append(f"tu novia se llama {profile.partner_name}")
            if profile.interests:
                parts.append(f"te gusta {', '.join(profile.interests)}")
            if not parts:
                return None
            sentence = ", ".join(parts)
            return sentence[0].upper() + sentence[1:] + "."
        return None
