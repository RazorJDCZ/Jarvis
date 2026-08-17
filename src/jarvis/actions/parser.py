from __future__ import annotations

import re
import unicodedata
from typing import Any

from jarvis.actions.models import ActionName, ActionPlan, ActionWorkflowPlan, BlockedIntent


def normalize_request(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"^[\W_]+|[\W_]+$", "", normalized)
    normalized = re.sub(
        r"^(?:(?:oye|hey)\s+)?jarvis(?:\b|[,:;.!?])(?:[,:;.!?\s]+)?",
        "",
        normalized,
    )
    # Typed requests commonly contain an inverted question/exclamation mark after the
    # wake word ("Jarvis, ¿qué ves?"). Strip edges again after removing the wake word;
    # Whisper transcripts normally do not expose this case, which made the mobile chat
    # behave differently from voice.
    return re.sub(r"^[\W_]+|[\W_]+$", "", normalized).strip()


class DeterministicActionParser:
    LAST_VISUAL_TARGET = "__last_visual_target__"
    _SPANISH_NUMBERS = {
        "cero": 0,
        "uno": 1,
        "un": 1,
        "dos": 2,
        "tres": 3,
        "cuatro": 4,
        "cinco": 5,
        "seis": 6,
        "siete": 7,
        "ocho": 8,
        "nueve": 9,
        "diez": 10,
        "once": 11,
        "doce": 12,
        "trece": 13,
        "catorce": 14,
        "quince": 15,
        "dieciseis": 16,
        "diecisiete": 17,
        "dieciocho": 18,
        "diecinueve": 19,
        "veinte": 20,
        "veintiuno": 21,
        "veintidos": 22,
        "veintitres": 23,
        "veinticuatro": 24,
        "veinticinco": 25,
        "veintiseis": 26,
        "veintisiete": 27,
        "veintiocho": 28,
        "veintinueve": 29,
        "treinta": 30,
        "cuarenta": 40,
        "cincuenta": 50,
        "sesenta": 60,
        "setenta": 70,
        "ochenta": 80,
        "noventa": 90,
        "cien": 100,
    }
    _COURTESY_PREFIX = re.compile(
        r"^(?:por favor,?\s+)?(?:podrias|puedes|quiero que|quisiera que|necesito que|"
        r"te pido que|me ayudas a|me puedes|serias tan amable de|hazme el favor de)\s+"
        r"(?:por favor\s+)?"
    )
    _ORIGINAL_COURTESY_PREFIX = re.compile(
        r"^(?:por favor,?\s+)?(?:podr[ií]as|puedes|quiero que|quisiera que|necesito que|"
        r"te pido que|me ayudas a|me puedes|ser[ií]as tan amable de|hazme el favor de)\s+"
        r"(?:por favor\s+)?",
        flags=re.IGNORECASE,
    )
    _INFINITIVE_COMMANDS = {
        "abrir": "abre",
        "abrirme": "abre",
        "iniciar": "inicia",
        "lanzar": "lanza",
        "buscar": "busca",
        "investigar": "busca",
        "visitar": "visita",
        "navegar": "navega",
        "entrar": "entra",
        "poner": "pon",
        "subir": "sube",
        "bajar": "baja",
        "silenciar": "silencia",
        "cerrar": "cierra",
        "maximizar": "maximiza",
        "minimizar": "minimiza",
        "restaurar": "restaura",
        "revisar": "revisa",
        "verificar": "verifica",
        "analizar": "analiza",
        "observar": "observa",
        "ver": "mira",
        "mirar": "mira",
        "leer": "lee",
        "encontrar": "encuentra",
        "localizar": "localiza",
        "organizar": "organiza",
        "acomodar": "acomoda",
        "ajustar": "ajusta",
        "comparar": "compara",
        "seleccionar": "selecciona",
        "presionar": "presiona",
        "escribir": "escribe",
        "crear": "crea",
        "agregar": "agrega",
        "anotar": "anota",
        "recordar": "recuerda",
        "recordarme": "recuerdame",
        "completar": "completa",
        "cancelar": "cancela",
        "resumir": "resume",
        "corregir": "corrige",
        "traducir": "traduce",
        "indexar": "indexa",
        "programar": "programa",
        "agendar": "agenda",
        "mostrar": "muestra",
        "mostrarme": "muestra",
        "ensenar": "muestra",
        "ensenarme": "muestra",
        "capturar": "captura",
        "guardar": "guarda",
        "apagar": "apaga",
        "reiniciar": "reinicia",
        "borrar": "borra",
        "eliminar": "elimina",
        "formatear": "formatea",
        "comprar": "compra",
        "pagar": "paga",
        "transferir": "transfiere",
    }
    _CONJUGATED_COMMANDS = {
        "abras": "abre",
        "abrieras": "abre",
        "inicies": "inicia",
        "iniciaras": "inicia",
        "lanzaras": "lanza",
        "busques": "busca",
        "buscaras": "busca",
        "subas": "sube",
        "subieras": "sube",
        "bajes": "baja",
        "bajaras": "baja",
        "silencies": "silencia",
        "cierres": "cierra",
        "cerraras": "cierra",
        "maximices": "maximiza",
        "minimices": "minimiza",
        "restaures": "restaura",
        "escribas": "escribe",
        "muestres": "muestra",
        "captures": "captura",
        "guardes": "guarda",
        "revises": "revisa",
        "verifiques": "verifica",
        "observes": "observa",
        "mires": "mira",
        "leas": "lee",
        "encuentres": "encuentra",
        "localices": "localiza",
        "organices": "organiza",
        "acomodes": "acomoda",
        "gestiones": "gestiona",
        "ajustes": "ajusta",
        "compares": "compara",
        "configures": "configura",
        "selecciones": "selecciona",
        "presiones": "presiona",
        "digas": "dime",
        "crees": "crea",
        "agregues": "agrega",
        "anotes": "anota",
        "recuerdes": "recuerdame",
        "completes": "completa",
        "canceles": "cancela",
        "resumas": "resume",
        "corrijas": "corrige",
        "traduzcas": "traduce",
        "indexes": "indexa",
        "programes": "programa",
        "agendes": "agenda",
    }
    _META_PREFIXES = (
        "explica ",
        "por que ",
        "que pasaria ",
        "si te digo ",
        "cuando diga ",
        "no ",
    )
    _COMPUTER_DOMAINS = re.compile(
        r"\b(?:computadora|ordenador|pc|sistema|escritorio|monitor(?:es)?|pantalla(?:s)?|"
        r"display(?:s)?|ventana(?:s)?|aplicacion(?:es)?|apps?|programa(?:s)?|navegador|"
        r"chrome|edge|brave|pestana(?:s)?|pagina|sitio|web|internet|google|archivo(?:s)?|"
        r"carpeta(?:s)?|portapapeles|volumen|audio|sonido|microfono|teclado|cursor|boton|"
        r"control(?:es)?|dialogo|mensaje|error|recordatorio(?:s)?|agenda|calendario|"
        r"tarea(?:s)?|inbox|bandeja de entrada|focus|"
        r"appa|biblioteca|conocimiento|adjunto(?:s)?|receta(?:s)?|skill(?:s)?|permiso(?:s)?|"
        r"workspace|proyecto|codigo|pruebas?|juego(?:s)?|steam|epic|camara)\b"
    )
    _REQUEST_SIGNALS = re.compile(
        r"\b(?:puedes|podrias|quiero|quisiera|necesito|haz|hazme|ayudame|ayudas|"
        r"gustaria|agradeceria|importaria|dime|muestrame|cuentame|revisa|verifica|"
        r"analiza|analices|averigua|comprueba|"
        r"observa|mira|encuentra|localiza|abre|cierra|busca|escribe|lee|sube|baja|"
        r"cambia|pon|quita|organiza|acomoda|deja|llevame|entra|ve|visita|navega|"
        r"selecciona|presiona|pulsa|clic|captura|describe|organiza|organices|ordenar|"
        r"ordena|ordenes|acomoda|acomodes|gestiona|gestiones|ajusta|ajustes|prepara|"
        r"prepares|configura|configures|crea|agrega|anota|recuerdame|completa|cancela|"
        r"resume|explica|corrige|traduce|indexa|programa|agenda|ejecuta|guarda)\b"
    )
    _NATURAL_GOAL = re.compile(
        r"^(?:me gustaria|quisiera|preferiria|te agradeceria|seria genial si|"
        r"me vendria bien|ayudame a|me ayudas a)\b.*\b(?:"
        r"abrir|usar|tener|dejar|poner|escuchar|reproducir|buscar|investigar|"
        r"visitar|revisar|verificar|mirar|ver|leer|escribir|organizar|acomodar|"
        r"ajustar|configurar|comparar|cerrar|cambiar|seleccionar|encontrar|localizar"
        r")\b"
    )
    _VISUAL_REFERENCE = re.compile(
        r"\b(?:monitor(?:es)?|pantalla(?:s)?|display(?:s)?|lo que (?:ves|aparece)|"
        r"contexto visual|imagen de (?:la )?pantalla)\b"
    )
    _VISUAL_OBSERVATION = re.compile(
        r"\b(?:ves|viendo|ver|observa|observar|mira|mirar|describe|describir|aparece|"
        r"muestra|mostrando|hay|tengo abierto|se ve|lee|leer|revisa|revisar|"
        r"echa(?:le)? (?:un )?vistazo|fijate|analiza|analizar|analices)\b"
    )
    _IMPLICIT_VISUAL = re.compile(
        r"^(?:(?:puedes|podrias)\s+)?(?:"
        r"que (?:estas viendo|ves|tengo abierto|aparece ahi|hay ahi)|"
        r"mira(?: esto| ahi)?|observa(?: esto| ahi)?|fijate(?: en esto| ahi)?|"
        r"echale (?:un )?vistazo(?: a esto)?|puedes ver (?:esto|lo que tengo abierto)"
        r")(?:\b|$)"
    )
    _ACTION_PREFIXES = (
        "abre",
        "inicia",
        "lanza",
        "ejecuta",
        "ve a",
        "entra",
        "navega",
        "visita",
        "busca",
        "haz clic",
        "presiona",
        "escribe",
        "teclea",
        "sube",
        "baja",
        "aumenta",
        "reduce",
        "pon el volumen",
        "configura",
        "compara",
        "organiza",
        "acomoda",
        "ajusta",
        "revisa",
        "verifica",
        "analiza",
        "observa",
        "lee",
        "selecciona",
        "localiza",
        "silencia",
        "quita el silencio",
        "reproduce",
        "pausa",
        "maximiza",
        "minimiza",
        "restaura",
        "cierra",
        "cambia a",
        "enfoca",
        "lista",
        "muestra",
        "toma una captura",
        "captura la pantalla",
        "crea",
        "agrega",
        "anota",
        "recuerdame",
        "programa",
        "agenda",
        "completa",
        "cancela",
        "resume",
        "corrige",
        "traduce",
        "indexa",
        "desplaza",
        "presiona",
        "muestra el escritorio",
        "lee el portapapeles",
        "copia al portapapeles",
        "mira",
        "describe",
        "encuentra visualmente",
        "ponme",
        "buscame",
        "llevame",
        "quiero",
        "necesito",
        "deja",
    )
    _EMBEDDED_ACTION_VERBS = (
        "abrir",
        "abrirme",
        "abras",
        "abrieras",
        "iniciar",
        "inicies",
        "lanzar",
        "buscar",
        "busques",
        "buscaras",
        "investigar",
        "subir",
        "subas",
        "bajar",
        "bajes",
        "bajaras",
        "silenciar",
        "silencies",
        "cerrar",
        "cierres",
        "maximizar",
        "maximices",
        "minimizar",
        "minimices",
        "restaurar",
        "restaures",
        "crear",
        "crees",
        "agregar",
        "agregues",
        "anotar",
        "anotes",
        "recordar",
        "recordarme",
        "recuerdes",
        "completar",
        "completes",
        "cancelar",
        "canceles",
        "resumir",
        "resumas",
        "corregir",
        "corrijas",
        "traducir",
        "traduzcas",
        "indexar",
        "indexes",
        "programar",
        "programes",
        "agendar",
        "agendes",
        "mostrar",
        "muestres",
        "capturar",
        "captures",
        "guardar",
        "guardes",
        "visitar",
        "navegar",
        "entrar",
        "dejar",
        "dejarme",
        "llevame",
        "llevarme",
        "apagar",
        "reiniciar",
        "borrar",
        "eliminar",
        "formatear",
        "comprar",
        "pagar",
        "transferir",
    )
    _WEBSITES = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
        "whatsapp": "https://web.whatsapp.com",
        "wikipedia": "https://es.wikipedia.org",
        "reddit": "https://www.reddit.com",
        "chatgpt": "https://chatgpt.com",
        "openai": "https://openai.com",
        "google maps": "https://maps.google.com",
        "drive": "https://drive.google.com",
        "linkedin": "https://www.linkedin.com",
        "instagram": "https://www.instagram.com",
        "facebook": "https://www.facebook.com",
        "x": "https://x.com",
        "twitter": "https://x.com",
        "netflix": "https://www.netflix.com",
        "spotify web": "https://open.spotify.com",
    }
    _BROWSERS = {
        "brave": "brave",
        "brave browser": "brave",
        "chrome": "chrome",
        "google chrome": "chrome",
        "edge": "edge",
        "microsoft edge": "edge",
        "navegador predeterminado": "default",
    }
    _APPS = {
        "calculadora": "calculator",
        "calculator": "calculator",
        "calc": "calculator",
        "bloc de notas": "notepad",
        "block de notas": "notepad",
        "notepad": "notepad",
        "note pad": "notepad",
        "explorador": "explorer",
        "explorador de archivos": "explorer",
        "paint": "paint",
        "configuracion": "settings",
        "ajustes": "settings",
        "administrador de tareas": "task_manager",
        "recortes": "snipping_tool",
        "herramienta recortes": "snipping_tool",
        "mapa de caracteres": "character_map",
    }
    _HOTKEYS = {
        "copia": "copy",
        "copiar": "copy",
        "pega": "paste",
        "pegar": "paste",
        "deshaz": "undo",
        "deshacer": "undo",
        "rehaz": "redo",
        "rehacer": "redo",
        "guarda": "save",
        "guardar": "save",
        "selecciona todo": "select_all",
    }

    @staticmethod
    def _plan(action: ActionName, **arguments: Any) -> ActionPlan:
        return ActionPlan(name=action, arguments=arguments)

    @staticmethod
    def _task_arguments(value: str) -> dict[str, Any] | None:
        """Extract bounded Appa metadata without treating arbitrary prose as a date."""

        title = value.strip(" ,.;")
        arguments: dict[str, Any] = {}
        priority = re.search(
            r"(?:[,;]?\s+)(?:con\s+)?prioridad\s+(baja|media|alta)\b",
            title,
        )
        if priority is not None:
            arguments["priority"] = priority.group(1)
            title = (title[: priority.start()] + title[priority.end() :]).strip(" ,.;")
        category = re.search(
            r"(?:[,;]?\s+)(?:en\s+)?categor(?:ia|izada como)\s+"
            r"(universidad|personal|trabajo|finanzas|salud|otros)\b",
            title,
        )
        if category is not None:
            arguments["category"] = category.group(1)
            title = (title[: category.start()] + title[category.end() :]).strip(" ,.;")

        temporal = (
            r"(?:hoy|manana)(?:\s+a\s+las?\s+\d{1,2}(?::\d{2})?)?|"
            r"en\s+\d{1,5}\s+(?:minutos?|horas?|dias?)|"
            r"el\s+\d{1,2}(?:\s+de\s+[a-z]+)?"
            r"(?:\s+a\s+las?\s+\d{1,2}(?::\d{2})?)?|"
            r"\d{4}-\d{2}-\d{2}(?:[t ]\d{2}:\d{2}(?::\d{2})?(?:z|[+-]\d{2}:\d{2})?)?"
        )
        reminder = re.search(
            rf"(?:[,;]?\s+)(?:con\s+)?recordatorio(?:\s+para)?\s+(?P<when>{temporal})$",
            title,
        )
        if reminder is not None:
            arguments["reminder_at"] = reminder.group("when")
            title = title[: reminder.start()].strip(" ,.;")
        due = re.search(
            rf"(?:[,;]?\s+)(?:para|vence(?:\s+el)?|con\s+fecha(?:\s+para)?)\s+"
            rf"(?P<when>{temporal})$",
            title,
        )
        if due is None:
            due = re.search(rf"(?:[,;]?\s+)(?P<when>{temporal})$", title)
        if due is not None:
            arguments["due"] = due.group("when")
            title = title[: due.start()].strip(" ,.;")
        title = re.sub(r"\s+", " ", title)
        if not title:
            return None
        return {"title": title, **arguments}

    @staticmethod
    def _extract_monitor(command: str) -> tuple[str | None, str]:
        display = r"(?:monitor|pantalla|display)"
        displays = r"(?:monitores|pantallas|displays)"
        number = (
            r"(?:primer|primero|primera|segundo|segunda|tercer|tercero|tercera|"
            r"cuarto|cuarta|quinto|quinta|uno|una|dos|tres|cuatro|cinco|\d{1,2})"
        )
        references = (
            (rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:todas|todos) (?:mis |los |las )?{displays}", "all"),
            (rf"(?<!\w)(?:(?:en|de|a)\s+)?amb[oa]s? {displays}", "all"),
            (rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:mis |los |las )?dos {displays}", "all"),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?cada (?:uno de )?(?:los |mis )?{displays}",
                "all",
            ),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*{display}\s+principal",
                "primary",
            ),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*{display}\s+"
                r"(?:de la\s+)?izquierda",
                "left",
            ),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*{display}\s+"
                r"(?:de la\s+)?derecha",
                "right",
            ),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*{display}\s+"
                rf"(?:numero\s+)?({number})",
                None,
            ),
            (
                rf"(?<!\w)(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*({number})\s+{display}",
                None,
            ),
        )
        ordinals = {
            "primer": "1",
            "primero": "1",
            "primera": "1",
            "uno": "1",
            "una": "1",
            "segundo": "2",
            "segunda": "2",
            "dos": "2",
            "tercer": "3",
            "tercero": "3",
            "tercera": "3",
            "tres": "3",
            "cuarto": "4",
            "cuarta": "4",
            "cuatro": "4",
            "quinto": "5",
            "quinta": "5",
            "cinco": "5",
        }
        for pattern, fixed in references:
            match = re.search(pattern, command)
            if match is None:
                continue
            raw = match.group(1) if match.lastindex else fixed
            monitor = fixed or ordinals.get(raw, raw)
            cleaned = f"{command[: match.start()]} {command[match.end() :]}"
            return monitor, re.sub(r"\s+", " ", cleaned).strip(" ,")
        return None, command

    @staticmethod
    def workflow_parts(text: str) -> list[str]:
        parts: list[str] = []
        start = 0
        quoted = False
        index = 0
        while index < len(text):
            character = text[index]
            if character in {'"', "“"}:
                quoted = not quoted
            elif character == "”":
                quoted = False
            if not quoted:
                connector = re.match(
                    r"\s+(?:(?:y\s+)?(?:luego|después|despues|además|ademas)|y)\s+",
                    text[index:],
                    flags=re.IGNORECASE,
                )
                if connector:
                    parts.append(text[start:index].strip())
                    index += connector.end()
                    start = index
                    continue
            index += 1
        parts.append(text[start:].strip())
        return [part for part in parts if part]

    @classmethod
    def _is_meta_request(cls, command: str) -> bool:
        """Distinguish an immediate goal from explanations, hypotheticals and negations."""
        if command.startswith(cls._META_PREFIXES):
            return True
        if re.match(
            r"^(?:explicame|cuentame (?:como|por que)|ensename (?:como|a))\b",
            command,
        ):
            return True
        if re.match(
            r"^(?:explica(?:me)?|cuenta(?:me)?|ensena(?:me)?|muestra(?:me)?|dime) como\b",
            command,
        ):
            return True
        if re.match(
            r"^como (?:puedo|podria|se puede|debo|deberia|haria|hago|hacer|abrir|cerrar|"
            r"buscar|usar|configurar|cambiar|subir|bajar|eliminar|instalar)\b",
            command,
        ):
            return True
        if re.match(
            r"^(?:quiero|quisiera|me gustaria) "
            r"(?:(?:hablar|conversar|charlar) (?:sobre|de)|"
            r"(?:saber|entender|aprender) como)\b",
            command,
        ):
            return True
        return bool(
            re.search(
                r"\b(?:no quiero|no necesito|no hace falta|sin que|algun dia|"
                r"si pudieras|seria genial si|en teoria|hipoteticamente)\b",
                command,
            )
        )

    def has_agent_intent(self, text: str) -> bool:
        """Broad, local gate for requests that deserve semantic tool planning.

        This is deliberately domain based instead of phrase based. The model still has to
        return a typed allow-listed plan, so admitting a candidate here cannot execute an
        arbitrary instruction.
        """
        command = self._canonical_command(text)
        if not command or self._is_meta_request(command):
            return False
        if command.startswith(self._ACTION_PREFIXES):
            return True
        if self._NATURAL_GOAL.search(command):
            return True
        if self._embedded_direct_command(text) or self._natural_search(text):
            return True
        if self._IMPLICIT_VISUAL.search(command):
            return True
        if self._VISUAL_REFERENCE.search(command) and (
            self._VISUAL_OBSERVATION.search(command)
            or re.match(r"^(?:que|cual|donde|cuanto|dime|puedes|podrias)\b", command)
        ):
            return True
        return bool(
            self._COMPUTER_DOMAINS.search(command)
            and (
                self._REQUEST_SIGNALS.search(command)
                or re.match(r"^(?:que|cual|donde|cuanto|como esta|en cuanto)\b", command)
            )
        )

    def looks_action_like(self, text: str) -> bool:
        """Backward-compatible alias for the semantic agent-intent gate."""
        return self.has_agent_intent(text)

    def looks_visual(self, text: str) -> bool:
        command = self._canonical_command(text)
        return bool(
            command
            and not self._is_meta_request(command)
            and (self._VISUAL_REFERENCE.search(command) or self._IMPLICIT_VISUAL.search(command))
            and (
                self._VISUAL_OBSERVATION.search(command)
                or re.match(r"^(?:que|cual|donde|cuanto|dime|puedes|podrias)\b", command)
            )
        )

    @classmethod
    def _embedded_direct_command(cls, text: str) -> str:
        """Extract a direct computer request that follows conversational context."""
        normalized = normalize_request(text)
        if cls._is_meta_request(normalized):
            return ""
        verbs = "|".join(cls._EMBEDDED_ACTION_VERBS)
        request = re.search(
            rf"\b(?:"
            rf"(?:me\s+)?(?:puedes|podrias)(?:\s+ayudar(?:me)?\s+a)?|"
            rf"quiero\s+que|quisiera\s+que|necesito\s+que|me\s+gustaria\s+que|"
            rf"te\s+agradeceria\s+que|te\s+pido\s+que|me\s+ayudas\s+a|"
            rf"me\s+ayudarias\s+a|ayudame\s+a|serias\s+tan\s+amable\s+de|"
            rf"me\s+harias\s+el\s+favor\s+de|te\s+importaria"
            rf")\s+(?:por\s+favor\s+)?(?P<request>(?:{verbs})\b.+)$",
            normalized,
        )
        if request is None:
            request = re.search(
                r"\b(?:quiero|quisiera|necesito|me gustaria)\s+"
                r"(?P<request>(?:tener|dejar) .+ abiert[oa])$",
                normalized,
            )
        if request is None and not normalized.startswith(cls._ACTION_PREFIXES):
            request = re.search(
                r"(?:[,;.!][\s¿¡]*|\by\s+)(?P<request>(?:"
                r"abre|me abres|inicia|lanza|busca|investiga|visita|navega|entra|ve a|"
                r"llevame a|sube|baja|silencia|maximiza|minimiza|restaura|cierra|"
                r"muestra|captura|pon|reproduce|revisa|verifica|analiza|observa|mira|"
                r"lee|organiza|acomoda|ajusta|configura|selecciona|presiona"
                r")\b.+)$",
                normalized,
            )
        return request.group("request").strip() if request is not None else ""

    @classmethod
    def _natural_search(cls, text: str) -> tuple[str, str] | None:
        """Recognize goal-oriented web searches embedded in natural Spanish."""
        normalized = normalize_request(text)
        if cls._is_meta_request(normalized):
            return None
        if re.search(r"\b(?:visualmente|pantalla|monitor|display)\b", normalized) and re.search(
            r"\b(?:boton|icono|control|elemento|enlace|mensaje|error)\b",
            normalized,
        ):
            return None

        browsers = "|".join(
            sorted((re.escape(name) for name in cls._BROWSERS), key=len, reverse=True)
        )
        browser_match = re.search(
            rf"\s+(?:en|usando|con|desde|a traves de)\s+(?:el navegador\s+)?"
            rf"(?P<browser>{browsers})\s*$",
            normalized,
        )
        browser = cls._BROWSERS[browser_match.group("browser")] if browser_match else ""
        without_browser = (
            normalized[: browser_match.start()].rstrip(" ,.;")
            if browser_match is not None
            else normalized
        )

        direct = re.search(
            r"\b(?:"
            r"(?:me\s+)?(?:puedes|podrias)(?:\s+ayudar(?:me)?\s+a)?|"
            r"quiero\s+que|quisiera\s+que|necesito\s+que|me\s+gustaria\s+que|"
            r"te\s+agradeceria\s+que|te\s+pido\s+que|me\s+ayudas\s+a|"
            r"me\s+ayudarias\s+a|ayudame\s+a|serias\s+tan\s+amable\s+de|"
            r"me\s+harias\s+el\s+favor\s+de|te\s+importaria"
            r")\s+(?:por\s+favor\s+)?"
            r"(?:dar(?:me)?\s+|estar\s+|(?:me\s+)?ayudar(?:as|me)?\s+a\s+)?"
            r"(?:buscar|buscando|busques|buscaras|encontrar|encontrando|encuentres|"
            r"investigar|investigues)"
            r"\s*(?P<query>.*)$",
            without_browser,
        )
        if direct is None:
            return None

        query = direct.group("query").strip(" ,.;")
        query = re.sub(r"^(?:me\s+)?(?:unos?|unas?|algunos?|algunas?)\s+", "", query)
        context = re.sub(
            r"[\s,.;:¿¡!?]+$",
            "",
            without_browser[: direct.start()],
        )
        topic_match = re.search(
            r"\b(?:estoy|ando)(?:\s+muy)?\s+interesad[oa]\s+en\s+(.+)$",
            context,
        )
        if topic_match is not None:
            topic = topic_match.group(1).strip(" ,.;")
            generic_query = normalize_request(query)
            if (
                not generic_query
                or generic_query in {"eso", "esto", "algo", "opciones", "resultados"}
                or generic_query.startswith(
                    ("opciones ", "resultados ", "alternativas ", "algunos ", "algunas ")
                )
                or len(generic_query.split()) <= 2
            ):
                query = topic
        query = re.sub(r"\s+por favor$", "", query).strip()
        if not query:
            return None
        return query, browser

    @classmethod
    def _canonical_command(cls, text: str) -> str:
        command = normalize_request(text)
        if cls._is_meta_request(command):
            return command
        command = re.sub(r"[,;:]?\s+por favor$", "", command).strip()
        command = re.sub(r"^por favor[,;:]?\s+", "", command).strip()
        # Whisper occasionally joins a short command with its article ("dime el" ->
        # "dimel"). Correct only bounded imperative prefixes so free conversation remains
        # untouched.
        command = re.sub(r"^dimel\s+", "dime el ", command)
        command = cls._COURTESY_PREFIX.sub("", command)
        colloquial_prefixes = (
            (r"^me abres\s+", "abre "),
            (r"^me dejes abiert[oa]\s+(?:la |el )?", "abre "),
            (r"^me dejes (?:la |el )?(.+?) abiert[oa]$", r"abre \1"),
            (r"^buscame\s+", "busca "),
            (r"^ponme\s+", "pon "),
            (r"^llevame a\s+", "ve a "),
            (r"^ensename\s+", "muestra "),
        )
        for pattern, replacement in colloquial_prefixes:
            command = re.sub(pattern, replacement, command)
        canonical_verbs = cls._INFINITIVE_COMMANDS | cls._CONJUGATED_COMMANDS
        for source_verb, imperative in canonical_verbs.items():
            if command.startswith("me " + source_verb + " "):
                return imperative + command[len(source_verb) + 3 :]
            if command == source_verb:
                return imperative
            if command.startswith(source_verb + " "):
                return imperative + command[len(source_verb) :]
        return command

    @classmethod
    def _number_value(cls, value: str) -> int | None:
        normalized = normalize_request(value)
        if normalized.isdigit():
            return int(normalized)
        direct = cls._SPANISH_NUMBERS.get(normalized)
        if direct is not None:
            return direct
        tens, separator, units = normalized.partition(" y ")
        if not separator:
            return None
        tens_value = cls._SPANISH_NUMBERS.get(tens)
        units_value = cls._SPANISH_NUMBERS.get(units)
        if tens_value not in {30, 40, 50, 60, 70, 80, 90} or units_value is None:
            return None
        return tens_value + units_value

    def parse(self, text: str) -> ActionPlan | ActionWorkflowPlan | BlockedIntent | None:
        command = self._canonical_command(text)
        if not command or self._is_meta_request(command):
            return None

        if re.fullmatch(
            r"(?:abre|inicia|lanza|ejecuta) (?:el )?"
            r"(?:powershell|cmd|terminal|simbolo del sistema)",
            command,
        ):
            return BlockedIntent("No ejecuto terminales ni comandos arbitrarios por voz.")
        if re.match(
            r"^(?:apaga|reinicia) (?:la |el )?(?:computadora|pc|maquina|sistema)|"
            r"^(?:borra|elimina|formatea) |^(?:compra|paga|transfiere) ",
            command,
        ):
            return BlockedIntent(
                "Esa operación está bloqueada porque puede causar pérdida de datos o dinero."
            )

        if re.fullmatch(
            r"(?:lista|muestra|dime|cuales son|que) (?:mis |las )?(?:recetas|skills)"
            r"(?: disponibles)?",
            command,
        ):
            return self._plan(ActionName.SKILL_LIST)
        skill_run = re.fullmatch(
            r"(?:ejecuta|inicia|usa|corre) (?:la )?(?:receta|skill) (.+)",
            command,
        )
        if skill_run:
            return self._plan(
                ActionName.SKILL_RUN,
                skill=re.sub(r"\s+", "_", skill_run.group(1).strip()),
                parameters={},
            )

        if re.fullmatch(
            r"(?:lista|muestra|dime|cuales son|que) (?:mis |las )?"
            r"(?:tareas|pendientes)(?: (?:de|en) appa)?",
            command,
        ):
            return self._plan(ActionName.TASK_LIST)
        task_create = re.fullmatch(
            r"(?:crea|agrega|anota) (?:una )?tarea(?: en appa)?(?: para)? (.+)",
            command,
        )
        if task_create:
            task_arguments = self._task_arguments(task_create.group(1))
            if task_arguments is not None:
                return self._plan(ActionName.TASK_CREATE, **task_arguments)
        task_complete = re.fullmatch(
            r"(?:completa|termina|marca como completada) (?:la )?tarea (.+)",
            command,
        )
        if task_complete:
            return self._plan(ActionName.TASK_COMPLETE, task=task_complete.group(1))

        if re.fullmatch(
            r"(?:lista|muestra|dime|cuales son|que) (?:mis |los )?proyectos de appa",
            command,
        ):
            return self._plan(ActionName.PROJECT_LIST)
        project_create = re.fullmatch(
            r"(?:crea|agrega) (?:un )?proyecto(?: en appa)?(?: llamado)? (.+)",
            command,
        )
        if project_create:
            return self._plan(ActionName.PROJECT_CREATE, name=project_create.group(1))

        if re.fullmatch(
            r"(?:lista|muestra|dime|que tengo en) (?:mi |la )?"
            r"(?:agenda|calendario)(?: de appa)?(?: hoy)?",
            command,
        ):
            return self._plan(ActionName.CALENDAR_LIST)
        calendar_create = re.fullmatch(
            r"(?:crea|agrega|programa|agenda) (?:un |una )?(?:evento|cita|reunion) "
            r"(?P<title>.+?) (?P<start>"
            r"en \d+ (?:minutos?|horas?|dias?)|"
            r"(?:hoy|manana) a las? \d{1,2}(?::\d{2})?|"
            r"el \d{1,2}(?: de [a-z]+)? a las? \d{1,2}(?::\d{2})?|"
            r"a las? \d{1,2}(?::\d{2})?)",
            command,
        )
        if calendar_create:
            return self._plan(
                ActionName.CALENDAR_CREATE,
                title=calendar_create.group("title"),
                start_at=calendar_create.group("start"),
            )

        if re.fullmatch(
            r"(?:lista|muestra|dime|que hay en) (?:mi |el )?"
            r"(?:inbox|bandeja de entrada)(?: de appa)?",
            command,
        ):
            return self._plan(ActionName.INBOX_LIST)
        inbox_capture = re.fullmatch(
            r"(?:guarda|captura|anota) (?:en )?(?:mi |el )?"
            r"(?:inbox|bandeja de entrada)(?: de appa)?(?: que)? (.+)|"
            r"(?:guarda|captura|anota) (.+) en (?:mi |el )?"
            r"(?:inbox|bandeja de entrada)(?: de appa)?",
            command,
        )
        if inbox_capture:
            text = next(group for group in inbox_capture.groups() if group)
            return self._plan(ActionName.INBOX_CAPTURE, text=text)

        if re.fullmatch(
            r"(?:estado de|como va|dime) (?:mi |la )?(?:sesion )?focus(?: de appa)?",
            command,
        ):
            return self._plan(ActionName.FOCUS_STATUS)
        focus_start = re.fullmatch(
            r"(?:inicia|empieza|comienza) (?:una )?(?:sesion de )?focus"
            r"(?: en appa)?(?: de)? (\d{1,3}) minutos?"
            r"(?: (?:para|con la tarea) (.+))?",
            command,
        )
        if focus_start:
            arguments: dict[str, Any] = {
                "duration_minutes": int(focus_start.group(1))
            }
            if focus_start.group(2):
                arguments["task_title"] = focus_start.group(2)
            return self._plan(ActionName.FOCUS_START, **arguments)

        if re.fullmatch(
            r"(?:lista|muestra|dime|cuales son|que) (?:mis |los )?recordatorios"
            r"(?: activos)?",
            command,
        ):
            return self._plan(ActionName.REMINDER_LIST)
        # Match recurrence before a one-shot clock time. Otherwise a phrase such as
        # "recuérdame revisar la agenda cada mes a las 9" is greedily interpreted as
        # a non-recurring reminder whose title happens to contain "cada mes".
        recurring_reminder = re.fullmatch(
            r"recuerdame(?: que)? (.+?) (cada dia|cada semana|cada mes)"
            r"(?: a las? (\d{1,2}(?::\d{2})?))?",
            command,
        )
        if recurring_reminder:
            recurrence = {
                "cada dia": "daily",
                "cada semana": "weekly",
                "cada mes": "monthly",
            }[recurring_reminder.group(2)]
            hour = recurring_reminder.group(3) or "09:00"
            return self._plan(
                ActionName.REMINDER_CREATE,
                title=recurring_reminder.group(1),
                due=f"hoy a las {hour}",
                recurrence=recurrence,
            )
        reminder_create = re.fullmatch(
            r"recuerdame(?: que)? (?P<title>.+?) (?P<due>"
            r"en \d+ (?:minutos?|horas?|dias?)|"
            r"(?:hoy|manana)(?: a las? \d{1,2}(?::\d{2})?)?|"
            r"el \d{1,2}(?: de [a-z]+)?(?: a las? \d{1,2}(?::\d{2})?)?|"
            r"a las? \d{1,2}(?::\d{2})?)",
            command,
        )
        if reminder_create is None:
            reminder_create = re.fullmatch(
                r"recuerdame (?P<due>en \d+ (?:minutos?|horas?|dias?)|"
                r"(?:hoy|manana)(?: a las? \d{1,2}(?::\d{2})?)?) "
                r"(?:que )?(?P<title>.+)",
                command,
            )
        if reminder_create:
            return self._plan(
                ActionName.REMINDER_CREATE,
                title=reminder_create.group("title"),
                due=reminder_create.group("due"),
                recurrence="none",
            )
        reminder_cancel = re.fullmatch(
            r"(?:cancela|elimina|borra) (?:el )?recordatorio (.+)",
            command,
        )
        if reminder_cancel:
            return self._plan(ActionName.REMINDER_CANCEL, reminder=reminder_cancel.group(1))

        if re.fullmatch(
            r"(?:lista|muestra|dime) (?:las )?(?:fuentes|documentos) "
            r"(?:de|en) (?:mi )?biblioteca",
            command,
        ):
            return self._plan(ActionName.KNOWLEDGE_LIST)
        knowledge_search = re.fullmatch(
            r"(?:busca|consulta|investiga) (?:en )?(?:mi )?biblioteca(?: sobre)? (.+)|"
            r"(?:busca|consulta) (.+) en (?:mi )?biblioteca",
            command,
        )
        if knowledge_search:
            return self._plan(
                ActionName.KNOWLEDGE_SEARCH,
                query=next(group for group in knowledge_search.groups() if group),
            )
        if command in {
            "guarda este adjunto en mi biblioteca",
            "indexa este adjunto",
            "agrega este documento a mi biblioteca",
        }:
            return self._plan(ActionName.KNOWLEDGE_ADD_ATTACHMENT, attachment_id="latest")
        if re.fullmatch(
            r"(?:lista|muestra|dime|que) (?:mis |los )?adjuntos(?: tengo)?",
            command,
        ):
            return self._plan(ActionName.ATTACHMENT_LIST)

        clipboard_analysis = re.fullmatch(
            r"(resume|explica|corrige|traduce) (?:lo que (?:copie|esta copiado)|"
            r"el contenido de )?\s*(?:en )?(?:mi )?portapapeles(?: al ([a-z]+))?",
            command,
        )
        if clipboard_analysis:
            operation = {
                "resume": "summarize",
                "explica": "explain",
                "corrige": "correct",
                "traduce": "translate",
            }[clipboard_analysis.group(1)]
            arguments: dict[str, Any] = {"operation": operation}
            if clipboard_analysis.group(2):
                arguments["language"] = clipboard_analysis.group(2)
            return self._plan(ActionName.CLIPBOARD_ANALYZE, **arguments)

        if re.fullmatch(
            r"(?:lista|muestra|dime) (?:los )?(?:permisos|permisos recordados)",
            command,
        ):
            return self._plan(ActionName.PERMISSION_LIST)
        forget_permission = re.fullmatch(
            r"(?:olvida|borra|elimina) (?:el )?permiso (.+)",
            command,
        )
        if forget_permission:
            return self._plan(ActionName.PERMISSION_FORGET, action=forget_permission.group(1))

        if re.fullmatch(
            r"(?:lista|muestra|dime) (?:los )?(?:workspaces|proyectos autorizados)",
            command,
        ):
            return self._plan(ActionName.DEV_LIST)
        dev_inspect = re.fullmatch(
            r"(?:lee|revisa|inspecciona) (?:el archivo )?(.+?) "
            r"(?:del|en el) (?:proyecto|workspace) (.+)",
            command,
        )
        if dev_inspect:
            return self._plan(
                ActionName.DEV_INSPECT,
                path=dev_inspect.group(1),
                workspace=dev_inspect.group(2),
            )
        dev_search = re.fullmatch(
            r"busca (.+?) (?:en|dentro de) (?:el )?(?:proyecto|workspace) (.+)",
            command,
        )
        if dev_search:
            return self._plan(
                ActionName.DEV_SEARCH,
                query=dev_search.group(1),
                workspace=dev_search.group(2),
            )
        dev_test = re.fullmatch(
            r"(?:ejecuta|corre) (?:las )?pruebas (?:del|en el) "
            r"(?:proyecto|workspace) (.+)",
            command,
        )
        if dev_test:
            return self._plan(ActionName.DEV_TEST, workspace=dev_test.group(1))

        if re.fullmatch(
            r"(?:lista|muestra|dime) (?:mis |los )?(?:juegos|juegos instalados)",
            command,
        ):
            return self._plan(ActionName.GAME_LIST)
        game_launch = re.fullmatch(
            r"(?:abre|inicia|lanza|juega) (?:el juego )?(.+)",
            command,
        )
        if game_launch and any(
            marker in command for marker in ("el juego", "juega ", " desde steam", " desde epic")
        ):
            return self._plan(ActionName.GAME_LAUNCH, game=game_launch.group(1))

        if command in {
            "cual es el monitor 1 y cual es el monitor 2",
            "dime cual es el monitor 1 y cual es el monitor 2",
            "como estan definidos el monitor 1 y el monitor 2",
        }:
            return self._plan(ActionName.SCREEN_LIST)

        natural_search = self._natural_search(text)
        if natural_search is not None:
            query, browser = natural_search
            arguments: dict[str, Any] = {"query": query}
            if browser:
                arguments["browser"] = browser
            return self._plan(ActionName.BROWSER_SEARCH, **arguments)

        embedded_command = self._embedded_direct_command(text)
        if embedded_command and embedded_command != command:
            return self.parse(embedded_command)

        original = re.sub(
            r"^(?:(?:oye|hey)\s+)?jarvis[,:;.!?\s]+",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        )
        original = self._ORIGINAL_COURTESY_PREFIX.sub("", original)
        original = re.sub(r"[,;:]?\s+por favor[.!?]*$", "", original, flags=re.IGNORECASE)
        canonical_verbs = self._INFINITIVE_COMMANDS | self._CONJUGATED_COMMANDS
        for source_verb, imperative in canonical_verbs.items():
            if original.casefold().startswith(source_verb + " "):
                original = imperative + original[len(source_verb) :]
                break
        workflow_parts = self.workflow_parts(original)
        if 2 <= len(workflow_parts) <= 5:
            steps: list[ActionPlan] = []
            for part in workflow_parts:
                parsed_part = self.parse(part)
                if isinstance(parsed_part, BlockedIntent):
                    return parsed_part
                if isinstance(parsed_part, ActionWorkflowPlan):
                    steps.extend(parsed_part.steps)
                elif isinstance(parsed_part, ActionPlan):
                    steps.append(parsed_part)
                else:
                    steps = []
                    break
            if len(steps) == len(workflow_parts):
                return ActionWorkflowPlan(tuple(steps))
        path_match = re.fullmatch(
            r"abre (?:la |el )?(carpeta|archivo) [\"“]?(.+?)[\"”]?",
            original,
            re.IGNORECASE,
        )
        if path_match:
            name = (
                ActionName.PATH_OPEN_FOLDER
                if path_match.group(1).casefold() == "carpeta"
                else ActionName.PATH_OPEN
            )
            return self._plan(name, path=path_match.group(2))

        leave_open = re.fullmatch(
            r"(?:deja|dejar|dejarme) (?:la |el )?(.+?) abiert[oa]",
            command,
        )
        if leave_open:
            target = leave_open.group(1).strip()
            if target in self._WEBSITES:
                return self._plan(ActionName.BROWSER_OPEN, url=self._WEBSITES[target])
            return self._plan(ActionName.APP_OPEN, app=self._APPS.get(target, target))

        if command in {"atras", "volver atras", "pagina anterior"}:
            return self._plan(ActionName.BROWSER_BACK)
        if command in {"adelante", "pagina siguiente"}:
            return self._plan(ActionName.BROWSER_FORWARD)
        if command in {"recarga la pagina", "actualiza la pagina", "refresca la pagina"}:
            return self._plan(ActionName.BROWSER_REFRESH)
        browser_new_tab = re.fullmatch(
            r"(?:abre )?(?:una )?(?:nueva pestana|pestana nueva|pestana) "
            r"(?:en|usando|con) "
            r"(?:el navegador )?(google chrome|chrome|microsoft edge|edge|"
            r"brave browser|brave|navegador predeterminado)",
            command,
        )
        if browser_new_tab:
            return self._plan(
                ActionName.BROWSER_NEW_TAB,
                browser=self._BROWSERS[browser_new_tab.group(1)],
            )
        if command in {
            "abre una pestana",
            "abre una nueva pestana",
            "abre una pestana nueva",
            "nueva pestana",
            "pestana nueva",
        }:
            return self._plan(ActionName.BROWSER_NEW_TAB)
        if command in {"lista las pestanas", "muestra las pestanas", "que pestanas estan abiertas"}:
            return self._plan(ActionName.BROWSER_LIST_TABS)
        switch_tab = re.fullmatch(r"(?:cambia|ve) a la pestana (.+)", command)
        if switch_tab:
            return self._plan(ActionName.BROWSER_SWITCH_TAB, target=switch_tab.group(1))
        if command in {"cierra la pestana", "cierra la pestana actual"}:
            return self._plan(ActionName.BROWSER_CLOSE_TAB)
        if command in {"lee la pagina", "resume la pagina", "que dice la pagina"}:
            return self._plan(ActionName.BROWSER_READ)
        result = re.fullmatch(
            r"abre (?:el )?(primer|primero|segundo|tercer|tercero|cuarto|quinto|\d{1,2}) resultado",
            command,
        )
        if result:
            indexes = {
                "primer": 1,
                "primero": 1,
                "segundo": 2,
                "tercer": 3,
                "tercero": 3,
                "cuarto": 4,
                "quinto": 5,
            }
            return self._plan(
                ActionName.BROWSER_OPEN_RESULT,
                index=indexes.get(
                    result.group(1), int(result.group(1)) if result.group(1).isdigit() else 1
                ),
            )

        if command in {
            "lista los monitores",
            "lista las pantallas",
            "muestra los monitores",
            "muestra las pantallas",
            "define los monitores",
            "define las pantallas",
            "identifica los monitores",
            "identifica las pantallas",
            "como estan definidos los monitores",
            "cual es el monitor 1 y cual es el monitor 2",
            "que monitores hay",
            "que monitores estan conectados",
            "que pantallas hay",
            "cuantos monitores hay",
        }:
            return self._plan(ActionName.SCREEN_LIST)

        if re.fullmatch(
            r"(?:que|cual|cuanto|dime|indica|consulta|revisa|verifica|"
            r"a cuanto|en cuanto|como esta) "
            r"(?:(?:esta|es|tengo|hay|se encuentra) )?"
            r"(?:el )?(?:volumen|nivel de (?:volumen|audio|sonido))"
            r"(?: (?:actual|actualmente|del sistema|de la computadora|de mi pc))?",
            command,
        ):
            return self._plan(ActionName.VOLUME_GET)
        if re.fullmatch(
            r"(?:dime|indica(?:me)?) (?:cual es|en cuanto esta|a cuanto esta) "
            r"(?:el )?(?:volumen|nivel de (?:volumen|audio|sonido))"
            r"(?: (?:actual|del sistema|de la computadora|de mi pc))?",
            command,
        ):
            return self._plan(ActionName.VOLUME_GET)

        if command in {
            "que hay en cada monitor",
            "que hay en cada pantalla",
            "que ves en cada monitor",
            "que ves en cada pantalla",
            "que aparece en cada monitor",
            "que aparece en cada pantalla",
            "describe cada monitor",
            "describe cada pantalla",
            "describe ambos monitores",
            "describe las dos pantallas",
            "dime que hay en cada monitor",
            "dime que hay en cada pantalla",
            "dime que tengo en cada monitor",
            "dime que tengo en cada pantalla",
        }:
            return self._plan(ActionName.SCREEN_DESCRIBE, monitor="all")

        monitor, screen_command = self._extract_monitor(command)
        visual_reference = monitor is not None or bool(
            self._VISUAL_REFERENCE.search(command) or self._IMPLICIT_VISUAL.search(command)
        )
        visual_command = re.sub(
            r"\b(?:(?:en|de|a)\s+)?(?:el|la|mi)?\s*(?:monitor|pantalla|display)\b",
            " ",
            screen_command,
        )
        visual_command = re.sub(r"\s+", " ", visual_command).strip(" ,")
        general_visual_description = bool(
            re.fullmatch(
                r"(?:(?:dime|cuentame|explicame|muestrame|puedes decirme|"
                r"me puedes decir)\s+)?"
                r"(?:(?:que(?: es)?(?: lo que)?|como)\s+)?"
                r"(?:ves|puedes ver|hay|aparece|se muestra|se ve|tengo abierto|"
                r"esta abierto|esta apareciendo|tienes a la vista)",
                visual_command,
            )
            or re.fullmatch(
                r"(?:mira|observa|describe|revisa|fijate|"
                r"echa(?:rle|le)? (?:un )?vistazo)"
                r"(?: (?:esto|ahi|lo que tengo abierto)| a esto)?"
                r"(?: y (?:dime|cuentame|contame|contarme|cuenta|describe) "
                r"(?:que (?:ves|hay|aparece|se muestra)|lo que (?:ves|hay|aparece)))?",
                visual_command,
            )
        )
        if visual_reference and (
            general_visual_description
            or screen_command
            in {
                "que ves en la pantalla",
                "que hay en la pantalla",
                "que aparece en la pantalla",
                "que estas viendo",
                "describe la pantalla",
                "describe lo que ves",
                "describe lo que ves en la pantalla",
                "dime que ves en la pantalla",
                "mira la pantalla",
                "que ves",
                "que hay",
                "que aparece",
                "describe",
                "dime que ves",
                "dime que hay",
                "dime que aparece",
                "mira",
            }
        ):
            return self._plan(
                ActionName.SCREEN_DESCRIBE,
                **({"monitor": monitor} if monitor is not None else {}),
            )
        screen_ask = re.fullmatch(
            r"(?:mira|observa)(?: la pantalla)? y (?:dime|responde) (.+)|"
            r"(?:segun|usando) (?:la pantalla|lo que ves),? (.+)",
            screen_command,
        )
        if screen_ask:
            return self._plan(
                ActionName.SCREEN_ASK,
                question=next(group for group in screen_ask.groups() if group),
                **({"monitor": monitor} if monitor is not None else {}),
            )
        screen_find = re.fullmatch(
            r"(?:encuentra|busca|localiza|ubica)(?: visualmente)? (.+)|"
            r"donde esta (.+) en (?:la )?pantalla",
            screen_command,
        )
        if screen_find and (
            monitor is not None or "visualmente" in screen_command or "pantalla" in screen_command
        ):
            return self._plan(
                ActionName.SCREEN_FIND,
                target=next(group for group in screen_find.groups() if group),
                **({"monitor": monitor} if monitor is not None else {}),
            )
        screen_click = re.fullmatch(
            r"(?:haz )?clic visualmente en (.+)|"
            r"(?:haz )?clic en (?:la )?pantalla (?:en )?(.+)",
            screen_command,
        )
        if screen_click or (
            monitor is not None
            and (screen_click := re.fullmatch(r"(?:haz )?clic en (.+)", screen_command))
        ):
            return self._plan(
                ActionName.SCREEN_CLICK,
                target=next(group for group in screen_click.groups() if group),
                **({"monitor": monitor} if monitor is not None else {}),
            )
        if screen_command in {
            "haz clic ahi",
            "haz clic en eso",
            "haz clic en ese boton",
            "haz clic en el boton que mencionaste",
            "pulsa ahi",
            "pulsa ese boton",
            "presiona ahi",
            "presiona ese boton",
        }:
            return self._plan(
                ActionName.SCREEN_CLICK,
                target=self.LAST_VISUAL_TARGET,
                **({"monitor": monitor} if monitor is not None else {}),
            )
        if monitor is not None and re.match(
            r"^(?:que|cual|donde|puedes leer|lee|dime)\b",
            visual_command,
        ):
            return self._plan(
                ActionName.SCREEN_ASK,
                question=visual_command,
                monitor=monitor,
            )
        if visual_reference and re.match(
            r"^(?:que|cual|donde|cuanto|como|puedes|podrias|lee|dime|revisa|verifica)\b",
            visual_command,
        ):
            return self._plan(
                ActionName.SCREEN_ASK,
                question=visual_command,
                **({"monitor": monitor} if monitor is not None else {}),
            )

        browser_search = re.fullmatch(
            r"(?:busca|buscar|investiga) (?:en (?:google|internet|la web) )?(.+?) "
            r"(?:en|usando|con) (?:el navegador )?(google chrome|chrome|"
            r"microsoft edge|edge|brave browser|brave|navegador predeterminado)",
            command,
        )
        if browser_search:
            return self._plan(
                ActionName.BROWSER_SEARCH,
                query=browser_search.group(1),
                browser=self._BROWSERS[browser_search.group(2)],
            )

        search = re.fullmatch(
            r"(?:busca|buscar|investiga) (?:en (?:google|internet|la web) )?(.+?)(?: en google)?",
            command,
        )
        if search:
            return self._plan(ActionName.BROWSER_SEARCH, query=search.group(1))

        browser_navigation = re.fullmatch(
            r"(?:abre|ve a|entra a|navega a|visita) "
            r"(?:la pagina |el sitio |la web de )?(.+?) "
            r"(?:en|usando|con) (?:el navegador )?(google chrome|chrome|"
            r"microsoft edge|edge|brave browser|brave|navegador predeterminado)",
            command,
        )
        if browser_navigation:
            target = browser_navigation.group(1).strip()
            browser = self._BROWSERS[browser_navigation.group(2)]
            if target in self._WEBSITES:
                return self._plan(
                    ActionName.BROWSER_OPEN,
                    url=self._WEBSITES[target],
                    browser=browser,
                )
            if target.startswith(("http://", "https://", "www.")) or "." in target:
                return self._plan(ActionName.BROWSER_OPEN, url=target, browser=browser)

        navigation = re.fullmatch(
            r"(?:abre|ve a|entra a|navega a|visita) (?:la pagina |el sitio |la web de )?(.+)",
            command,
        )
        if navigation:
            target = navigation.group(1).removesuffix(" por favor").strip()
            if target in self._WEBSITES:
                return self._plan(ActionName.BROWSER_OPEN, url=self._WEBSITES[target])
            if target.startswith(("http://", "https://", "www.")) or "." in target:
                return self._plan(ActionName.BROWSER_OPEN, url=target)

        point = re.fullmatch(r"(?:haz )?clic en (\d{1,5})[ ,]+(\d{1,5})", command)
        if point:
            return self._plan(
                ActionName.POINTER_CLICK,
                x=int(point.group(1)),
                y=int(point.group(2)),
            )

        ui_click = re.fullmatch(r"(?:haz )?clic en (?:el )?control (.+)", command)
        if ui_click:
            return self._plan(ActionName.UI_CLICK, target=ui_click.group(1))

        browser_click = re.fullmatch(
            r"(?:haz )?clic (?:en|sobre) (?:el boton |el enlace )?(.+)",
            command,
        )
        if browser_click:
            target = re.sub(
                r" en (?:el navegador|la pagina)$",
                "",
                browser_click.group(1),
            )
            return self._plan(ActionName.BROWSER_CLICK, target=target)

        fill = re.fullmatch(
            r"(?:escribe|ingresa|pon) (.+?) en (?:el )?campo (.+)",
            command,
        )
        if fill:
            return self._plan(ActionName.BROWSER_FILL, text=fill.group(1), field=fill.group(2))

        if command in {
            "que aplicaciones puedes abrir",
            "que apps puedes abrir",
            "lista aplicaciones",
            "lista las aplicaciones",
            "lista aplicaciones instaladas",
            "lista las aplicaciones instaladas",
            "muestra las aplicaciones instaladas",
        }:
            return self._plan(ActionName.APP_LIST)

        app = re.fullmatch(
            r"(?:abre|inicia|lanza|ejecuta) (?:la |el )?(.+?)(?: por favor)?",
            command,
        )
        if app:
            target = app.group(1).strip()
            return self._plan(ActionName.APP_OPEN, app=self._APPS.get(target, target))

        volume_set = re.fullmatch(
            r"(?:pon|ajusta|establece) (?:el )?volumen (?:al|a) "
            r"(.+?)(?: por ciento|%)?",
            command,
        )
        if volume_set:
            level = self._number_value(volume_set.group(1))
            if level is not None:
                return self._plan(ActionName.VOLUME_SET, level=level)
        volume_change = re.fullmatch(
            r"(?:sube|aumenta|incrementa|subele|baja|reduce|disminuye|bajale) "
            r"(?:un poco )?(?:el )?volumen(?: (\d{1,3})(?: por ciento|%)?)?",
            command,
        )
        if volume_change:
            direction = -1 if command.startswith(("baja", "reduce", "disminuye", "bajale")) else 1
            step = int(volume_change.group(1) or 5) * direction
            return self._plan(ActionName.VOLUME_CHANGE, step=step)
        if re.fullmatch(r"(?:silencia|mutea) (?:el )?(?:audio|sonido|volumen)", command):
            return self._plan(ActionName.VOLUME_MUTE, muted=True)
        if re.fullmatch(
            r"(?:(?:quita|desactiva) (?:el )?silencio|"
            r"(?:desmutea|activa) (?:el )?(?:audio|sonido))(?: del sistema)?",
            command,
        ):
            return self._plan(ActionName.VOLUME_MUTE, muted=False)
        if command in {"reproduce o pausa", "reproduce", "pausa", "play pause"}:
            return self._plan(ActionName.MEDIA_PLAY_PAUSE)
        if command in {"siguiente cancion", "siguiente pista", "pon la siguiente"}:
            return self._plan(ActionName.MEDIA_NEXT)
        if command in {"cancion anterior", "pista anterior", "pon la anterior"}:
            return self._plan(ActionName.MEDIA_PREVIOUS)
        if command in {"deten la musica", "deten la reproduccion", "stop"}:
            return self._plan(ActionName.MEDIA_STOP)

        if command in {
            "lista las ventanas",
            "lista las ventanas abiertas",
            "muestra ventanas",
            "muestra las ventanas",
            "muestra las ventanas abiertas",
            "que ventanas estan abiertas",
        }:
            return self._plan(ActionName.WINDOW_LIST)
        if command in {
            "que ventana esta activa",
            "cual es la ventana actual",
            "que ventana tengo activa",
            "que aplicacion esta activa",
            "que aplicacion tengo abierta",
            "que tengo abierto en primer plano",
            "dime la ventana activa",
            "dime cual ventana esta activa",
            "dime cual es la ventana activa",
        }:
            return self._plan(ActionName.WINDOW_CURRENT)
        window_focus = re.fullmatch(
            r"(?:cambia a|enfoca|activa|trae al frente) (?:la ventana de |la ventana )?(.+)",
            command,
        )
        if window_focus:
            return self._plan(ActionName.WINDOW_FOCUS, title=window_focus.group(1))
        for verb, action_name in (
            ("minimiza", ActionName.WINDOW_MINIMIZE),
            ("maximiza", ActionName.WINDOW_MAXIMIZE),
            ("restaura", ActionName.WINDOW_RESTORE),
            ("cierra", ActionName.WINDOW_CLOSE),
        ):
            match = re.fullmatch(
                rf"{verb}(?: (?:(?:la|esta) )?ventana(?: de)?(?: (.+))?)?",
                command,
            )
            if match:
                return self._plan(action_name, title=(match.group(1) or "").strip())

        if command in {"inspecciona la pantalla", "muestra los controles", "que controles ves"}:
            return self._plan(ActionName.UI_INSPECT)
        type_text = re.fullmatch(
            r"(?:escribe|teclea) [\"“](.+)[\"”]",
            original,
            re.IGNORECASE,
        )
        if type_text:
            return self._plan(ActionName.UI_TYPE, text=type_text.group(1))
        if command in self._HOTKEYS:
            return self._plan(ActionName.UI_HOTKEY, hotkey=self._HOTKEYS[command])
        key = re.fullmatch(
            r"presiona (enter|intro|escape|esc|tab|shift tab|arriba|abajo|"
            r"izquierda|derecha|espacio|retroceso)",
            command,
        )
        if key:
            key_names = {
                "intro": "enter",
                "esc": "escape",
                "shift tab": "shift_tab",
                "arriba": "up",
                "abajo": "down",
                "izquierda": "left",
                "derecha": "right",
                "espacio": "space",
                "retroceso": "backspace",
            }
            return self._plan(ActionName.UI_KEY, key=key_names.get(key.group(1), key.group(1)))

        scroll = re.fullmatch(r"(?:desplaza|haz scroll) (arriba|abajo)(?: (\d{1,3}))?", command)
        if scroll:
            amount = int(scroll.group(2) or 5) * (1 if scroll.group(1) == "arriba" else -1)
            return self._plan(ActionName.POINTER_SCROLL, amount=amount)
        if command in {"toma una captura", "toma una captura de pantalla", "captura la pantalla"}:
            return self._plan(ActionName.SCREENSHOT_TAKE)
        if command in {"muestra el escritorio", "ve al escritorio"}:
            return self._plan(ActionName.DESKTOP_SHOW)
        if command in {
            "estado del sistema",
            "estado actual del sistema",
            "como esta la computadora",
            "como esta mi computadora",
            "como esta mi pc",
            "dime el estado del sistema",
            "revisa el estado del sistema",
            "uso del sistema",
            "uso actual del sistema",
            "uso de cpu y memoria",
            "cuanto cpu y memoria estoy usando",
            "uso de disco",
            "cuanto espacio libre tengo",
            "cuanto espacio libre tengo en el disco",
            "cuanta memoria disponible tengo",
            "estado de la bateria",
            "dime el uso de cpu memoria y disco",
        }:
            return self._plan(ActionName.SYSTEM_STATUS)
        if command in {"lee el portapapeles", "que hay en el portapapeles"}:
            return self._plan(ActionName.CLIPBOARD_READ)
        clipboard_write = re.fullmatch(
            r"(?:copia|pon) [\"“](.+)[\"”] (?:al|en el) portapapeles",
            original,
            re.IGNORECASE,
        )
        if clipboard_write:
            return self._plan(ActionName.CLIPBOARD_WRITE, text=clipboard_write.group(1))

        return None
