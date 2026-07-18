from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from jarvis.config import SYSTEM_PROMPT, Settings
from jarvis.providers.brain import AutoBrain, Brain
from jarvis.services.commands import SafeCommandRouter


@dataclass(frozen=True, slots=True)
class ConversationReply:
    text: str
    provider: str


class ConversationService:
    def __init__(
        self,
        settings: Settings,
        brain: Brain,
        commands: SafeCommandRouter | None = None,
    ) -> None:
        self.settings = settings
        self.brain = brain
        self.commands = commands or SafeCommandRouter(settings)
        self._history: OrderedDict[str, list[dict[str, str]]] = OrderedDict()

    @property
    def provider_name(self) -> str:
        if isinstance(self.brain, AutoBrain):
            return self.brain.active_name
        return self.brain.name

    async def reply(self, session_id: str, message: str) -> ConversationReply:
        safe_command = self.commands.try_handle(message)
        if safe_command is not None:
            if safe_command.reset_history:
                self.reset(session_id)
            return ConversationReply(safe_command.response, "safe-command")

        if session_id not in self._history:
            max_sessions = max(1, self.settings.max_sessions)
            while len(self._history) >= max_sessions:
                self._history.popitem(last=False)
            self._history[session_id] = []
        self._history.move_to_end(session_id)
        history = self._history[session_id]
        history.append({"role": "user", "content": message.strip()})
        max_history = max(1, self.settings.max_history_messages)
        history[:] = history[-max_history:]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
        response = await self.brain.chat(messages)
        history.append({"role": "assistant", "content": response})
        history[:] = history[-max_history:]
        return ConversationReply(response, self.provider_name)

    def reset(self, session_id: str) -> None:
        self._history.pop(session_id, None)
