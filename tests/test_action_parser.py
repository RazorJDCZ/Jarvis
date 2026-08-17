from __future__ import annotations

import pytest

from jarvis.actions.models import ActionName, ActionWorkflowPlan, BlockedIntent
from jarvis.actions.parser import DeterministicActionParser, normalize_request


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        ("abre la calculadora", ActionName.APP_OPEN, {"app": "calculator"}),
        ("¿Podrías abrir la calculadora?", ActionName.APP_OPEN, {"app": "calculator"}),
        ("¿Podrías abrir la calculadora, por favor?", ActionName.APP_OPEN, {"app": "calculator"}),
        ("¿Podrías por favor abrir la calculadora?", ActionName.APP_OPEN, {"app": "calculator"}),
        ("¿Te importaría abrirme la calculadora?", ActionName.APP_OPEN, {"app": "calculator"}),
        ("Me abres el bloc de notas por favor", ActionName.APP_OPEN, {"app": "notepad"}),
        ("Necesito que abras Paint", ActionName.APP_OPEN, {"app": "paint"}),
        ("Quiero que subas el volumen", ActionName.VOLUME_CHANGE, {"step": 5}),
        ("Ponme el volumen al 35%", ActionName.VOLUME_SET, {"level": 35}),
        (
            "Búscame restaurantes italianos",
            ActionName.BROWSER_SEARCH,
            {"query": "restaurantes italianos"},
        ),
        ("Llévame a OpenAI", ActionName.BROWSER_OPEN, {"url": "https://openai.com"}),
        ("Quiero que me muestres las ventanas", ActionName.WINDOW_LIST, {}),
        ("Oye Jarvis, inicia calc por favor", ActionName.APP_OPEN, {"app": "calculator"}),
        ("lanza el block de notas", ActionName.APP_OPEN, {"app": "notepad"}),
        ("abre note pad", ActionName.APP_OPEN, {"app": "notepad"}),
        ("abre el explorador de archivos", ActionName.APP_OPEN, {"app": "explorer"}),
        ("abre paint", ActionName.APP_OPEN, {"app": "paint"}),
        ("abre spotify", ActionName.APP_OPEN, {"app": "spotify"}),
        ("abre la aplicación Discord", ActionName.APP_OPEN, {"app": "aplicacion discord"}),
        ("abre youtube", ActionName.BROWSER_OPEN, {"url": "https://www.youtube.com"}),
        (
            "abre YouTube en Google Chrome",
            ActionName.BROWSER_OPEN,
            {"url": "https://www.youtube.com", "browser": "chrome"},
        ),
        (
            "visita github.com usando Microsoft Edge",
            ActionName.BROWSER_OPEN,
            {"url": "github.com", "browser": "edge"},
        ),
        (
            "busca restaurantes en Chrome",
            ActionName.BROWSER_SEARCH,
            {"query": "restaurantes", "browser": "chrome"},
        ),
        (
            "abre una nueva pestaña en Brave",
            ActionName.BROWSER_NEW_TAB,
            {"browser": "brave"},
        ),
        ("ve a openai.com", ActionName.BROWSER_OPEN, {"url": "openai.com"}),
        ("busca en google clima en Quito", ActionName.BROWSER_SEARCH, {"query": "clima en quito"}),
        ("volver atrás", ActionName.BROWSER_BACK, {}),
        ("página siguiente", ActionName.BROWSER_FORWARD, {}),
        ("recarga la página", ActionName.BROWSER_REFRESH, {}),
        ("abre una nueva pestaña", ActionName.BROWSER_NEW_TAB, {}),
        ("lista las pestañas", ActionName.BROWSER_LIST_TABS, {}),
        ("cambia a la pestaña GitHub", ActionName.BROWSER_SWITCH_TAB, {"target": "github"}),
        ("cierra la pestaña actual", ActionName.BROWSER_CLOSE_TAB, {}),
        ("lee la página", ActionName.BROWSER_READ, {}),
        ("abre el segundo resultado", ActionName.BROWSER_OPEN_RESULT, {"index": 2}),
        ("qué ves en la pantalla", ActionName.SCREEN_DESCRIBE, {}),
        ("describe lo que ves en la pantalla", ActionName.SCREEN_DESCRIBE, {}),
        ("dime qué ves en la pantalla", ActionName.SCREEN_DESCRIBE, {}),
        (
            "mira la pantalla y dime cuántas ventanas hay",
            ActionName.SCREEN_ASK,
            {"question": "cuantas ventanas hay"},
        ),
        (
            "encuentra visualmente el botón aceptar",
            ActionName.SCREEN_FIND,
            {"target": "el boton aceptar"},
        ),
        (
            "haz clic visualmente en el icono de configuración",
            ActionName.SCREEN_CLICK,
            {"target": "el icono de configuracion"},
        ),
        ("haz clic en Aceptar", ActionName.BROWSER_CLICK, {"target": "aceptar"}),
        ("haz clic en el control Guardar", ActionName.UI_CLICK, {"target": "guardar"}),
        (
            "escribe Juandi en el campo Nombre",
            ActionName.BROWSER_FILL,
            {"text": "juandi", "field": "nombre"},
        ),
        ("pon el volumen al 42 por ciento", ActionName.VOLUME_SET, {"level": 42}),
        ("súbele el volumen", ActionName.VOLUME_CHANGE, {"step": 5}),
        ("bájale el volumen 10%", ActionName.VOLUME_CHANGE, {"step": -10}),
        ("silencia el sonido", ActionName.VOLUME_MUTE, {"muted": True}),
        ("quita el silencio", ActionName.VOLUME_MUTE, {"muted": False}),
        ("dime el volumen", ActionName.VOLUME_GET, {}),
        ("Jarvis, dime el volumen actual", ActionName.VOLUME_GET, {}),
        ("¿En cuánto está el volumen del sistema?", ActionName.VOLUME_GET, {}),
        ("siguiente canción", ActionName.MEDIA_NEXT, {}),
        ("pausa", ActionName.MEDIA_PLAY_PAUSE, {}),
        ("lista las ventanas", ActionName.WINDOW_LIST, {}),
        ("cuál es la ventana actual", ActionName.WINDOW_CURRENT, {}),
        ("cambia a la ventana de Spotify", ActionName.WINDOW_FOCUS, {"title": "spotify"}),
        ("minimiza la ventana", ActionName.WINDOW_MINIMIZE, {"title": ""}),
        ("maximiza la ventana de Edge", ActionName.WINDOW_MAXIMIZE, {"title": "edge"}),
        ("cierra la ventana de Paint", ActionName.WINDOW_CLOSE, {"title": "paint"}),
        ("muestra los controles", ActionName.UI_INSPECT, {}),
        ('Jarvis, escribe "Texto con ácentos"', ActionName.UI_TYPE, {"text": "Texto con ácentos"}),
        ("guarda", ActionName.UI_HOTKEY, {"hotkey": "save"}),
        ("presiona intro", ActionName.UI_KEY, {"key": "enter"}),
        ("haz clic en 400, 250", ActionName.POINTER_CLICK, {"x": 400, "y": 250}),
        ("haz scroll abajo 8", ActionName.POINTER_SCROLL, {"amount": -8}),
        ("captura la pantalla", ActionName.SCREENSHOT_TAKE, {}),
        ("muestra el escritorio", ActionName.DESKTOP_SHOW, {}),
        ("estado del sistema", ActionName.SYSTEM_STATUS, {}),
        ("cuánto espacio libre tengo en el disco", ActionName.SYSTEM_STATUS, {}),
        ("cuánta memoria disponible tengo", ActionName.SYSTEM_STATUS, {}),
        ("qué aplicaciones puedes abrir", ActionName.APP_LIST, {}),
        ("lee el portapapeles", ActionName.CLIPBOARD_READ, {}),
        (
            'copia "Texto privado" al portapapeles',
            ActionName.CLIPBOARD_WRITE,
            {"text": "Texto privado"},
        ),
        ("abre la carpeta Descargas", ActionName.PATH_OPEN_FOLDER, {"path": "Descargas"}),
        (
            'abre el archivo "D:\\Datos\\reporte.pdf"',
            ActionName.PATH_OPEN,
            {"path": "D:\\Datos\\reporte.pdf"},
        ),
    ],
)
def test_supported_phrases_are_parsed(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert parsed is not None
    assert not isinstance(parsed, BlockedIntent)
    assert parsed.name is name
    assert parsed.arguments == arguments


@pytest.mark.parametrize(
    "phrase",
    [
        "abre powershell",
        "ejecuta cmd",
        "apaga la computadora",
        "reinicia el sistema",
        "borra todos mis archivos",
        "formatea el disco",
        "compra una laptop",
        "transfiere cien dólares",
    ],
)
def test_dangerous_direct_requests_are_explicitly_blocked(phrase: str) -> None:
    result = DeterministicActionParser().parse(phrase)

    assert isinstance(result, BlockedIntent)


@pytest.mark.parametrize(
    "phrase",
    [
        "No abras la calculadora",
        "Si te digo abre PowerShell no lo hagas",
        "¿Cómo abro el bloc de notas?",
        "Explica cómo subir el volumen",
        "Cuando diga abre Google, ¿qué harás?",
        "Cuéntame algo interesante",
        "¿Puedes explicarme cómo abrir la calculadora?",
        "Quiero que me expliques cómo funciona el volumen",
    ],
)
def test_meta_negated_and_conversational_phrases_are_not_actions(phrase: str) -> None:
    parser = DeterministicActionParser()

    assert parser.parse(phrase) is None
    assert parser.looks_action_like(phrase) is False


def test_normalization_is_wake_accent_and_whitespace_insensitive() -> None:
    assert normalize_request(" ¿OYE   JÁRVIS,  SÚBELE el volumen!? ") == "subele el volumen"


def test_normalization_strips_typed_punctuation_after_wake_word() -> None:
    assert normalize_request("Jarvis, ¿qué ves en mi monitor?") == "que ves en mi monitor"


@pytest.mark.parametrize(
    ("phrase", "names"),
    [
        (
            "abre la calculadora y maximiza la ventana",
            (ActionName.APP_OPEN, ActionName.WINDOW_MAXIMIZE),
        ),
        (
            'abre el bloc de notas y escribe "hola y adiós"',
            (ActionName.APP_OPEN, ActionName.UI_TYPE),
        ),
        (
            "abre Google, luego busca clima y después abre el primer resultado",
            (
                ActionName.BROWSER_OPEN,
                ActionName.BROWSER_SEARCH,
                ActionName.BROWSER_OPEN_RESULT,
            ),
        ),
    ],
)
def test_explicit_compound_requests_create_bounded_workflows(
    phrase: str,
    names: tuple[ActionName, ...],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert isinstance(parsed, ActionWorkflowPlan)
    assert tuple(step.name for step in parsed.steps) == names


def test_conjunction_inside_search_is_not_mistaken_for_workflow() -> None:
    parsed = DeterministicActionParser().parse("busca rock y roll")

    assert parsed.name is ActionName.BROWSER_SEARCH
    assert parsed.arguments == {"query": "rock y roll"}


@pytest.mark.parametrize(
    ("phrase", "query", "browser"),
    [
        (
            "Jarvis, estoy muy interesado en cursos de Python en español, "
            "¿me puedes dar buscando unos cursos usando Google Chrome?",
            "cursos de python en espanol",
            "chrome",
        ),
        (
            "Ando interesado en fotografía nocturna; ¿podrías buscar opciones en internet "
            "con Microsoft Edge?",
            "fotografia nocturna",
            "edge",
        ),
        (
            "Me puedes ayudar a encontrar restaurantes tranquilos usando Brave",
            "restaurantes tranquilos",
            "brave",
        ),
        (
            "Estoy pensando en cocinar, ¿me ayudarías a encontrar recetas de lasaña en Chrome?",
            "recetas de lasana",
            "chrome",
        ),
        (
            "Quisiera que me ayudaras a buscar cursos gratuitos de Linux usando Chrome",
            "cursos gratuitos de linux",
            "chrome",
        ),
    ],
)
def test_natural_goal_oriented_searches_use_context(
    phrase: str,
    query: str,
    browser: str,
) -> None:
    parser = DeterministicActionParser()

    parsed = parser.parse(phrase)

    assert parsed is not None
    assert parsed.name is ActionName.BROWSER_SEARCH
    assert parsed.arguments == {"query": query, "browser": browser}
    assert parser.looks_action_like(phrase) is True


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        (
            "Estoy por comenzar a estudiar; ¿me puedes abrir el bloc de notas?",
            ActionName.APP_OPEN,
            {"app": "notepad"},
        ),
        (
            "Tengo poca batería, necesito que cierres la ventana de Spotify",
            ActionName.WINDOW_CLOSE,
            {"title": "spotify"},
        ),
        (
            "Para ver mejor, me gustaría que maximices la ventana",
            ActionName.WINDOW_MAXIMIZE,
            {"title": ""},
        ),
        (
            "Para concentrarme, me gustaría que bajaras un poco el volumen",
            ActionName.VOLUME_CHANGE,
            {"step": -5},
        ),
        (
            "Tengo que hacer cuentas; ¿serías tan amable de dejarme la calculadora abierta?",
            ActionName.APP_OPEN,
            {"app": "calculator"},
        ),
        (
            "Quisiera revisar mi correo; llévame a Gmail",
            ActionName.BROWSER_OPEN,
            {"url": "https://mail.google.com"},
        ),
        (
            "Tengo que hacer una cuenta, ¿me abres la calculadora?",
            ActionName.APP_OPEN,
            {"app": "calculator"},
        ),
    ],
)
def test_actions_can_follow_conversational_context(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments


@pytest.mark.parametrize(
    "phrase",
    [
        "Estoy interesado en Python, pero no quiero que busques cursos todavía",
        "Me puedes explicar cómo buscar cursos usando Chrome",
        "Si pudieras buscar cursos algún día sería genial",
    ],
)
def test_natural_context_does_not_turn_negation_explanation_or_hypothesis_into_action(
    phrase: str,
) -> None:
    parser = DeterministicActionParser()

    assert parser.parse(phrase) is None
    assert parser.looks_action_like(phrase) is False


def test_indirect_open_goal_with_context_is_routed_to_restricted_planner() -> None:
    parser = DeterministicActionParser()
    phrase = "Voy a escribir unas ideas y quiero tener el bloc de notas abierto"

    assert parser.parse(phrase) is None
    assert parser.looks_action_like(phrase) is True


def test_dangerous_step_blocks_entire_workflow() -> None:
    result = DeterministicActionParser().parse("abre la calculadora y apaga la computadora")

    assert isinstance(result, BlockedIntent)


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        ("qué monitores están conectados", ActionName.SCREEN_LIST, {}),
        (
            "dime cuál es el monitor 1 y cuál es el monitor 2",
            ActionName.SCREEN_LIST,
            {},
        ),
        (
            "dime qué hay en cada uno de mis monitores",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "all"},
        ),
        ("qué ves en el monitor 2", ActionName.SCREEN_DESCRIBE, {"monitor": "2"}),
        ("describe el segundo monitor", ActionName.SCREEN_DESCRIBE, {"monitor": "2"}),
        (
            "mira el monitor principal y dime cuál es el error",
            ActionName.SCREEN_ASK,
            {"question": "cual es el error", "monitor": "primary"},
        ),
        (
            "encuentra Aceptar en el monitor de la derecha",
            ActionName.SCREEN_FIND,
            {"target": "aceptar", "monitor": "right"},
        ),
        (
            "haz clic en Continuar en el monitor 1",
            ActionName.SCREEN_CLICK,
            {"target": "continuar", "monitor": "1"},
        ),
        (
            "qué dice el mensaje en la pantalla de la izquierda",
            ActionName.SCREEN_ASK,
            {"question": "que dice el mensaje", "monitor": "left"},
        ),
    ],
)
def test_monitor_aware_visual_commands(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        (
            "Jarvis, ¿qué es lo que ves en mi monitor número uno?",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "1"},
        ),
        (
            "¿Puedes echarle un vistazo a mi primera pantalla y contarme qué aparece?",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "1"},
        ),
        (
            "Dime qué tengo abierto en el display de la derecha",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "right"},
        ),
        (
            "¿Qué dice el mensaje en mi monitor número dos?",
            ActionName.SCREEN_ASK,
            {"question": "que dice el mensaje", "monitor": "2"},
        ),
        (
            "Observa cada uno de mis monitores",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "all"},
        ),
    ],
)
def test_visual_intent_accepts_natural_monitor_language(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parser = DeterministicActionParser()

    parsed = parser.parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments
    assert parser.looks_visual(phrase) is True


def test_generic_visual_command_leaves_monitor_available_for_session_context() -> None:
    parsed = DeterministicActionParser().parse("qué ves en la pantalla")

    assert parsed is not None
    assert parsed.name is ActionName.SCREEN_DESCRIBE
    assert parsed.arguments == {}


def test_visual_pronoun_uses_guarded_recent_target_reference() -> None:
    parsed = DeterministicActionParser().parse("haz clic en el botón que mencionaste")

    assert parsed is not None
    assert parsed.name is ActionName.SCREEN_CLICK
    assert parsed.arguments["target"] == DeterministicActionParser.LAST_VISUAL_TARGET


@pytest.mark.parametrize(
    "phrase",
    (
        "Jarvis, ¿qué estás viendo?",
        "¿Puedes ver lo que tengo abierto?",
        "Mira esto",
        "Échale un vistazo a esto",
    ),
)
def test_implicit_visual_language_is_grounded_in_a_fresh_capture(phrase: str) -> None:
    parser = DeterministicActionParser()

    parsed = parser.parse(phrase)

    assert parsed is not None
    assert parsed.name is ActionName.SCREEN_DESCRIBE
    assert parser.has_agent_intent(phrase) is True
    assert parser.looks_visual(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    (
        "¿Podrías revisar las ventanas que están abiertas?",
        "Me puedes organizar el escritorio para estudiar",
        "Quisiera que analizaras el mensaje que aparece en pantalla",
        "Necesito tener Discord abierto",
        "Me gustaría escuchar música tranquila en Spotify",
        "Me vendría bien tener Obsidian abierto para escribir",
        "Estoy cansado; pon algo relajante en Spotify",
    ),
)
def test_natural_computer_goals_reach_semantic_planning(phrase: str) -> None:
    assert DeterministicActionParser().has_agent_intent(phrase) is True


def test_additive_natural_goal_preserves_every_requested_subgoal() -> None:
    parser = DeterministicActionParser()
    phrase = (
        "Jarvis, necesito que revises cómo está funcionando mi computadora "
        "y además me digas cuál es el volumen actual"
    )

    parts = parser.workflow_parts(phrase)

    assert len(parts) == 2
    assert "además" not in parts[1]
    volume = parser.parse(parts[1])
    assert volume is not None
    assert volume.name is ActionName.VOLUME_GET


@pytest.mark.parametrize(
    ("phrase", "name", "arguments"),
    [
        (
            "Jarvis, necesito que me dejes abierto el bloc de notas",
            ActionName.APP_OPEN,
            {"app": "notepad"},
        ),
        ("Por favor abre Google Chrome", ActionName.APP_OPEN, {"app": "google chrome"}),
        (
            "Pon el volumen al cincuenta por ciento",
            ActionName.VOLUME_SET,
            {"level": 50},
        ),
        (
            "Pon el volumen al cuarenta y dos por ciento",
            ActionName.VOLUME_SET,
            {"level": 42},
        ),
        ("Quita el silencio del sistema", ActionName.VOLUME_MUTE, {"muted": False}),
        ("Jarvis, dimel volumen actual", ActionName.VOLUME_GET, {}),
        (
            "Dime qué tengo en cada monitor",
            ActionName.SCREEN_DESCRIBE,
            {"monitor": "all"},
        ),
        (
            "Busca visualmente el botón de continuar en la pantalla derecha",
            ActionName.SCREEN_FIND,
            {"target": "el boton de continuar", "monitor": "right"},
        ),
        ("Lista las ventanas abiertas", ActionName.WINDOW_LIST, {}),
        ("Dime cuál ventana está activa", ActionName.WINDOW_CURRENT, {}),
        ("Minimiza esta ventana", ActionName.WINDOW_MINIMIZE, {"title": ""}),
        (
            "Abre una pestaña nueva en Chrome",
            ActionName.BROWSER_NEW_TAB,
            {"browser": "chrome"},
        ),
    ],
)
def test_common_natural_variants_do_not_require_model_planning(
    phrase: str,
    name: ActionName,
    arguments: dict[str, object],
) -> None:
    parsed = DeterministicActionParser().parse(phrase)

    assert parsed is not None
    assert parsed.name is name
    assert parsed.arguments == arguments
