from __future__ import annotations

import asyncio
import json
import sys

from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import ActionName, ActionStatus
from jarvis.config import Settings


async def verify() -> dict[str, object]:
    settings = Settings(action_model_planning=False)
    engine = ActionEngine(settings)
    windows = engine.catalog.windows
    try:
        opened = await engine.try_handle("dialog-smoke", "abre el bloc de notas")
        notepad = windows.find(
            aliases=("Bloc de notas", "Notepad"),
        )
        editor = next(
            (
                control
                for control in notepad.descendants()
                if windows._control_type(control) in {"Document", "Edit"}
            ),
            None,
        )
        editor.set_edit_text("JARVIS_DIALOG_SMOKE")
        text_written = True
        close_pending = await engine.try_handle(
            "dialog-smoke",
            "cierra la ventana de Bloc de notas",
        )
        dialog_pending = await engine.decide(
            "dialog-smoke",
            close_pending.action_id,
            True,
        )
        options = dialog_pending.details.get("dialog_options", [])
        decided = await engine.try_handle("dialog-smoke", "no guardes")
        return {
            "notepad_opened": opened is not None and opened.status is ActionStatus.COMPLETED,
            "text_typed": text_written,
            "dialog_detected": dialog_pending.name is ActionName.DIALOG_CHOOSE,
            "dialog_waiting": dialog_pending.status is ActionStatus.PENDING,
            "close_result": dialog_pending.status.value,
            "close_message": dialog_pending.message,
            "options": options,
            "voice_choice_completed": decided is not None
            and decided.status is ActionStatus.COMPLETED,
            "dialog_closed": not windows.dialogs(),
        }
    finally:
        for dialog in windows.dialogs():
            discard = next(
                (
                    option
                    for option in dialog.options
                    if option.casefold() in {"no guardar", "don't save", "cancelar", "cancel"}
                ),
                None,
            )
            if discard:
                windows.choose_dialog_option(
                    dialog.parent_handle,
                    dialog.dialog_handle,
                    discard,
                )
        await engine.close()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))


if __name__ == "__main__":
    main()
