from __future__ import annotations

import re
import unicodedata
from typing import Any

from jarvis.actions.models import ActionName, ActionPlan, ActionWorkflowPlan, BlockedIntent


def normalize_request(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"\s+", " ", normalized).strip(" \t\r\n¿¡.,;:!?")
    return re.sub(r"^(?:(?:oye|hey)\s+)?jarvis[,:;.!?\s]+", "", normalized)


class DeterministicActionParser:
    LAST_VISUAL_TARGET = "__last_visual_target__"
    _COURTESY_PREFIX = re.compile(
        r"^(?:por favor,?\s+)?(?:podrias|puedes|quiero que|quisiera que|necesito que|"
        r"te pido que|me ayudas a|me puedes|serias tan amable de|hazme el favor de)\s+"
    )
    _ORIGINAL_COURTESY_PREFIX = re.compile(
        r"^(?:por favor,?\s+)?(?:podr[ií]as|puedes|quiero que|quisiera que|necesito que|"
        r"te pido que|me ayudas a|me puedes|ser[ií]as tan amable de|hazme el favor de)\s+",
        flags=re.IGNORECASE,
    )
    _INFINITIVE_COMMANDS = {
        "abrir": "abre",
        "iniciar": "inicia",
        "lanzar": "lanza",
        "subir": "sube",
        "bajar": "baja",
        "silenciar": "silencia",
        "cerrar": "cierra",
        "maximizar": "maximiza",
        "minimizar": "minimiza",
        "restaurar": "restaura",
        "escribir": "escribe",
        "mostrar": "muestra",
        "capturar": "captura",
    }
    _CONJUGATED_COMMANDS = {
        "abras": "abre",
        "subas": "sube",
        "bajes": "baja",
        "silencies": "silencia",
        "cierres": "cierra",
        "maximices": "maximiza",
        "minimices": "minimiza",
        "restaures": "restaura",
        "escribas": "escribe",
        "muestres": "muestra",
        "captures": "captura",
    }
    _META_PREFIXES = (
        "como ",
        "explica ",
        "por que ",
        "que pasaria ",
        "si te digo ",
        "cuando diga ",
        "no ",
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
    def _plan(name: ActionName, **arguments: Any) -> ActionPlan:
        return ActionPlan(name=name, arguments=arguments)

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
                    r"\s+(?:(?:y\s+)?(?:luego|después|despues)|y)\s+",
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

    def looks_action_like(self, text: str) -> bool:
        command = self._canonical_command(text)
        if command.startswith(self._META_PREFIXES):
            return False
        return command.startswith(self._ACTION_PREFIXES)

    @classmethod
    def _canonical_command(cls, text: str) -> str:
        command = normalize_request(text)
        if command.startswith(cls._META_PREFIXES):
            return command
        command = re.sub(r"[,;:]?\s+por favor$", "", command).strip()
        command = cls._COURTESY_PREFIX.sub("", command)
        colloquial_prefixes = (
            (r"^me abres\s+", "abre "),
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

    def parse(self, text: str) -> ActionPlan | BlockedIntent | None:
        command = self._canonical_command(text)
        if not command or command.startswith(self._META_PREFIXES):
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
        if 2 <= len(workflow_parts) <= 3:
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

        if command in {"atras", "volver atras", "pagina anterior"}:
            return self._plan(ActionName.BROWSER_BACK)
        if command in {"adelante", "pagina siguiente"}:
            return self._plan(ActionName.BROWSER_FORWARD)
        if command in {"recarga la pagina", "actualiza la pagina", "refresca la pagina"}:
            return self._plan(ActionName.BROWSER_REFRESH)
        if command in {"abre una pestana", "abre una nueva pestana", "nueva pestana"}:
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
            "que ves en la pantalla",
            "que hay en la pantalla",
            "que aparece en la pantalla",
            "que estas viendo",
            "describe la pantalla",
            "describe lo que ves",
            "describe lo que ves en la pantalla",
            "dime que ves en la pantalla",
            "mira la pantalla",
        }:
            return self._plan(ActionName.SCREEN_DESCRIBE)
        screen_ask = re.fullmatch(
            r"(?:mira|observa) la pantalla y (?:dime|responde) (.+)|"
            r"(?:segun|usando) (?:la pantalla|lo que ves),? (.+)",
            command,
        )
        if screen_ask:
            return self._plan(
                ActionName.SCREEN_ASK,
                question=next(group for group in screen_ask.groups() if group),
            )
        screen_find = re.fullmatch(
            r"(?:encuentra|localiza|ubica) visualmente (.+)|"
            r"donde esta (.+) en (?:la )?pantalla",
            command,
        )
        if screen_find:
            return self._plan(
                ActionName.SCREEN_FIND,
                target=next(group for group in screen_find.groups() if group),
            )
        screen_click = re.fullmatch(
            r"(?:haz )?clic visualmente en (.+)|"
            r"(?:haz )?clic en (?:la )?pantalla (?:en )?(.+)",
            command,
        )
        if screen_click:
            return self._plan(
                ActionName.SCREEN_CLICK,
                target=next(group for group in screen_click.groups() if group),
            )
        if command in {"haz clic ahi", "haz clic en eso", "pulsa ahi", "presiona ahi"}:
            return self._plan(ActionName.SCREEN_CLICK, target=self.LAST_VISUAL_TARGET)

        search = re.fullmatch(
            r"(?:busca|buscar|investiga) (?:en (?:google|internet|la web) )?(.+?)(?: en google)?",
            command,
        )
        if search:
            return self._plan(ActionName.BROWSER_SEARCH, query=search.group(1))

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

        app = re.fullmatch(
            r"(?:abre|inicia|lanza|ejecuta) (?:la |el )?(.+?)(?: por favor)?",
            command,
        )
        if app:
            target = app.group(1).strip()
            return self._plan(ActionName.APP_OPEN, app=self._APPS.get(target, target))

        volume_set = re.fullmatch(
            r"(?:pon|ajusta|establece) (?:el )?volumen (?:al|a) (\d{1,3})(?: por ciento|%)?",
            command,
        )
        if volume_set:
            return self._plan(ActionName.VOLUME_SET, level=int(volume_set.group(1)))
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
            r"(?:quita|desactiva) (?:el )?silencio|(?:desmutea|activa) (?:el )?(?:audio|sonido)",
            command,
        ):
            return self._plan(ActionName.VOLUME_MUTE, muted=False)
        if command in {"que volumen hay", "cual es el volumen", "dime el volumen"}:
            return self._plan(ActionName.VOLUME_GET)

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
            "muestra ventanas",
            "muestra las ventanas",
            "que ventanas estan abiertas",
        }:
            return self._plan(ActionName.WINDOW_LIST)
        if command in {"que ventana esta activa", "cual es la ventana actual"}:
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
            match = re.fullmatch(rf"{verb}(?: (?:la )?ventana(?: de)?(?: (.+))?)?", command)
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
        if command in {"estado del sistema", "como esta la computadora", "uso del sistema"}:
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
