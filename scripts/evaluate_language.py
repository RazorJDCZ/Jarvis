"""Isolated conversational evaluation with the installed model; no executable tools.

The JSONL contains observations, not automatic semantic pass/fail judgments.
Review each response against its criterion. No production profile or memory is read.
Run: python scripts/evaluate_language.py --output .data/language-eval
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jarvis.actions.models import ActionPlan, ActionWorkflowPlan, BlockedIntent
from jarvis.actions.parser import DeterministicActionParser
from jarvis.actions.planner import LocalActionPlanner
from jarvis.config import Settings
from jarvis.providers.brain import OllamaBrain
from jarvis.services.conversation import ConversationService
from jarvis.services.profile import LocalProfileStore


class NoActions:
    """Inspect lexical routing only. No catalog, executors or planning inference exist."""

    def __init__(self, config):
        self.parser = DeterministicActionParser()
        self.planner = LocalActionPlanner(config, tuple(LocalActionPlanner._TOOL_GUIDE))

    def inspect(self, text):
        parsed = self.parser.parse(text)
        return {
            "deterministic": (
                str(parsed.name)
                if isinstance(parsed, ActionPlan)
                else "workflow"
                if isinstance(parsed, ActionWorkflowPlan)
                else "blocked"
                if isinstance(parsed, BlockedIntent)
                else None
            ),
            "explicit_candidate": self.parser.has_agent_intent(text),
            "semantic_candidate": self.planner.likely_tool_request(text),
            "explicit_non_action": self.parser.is_explicitly_non_action(text),
        }

    async def try_handle(self, *_args, **_kwargs):
        return None

    def supersede_pending(self, _session):
        return False

    def reset(self, _session):
        pass


class NoVerification:
    async def verify(self, _message):
        return None


def suite():
    cases = []

    def add(key, category, *turns):
        cases.append(
            {
                "id": key,
                "category": category,
                "turns": [
                    {"message": message, "criterion": criterion} for message, criterion in turns
                ],
            }
        )

    for key, text, criterion in [
        (
            "g01",
            "Hola Jarvis, ¿cómo vas que te cuentas? Hace mucho que no hablamos cómo se ha estado.",
            "Saludo social, sin informes técnicos ni actividad inventada.",
        ),
        ("g02", "¿Cómo estás?", "Responder socialmente, no pedir definir una tarea."),
        ("g03", "Buenas, ¿todo bien por allá?", "Saludo; no afirmar diagnósticos comprobados."),
        (
            "g04",
            "Qué gusto volver a hablar contigo.",
            "Reciprocidad natural sin recuerdos inventados.",
        ),
        (
            "g05",
            "¿Qué has hecho mientras no estaba?",
            "No inventar actividades autónomas o vivencias.",
        ),
        (
            "g06",
            "Solo pasaba a saludar, no necesito nada.",
            "No proponer tareas ni preguntar qué necesita.",
        ),
        (
            "g07",
            "Gracias, eso era justo lo que quería decir.",
            "Reconocer agradecimiento sin fabricar contexto.",
        ),
        (
            "g08",
            "Hasta luego, hablamos mañana.",
            "Despedida sin crear recordatorios ni prometer avisos.",
        ),
    ]:
        add(key, "saludos", (text, criterion))

    for key, text, criterion in [
        (
            "ec01",
            "Hoy estoy chiro, pero de buen ánimo.",
            "Chiro significa sin dinero; respetar buen ánimo.",
        ),
        ("ec02", "Ese examen estuvo yuca.", "Examen difícil, no alimento ni problema informático."),
        ("ec03", "Mi pana se portó súper bien conmigo.", "Pana significa amigo; respuesta social."),
        ("ec04", "Estoy hecho funda después de clases.", "Cansancio intenso, sentido figurado."),
        (
            "ec05",
            "Qué bestia, me fue de ley en la presentación.",
            "Interpretación prudente del coloquialismo; no animal literal.",
        ),
        (
            "ec06",
            "Chuta, se me fue la onda y olvidé lo que iba a decir.",
            "Perdió el hilo; no avería de audio.",
        ),
        (
            "ec07",
            "Ya mismo te cuento; dame chance.",
            "Esperar sin exigir datos ni asumir duración exacta.",
        ),
        (
            "ec08",
            "Me dio un acolite cuando más lo necesitaba.",
            "Apoyo o ayuda de alguien; no inventar quién.",
        ),
        (
            "ec09",
            "No caché el chiste, ¿me sigues?",
            "No entendió un chiste que no se ha proporcionado; no inventarlo.",
        ),
        ("ec10", "Me quedé en blanco en plena expo.", "Bloqueo al exponer, no pantalla blanca."),
    ]:
        add(key, "coloquial_ecuador", (text, criterion))

    for key, text, criterion in [
        ("m01", "Hoy tengo la cabeza en las nubes.", "Distracción, no clima ni nube informática."),
        (
            "m02",
            "Se me cruzaron los cables cuando me preguntaron eso.",
            "Confusión mental figurada, no reparar hardware.",
        ),
        (
            "m03",
            "Necesito bajar un cambio, llevo toda la semana a mil.",
            "Necesita desacelerar, no modificar volumen o equipo.",
        ),
        (
            "m04",
            "Estoy entre la espada y la pared con esa decisión.",
            "Dilema, no amenaza física literal sin señales adicionales.",
        ),
        ("m05", "Ese comentario me dejó helado.", "Sorpresa o impacto, no tratamiento por frío."),
        (
            "m06",
            "Me estás leyendo la mente, justo iba a decir eso.",
            "Expresión de coincidencia; no afirmar telepatía.",
        ),
        (
            "m07",
            "Mi paciencia está en modo avión.",
            "Metáfora sobre paciencia, no tocar conectividad.",
        ),
        (
            "m08",
            "Quiero abrir un paréntesis en esta charla.",
            "Introducir digresión, no abrir aplicaciones.",
        ),
        (
            "m09",
            "No quiero que me arregles la vida, solo que me entiendas.",
            "Escuchar sin plan ni lista de soluciones.",
        ),
        ("m10", "Estoy muerto de sueño.", "Somnolencia figurada, no interpretar muerte literal."),
    ]:
        add(key, "expresiones_figuradas", (text, criterion))

    for key, text, criterion in [
        (
            "i01",
            "Qué maravilla, otro trabajo grupal donde hago todo yo.",
            "Detectar frustración irónica, no felicitar.",
        ),
        (
            "i02",
            "Buenísimo, justo se fue la luz cuando iba a entregar. Qué suerte la mía.",
            "Contratiempo e ironía, no buena suerte literal.",
        ),
        (
            "i03",
            "Sí, claro, porque dormir tres horas es la receta del éxito.",
            "Ironía crítica, no recomendar dormir tres horas.",
        ),
        (
            "i04",
            "Me fue increíble: olvidé mi nombre al presentarme. Estoy siendo sarcástico.",
            "Reconocer vergüenza y sarcasmo explícito.",
        ),
        (
            "i05",
            "Menudo genio soy, dejé el paraguas justo el día que llueve.",
            "Autocrítica irónica sin insultar ni afirmar genialidad literal.",
        ),
        (
            "i06",
            "Llegué temprano por primera vez. Milagro, ¿no?",
            "Humor cotidiano sin discusión religiosa literal.",
        ),
        (
            "i07",
            "Ganamos. Me estoy muriendo 😂",
            "Exageración alegre; no emergencia ni muerte literal.",
        ),
        (
            "i08",
            "Sí, estoy feliz... se nota muchísimo 🙃",
            "No asumir alegría; reconocer posible ironía o ambigüedad.",
        ),
    ]:
        add(key, "ironia_humor", (text, criterion))

    for key, text, criterion in [
        (
            "e01",
            "Hoy tuve un día pesado. No quiero consejos, solo conversar.",
            "Acompañar sin consejos ni listas.",
        ),
        (
            "e02",
            "Estoy contento y triste a la vez; terminé una etapa importante.",
            "Aceptar emociones mixtas, no contradicción lógica.",
        ),
        (
            "e03",
            "No estoy enojado contigo, estoy frustrado conmigo.",
            "Distinguir destinatario de frustración; no disculparse por culpa inventada.",
        ),
        (
            "e04",
            "Me da vergüenza admitir que no entendí nada de la clase.",
            "Validación sin juzgar ni diagnosticar.",
        ),
        ("e05", "No quiero hablar de eso ahora.", "Respetar límite sin insistir en qué pasó."),
        (
            "e06",
            "Me ascendieron, pero siento que no me lo merezco.",
            "Reconocer logro y duda; no diagnóstico categórico.",
        ),
        (
            "e07",
            "Estoy molesto. Respóndeme sin intentar animarme a la fuerza.",
            "Reconocer molestia sin positividad impuesta.",
        ),
        (
            "e08",
            "Me dejaron en visto y ya me hice mil películas.",
            "Reconocer interpretaciones ansiosas; no afirmar intenciones ajenas.",
        ),
    ]:
        add(key, "emociones_limites", (text, criterion))

    for key, text, criterion in [
        (
            "t01",
            "ola jarvis cm tas? tnia ganas d ablar un rato",
            "Comprender abreviaturas como saludo y deseo de charla.",
        ),
        ("t02", "oy no fue mi dia la vdd", "Comprender mal día pese a errores de escritura."),
        (
            "t03",
            "Osea no se como explicarlo estoy feliz pero como raro",
            "Aceptar emoción mixta; aclarar con tacto.",
        ),
        (
            "t04",
            "Estoy medio overwhelmed con la uni, pero no quiero un productivity plan.",
            "Entender mezcla español-inglés y no ofrecer plan.",
        ),
        (
            "t05",
            "That was awkward, pero ya fue, let's move on.",
            "Aceptar cambio de tema; no insistir en incidente.",
        ),
        (
            "t06",
            "Toy cansadísimo, bro. Cero ganas de socializar hoy.",
            "Comprender cansancio y falta de ganas de socializar.",
        ),
        (
            "t07",
            "no no osea no era eso lo q keria decir",
            "Pedir o permitir aclaración, no adivinar significado ausente.",
        ),
        ("t08", "Holi :) q tal va todo x ahi", "Saludo coloquial sin diagnóstico técnico."),
    ]:
        add(key, "escritura_y_code_switch", (text, criterion))

    for key, text, criterion in [
        (
            "n01",
            "No quiero que abras nada, solo estoy hablando de ventanas como metáfora.",
            "Respetar negación y metáfora; no ejecutar ni pedir autorizar.",
        ),
        (
            "n02",
            "Cuando digo 'borra eso de tu cabeza', es una expresión, no una orden.",
            "Comprender mención de expresión; no borrar memoria.",
        ),
        (
            "n03",
            "Mi amigo me dijo 'cierra la boca'. ¿Suena agresivo?",
            "Evaluar cita, no tomarla como orden del usuario.",
        ),
        (
            "n04",
            "Explícame la diferencia entre 'no puedo' y 'no quiero'.",
            "Diferenciar capacidad y voluntad.",
        ),
        (
            "n05",
            "No es que no me importe; es que no sé cómo demostrarlo.",
            "Comprender que sí le importa, dificultad al expresarlo.",
        ),
        (
            "n06",
            "Nunca dije que no quisiera ir.",
            "No equiparar a rechazo; tampoco inferir certeza de que quiere ir.",
        ),
        ("n07", "Solo Ana no vino; Luis y Carla sí llegaron. ¿Quién faltó?", "Ana únicamente."),
        (
            "n08",
            "Ninguno de los dos dijo que sí. ¿Eso prueba que dijeron que no?",
            "No; ausencia de afirmación no prueba negativa explícita.",
        ),
        (
            "n09",
            "La frase de mi cuento es: 'abre la puerta y sal corriendo'. ¿Qué tono tiene?",
            "Analizar frase citada, no tratar como instrucción.",
        ),
        (
            "n10",
            "No dejes de contarme qué significa 'estar pilas'.",
            "Doble negación pide explicar: estar atento, activo o listo.",
        ),
    ]:
        add(key, "negacion_y_citas", (text, criterion))

    for key, text, criterion in [
        ("a01", "Dile que sí.", "Sin antecedente: preguntar a quién/sobre qué; no afirmar envío."),
        ("a02", "Eso estuvo fuerte.", "Reconocer falta de contexto sin inventar qué sucedió."),
        (
            "a03",
            "Se lo di a ella porque él no lo quería.",
            "No asignar identidades ni objeto no proporcionados.",
        ),
        (
            "a04",
            "Vi a Pedro con el telescopio. ¿Quién tenía el telescopio?",
            "Reconocer dos lecturas posibles.",
        ),
        (
            "a05",
            "Ana vio a Laura cuando salía de clase. ¿Quién salía?",
            "Reconocer ambigüedad, no asegurar una lectura.",
        ),
        (
            "a06",
            "¿Te acuerdas de lo que te dije ayer?",
            "No inventar recuerdo fuera de la sesión aislada.",
        ),
    ]:
        add(key, "ambiguedad", (text, criterion))

    add(
        "d01",
        "correcciones",
        ("Tengo un examen el martes.", "Registrar martes sin agendar."),
        ("Perdón, es el jueves, no el martes.", "Actualizar a jueves."),
        ("¿Qué día tengo el examen?", "Jueves, sin conservar martes como vigente."),
    )
    add(
        "d02",
        "correcciones",
        ("Voy a invitar a Ana y a Luis.", "Registrar dos personas."),
        (
            "Al final Ana no puede; irá Carla en su lugar.",
            "Sustituir Ana por Carla, conservar Luis.",
        ),
        ("¿Quiénes van a ir?", "Luis y Carla; no Ana."),
    )
    add(
        "d03",
        "correcciones",
        ("Mi gato se llama Nube.", "Retener nombre Nube, no añadir datos."),
        ("Me equivoqué al escribir: es mi perro.", "Cambiar especie; conservar nombre."),
        ("¿Cómo se llama y qué animal es?", "Perro llamado Nube."),
    )
    add(
        "d04",
        "correcciones",
        ("Estoy feliz porque me fue bien.", "Reconocer alegría."),
        ("No, era sarcasmo. Me fue horrible.", "Actualizar intención; no continuar felicitando."),
    )
    add(
        "d05",
        "correcciones",
        ("Te estoy contando algo, no pidiéndote que hagas nada.", "Aceptar marco conversacional."),
        (
            "Cuando digo 'organizar mi cabeza', hablo de entender lo que siento.",
            "Comprender metáfora; no agenda ni herramientas.",
        ),
    )
    add(
        "d06",
        "correcciones",
        ("El ensayo debe tener 800 palabras.", "Retener cantidad."),
        ("Ojo, dije ochocientas, no ocho mil.", "No cambiar a 8000."),
        ("¿Cuántas palabras eran?", "800."),
    )
    add(
        "d07",
        "correcciones",
        ("Mi hermana es mayor que yo.", "Retener relación sin inventar edad."),
        ("No dije que tenga 30 años; no te he dicho su edad.", "No conservar edad inventada."),
        ("¿Cuántos años tiene ella?", "No sabe la edad."),
    )
    add(
        "d08",
        "correcciones",
        ("No me contestes tan formal; háblame como un pana.", "Adaptar tono sin caricatura."),
        ("Hoy sí que me costó levantarme.", "Mantener registro cercano natural."),
    )

    add(
        "c01",
        "contexto_referencias",
        (
            "Compré una libreta roja y una azul. La roja es para cálculo.",
            "Retener correspondencias.",
        ),
        ("La otra la usaré para mis ideas.", "La otra es azul."),
        ("¿De qué color es la de las ideas?", "Azul."),
    )
    add(
        "c02",
        "contexto_referencias",
        ("Estoy entre ir al cine o quedarme leyendo.", "Retener dos opciones."),
        ("La segunda me suena mejor porque estoy cansado.", "Segunda = quedarse leyendo."),
        ("¿Qué elegí?", "Quedarse leyendo."),
    )
    add(
        "c03",
        "contexto_referencias",
        ("Laura le prestó su libro a Mateo.", "Laura dueña, Mateo receptor."),
        ("Él se lo devolvió ayer.", "Mateo devuelve libro a Laura."),
        ("¿Quién tiene ahora el libro?", "Laura."),
    )
    add(
        "c04",
        "contexto_referencias",
        ("Si llueve, no salgo; si no llueve, voy al parque.", "Retener condición."),
        ("Está lloviendo.", "No sale."),
        ("Según lo que dije, ¿voy al parque?", "No."),
    )
    add(
        "c05",
        "contexto_referencias",
        ("Me preocupaba el examen, pero ya lo aprobé.", "Preocupación pasada; aprobación actual."),
        (
            "¿Por qué sigues hablando como si todavía tuviera que rendirlo?",
            "Aceptar corrección temporal, no insistir en prepararlo.",
        ),
    )
    add(
        "c06",
        "contexto_referencias",
        (
            "Ana me dijo que estaba cansada. Yo estaba contento.",
            "Distinguir estados de Ana y usuario.",
        ),
        ("¿Quién estaba cansado y quién contento?", "Ana cansada; usuario contento."),
    )
    add(
        "c07",
        "contexto_referencias",
        ("Mi amigo dejó de contestarme y me preocupé.", "No atribuir intenciones."),
        ("Resultó que se había quedado sin batería.", "Actualizar explicación a batería."),
        (
            "Entonces, ¿me estaba ignorando?",
            "La evidencia dada apunta a batería, no rechazo intencional.",
        ),
    )
    add(
        "c08",
        "contexto_referencias",
        ("¿Podemos hablar de música?", "Aceptar tema sin abrir reproductor."),
        (
            "Más que canciones, me interesa cómo me cambia el ánimo.",
            "Conversar sobre experiencia emocional; no reproducir música.",
        ),
    )
    add(
        "c09",
        "contexto_referencias",
        ("Estoy contento por mi nota.", "Alegría por calificación."),
        (
            "Cambiando de tema, ¿por qué a veces los silencios son cómodos?",
            "Responder nuevo tema sin relacionarlo forzosamente con nota.",
        ),
    )
    add(
        "c10",
        "contexto_referencias",
        (
            "Mi reunión era a las tres, pero la pasaron dos horas más tarde.",
            "Inferir las cinco sin agendar.",
        ),
        ("¿A qué hora quedó?", "A las cinco."),
    )

    add(
        "f01",
        "restricciones",
        (
            "En una sola frase, ¿qué significa 'ponerse en los zapatos del otro'?",
            "Una frase: adoptar perspectiva o empatizar, no zapatos literales.",
        ),
    )
    add(
        "f02",
        "restricciones",
        (
            "Responde solamente 'sí' o 'no': si Ana es mayor que Luis y Luis es mayor que Carla, "
            "¿Ana es mayor que Carla?",
            "Solo sí, razonamiento transitivo correcto.",
        ),
    )
    add(
        "f03",
        "restricciones",
        (
            "Explícame 'nostalgia' sin usar la palabra 'tristeza'.",
            "Explicar sin palabra prohibida, no texto técnico.",
        ),
    )
    add(
        "f04",
        "restricciones",
        (
            "Dame exactamente dos interpretaciones de 'me dejó frío', sin ejemplos.",
            "Dos lecturas, ninguna tercera ni ejemplos.",
        ),
    )
    add(
        "f05",
        "restricciones",
        (
            "Tengo ganas de hablar, pero no me hagas preguntas en tu respuesta.",
            "Respuesta social sin interrogaciones ni preguntas indirectas.",
        ),
    )
    add(
        "f06",
        "restricciones",
        (
            "Resume en seis palabras: estoy agotado, orgulloso y nervioso "
            "por haber terminado la carrera.",
            "Exactamente seis palabras y preservar sentimientos principales.",
        ),
    )

    add(
        "l01",
        "memoria_conversacion_larga",
        (
            "En esta charla, mi palabra clave es girasol y el número es 47.",
            "Retener dos datos solo en conversación.",
        ),
        ("Mi bebida favorita para este ejemplo es chocolate caliente.", "Retener dato sintético."),
        ("Me gusta el olor a lluvia.", "Reconocer preferencia sin inventar historia."),
        ("A veces prefiero escuchar que hablar.", "Reconocer sin diagnosticar personalidad."),
        ("Una caminata corta puede cambiar el ánimo.", "Comentario general sin tareas."),
        (
            "¿Cuál era mi palabra clave y mi número?",
            "Girasol y 47, dentro de ventana de historial.",
        ),
        ("Cambio únicamente el número: ahora es 62.", "Actualizar número; mantener girasol."),
        ("Me gustan las tardes tranquilas.", "Respuesta natural."),
        ("El color que elijo es verde.", "Retener verde."),
        ("Hoy prefiero respuestas cortas.", "Respetar brevedad."),
        ("Me gusta mirar las nubes.", "Comentario sin consultar clima."),
        ("El olor a pan recién hecho también me gusta.", "No convertir en pedido de comida."),
        ("Hemos hablado de cosas sencillas.", "No inventar otros temas."),
        ("Sigo aquí, solo estoy pensando.", "No exigir tarea."),
        (
            "¿Qué número está vigente, 47 o 62?",
            "62; dato de corrección puede quedar al borde de ventana.",
        ),
        (
            "¿Qué bebida mencioné al principio?",
            "Si no conserva dato, admitirlo; nunca adivinar como recuerdo.",
        ),
        (
            "¿Cuál era mi palabra clave?",
            "Girasol si recuerda; admitir desconocimiento si perdió historial.",
        ),
    )
    return cases


async def run(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8")) if args.cases else suite()
    if args.ids:
        cases = [case for case in cases if case["id"] in args.ids.split(",")]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    config = Settings()
    metadata = {
        "model": config.ollama_model,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dialogs": len(cases),
        "planned_turns": sum(len(c["turns"]) for c in cases),
        "history_messages": config.max_history_messages,
        "tools": "absent; parser observations only, no executor or agent inference",
        "profile": "empty; production personal profile is not loaded",
        "memory": "disabled; only current dialog history",
        "verification": "disabled; no external web or account calls",
        "warm_model": "3m keep-alive override only for this evaluation process",
        "judging": "criteria recorded before generation; human review required",
    }
    (output / "cases.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=True), flush=True)
    with tempfile.TemporaryDirectory(prefix="jarvis-language-") as folder:
        config = replace(
            config,
            project_root=Path(folder),
            memory_enabled=False,
            semantic_enabled=False,
            voice_preload=False,
            safe_actions_enabled=False,
            action_model_planning=False,
            capabilities_enabled=False,
            information_verification_enabled=False,
            appa_auto_discover=False,
        )
        brain = OllamaBrain(config)
        actions = NoActions(config)
        profile = LocalProfileStore(Path(folder) / "empty-profile.json")
        service = ConversationService(
            config, brain, actions, verifier=NoVerification(), profile_store=profile
        )
        completed = 0
        with (output / "responses.jsonl").open("w", encoding="utf-8", buffering=1) as log:
            for case in cases:
                for index, turn in enumerate(case["turns"], 1):
                    started = time.perf_counter()
                    row = {
                        "id": f"{case['id']}.{index}",
                        "category": case["category"],
                        **turn,
                        "routing_probe": actions.inspect(turn["message"]),
                    }
                    try:
                        with patch("jarvis.providers.brain.model_keep_alive", return_value="3m"):
                            answer = await service.reply(case["id"], turn["message"])
                            row["initial_provider"] = answer.provider
                            if answer.provider == "analysis-confirmation":
                                row["interruption"] = answer.text
                                answer = await service.reply(case["id"], "versión normal")
                        row.update(response=answer.text, provider=answer.provider)
                    except Exception as exc:
                        row.update(error=type(exc).__name__ + ": " + str(exc)[:250])
                    row["seconds"] = round(time.perf_counter() - started, 2)
                    log.write(json.dumps(row, ensure_ascii=False) + "\n")
                    completed += 1
                    print(
                        f"{completed}/{metadata['planned_turns']} {row['id']} "
                        f"{row.get('provider', 'ERROR')} {row['seconds']}s",
                        flush=True,
                    )
                service.reset(case["id"])
    print("Evaluation complete. Review responses against the recorded criteria.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".data/language-eval")
    parser.add_argument("--ids", default="", help="Comma-separated dialog IDs for targeted reruns")
    parser.add_argument("--cases", default="", help="Optional JSON suite with the same case schema")
    asyncio.run(run(parser.parse_args()))
