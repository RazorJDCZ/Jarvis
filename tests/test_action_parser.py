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
        ("abre youtube", ActionName.BROWSER_OPEN, {"url": "https://www.youtube.com"}),
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


def test_dangerous_step_blocks_entire_workflow() -> None:
    result = DeterministicActionParser().parse("abre la calculadora y apaga la computadora")

    assert isinstance(result, BlockedIntent)
