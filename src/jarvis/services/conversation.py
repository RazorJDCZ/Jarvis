from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from dataclasses import dataclass

from jarvis.actions.engine import ActionEngine
from jarvis.actions.models import ActionOutcome
from jarvis.config import Settings, build_system_prompt
from jarvis.providers.brain import AutoBrain, Brain
from jarvis.services.commands import SafeCommandRouter
from jarvis.services.information import InformationVerifier
from jarvis.services.memory import MemoryService
from jarvis.services.profile import LocalProfileStore


@dataclass(frozen=True, slots=True)
class ConversationReply:
    text: str
    provider: str
    action: ActionOutcome | None = None


class ConversationService:
    _GENERIC_FOLLOW_UP = re.compile(
        r"\s*(?:¿)?(?:"
        r"hay algo mas en lo que (?:pueda|puedo) ayudarte|"
        r"en que mas (?:puedo|podria) ayudarte|"
        r"(?:quieres|te gustaria) que (?:te )?(?:ayude|cuente|explique|diga|muestre).+|"
        r"(?:quieres|te gustaria) ver (?:algun|un) ejemplo.+|"
        r"(?:quieres|te gustaria) saber mas.+|"
        r"necesitas ayuda (?:para|con).+|"
        r"necesitas (?:algo|alguna cosa) mas|"
        r"puedo ayudarte (?:con|en) algo mas"
        r")\?\s*$",
        flags=re.IGNORECASE,
    )
    _GENERIC_CLOSING = re.compile(
        r"\s*(?:"
        r"ya tienes todo el contexto listo para seguir hablando.+|"
        r"(?:aqui|ac[aá]) estoy si necesitas.+|"
        r"cuando quieras, (?:puedo|podemos) ayudarte.+|"
        r"si (?:necesitas|quieres) (?:ayuda|que).+(?:dime|avisame).+|"
        r"(?:dado que|ya que).+quizas podrias considerar si .+"
        r")[.!]\s*$",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
        settings: Settings,
        brain: Brain,
        actions: ActionEngine,
        commands: SafeCommandRouter | None = None,
        verifier: InformationVerifier | None = None,
        profile_store: LocalProfileStore | None = None,
        memory: MemoryService | None = None,
    ) -> None:
        self.settings = settings
        self.brain = brain
        self.actions = actions
        self.commands = commands or SafeCommandRouter()
        self.verifier = verifier or InformationVerifier(settings)
        self.profile_store = profile_store or LocalProfileStore(settings.user_profile_path)
        self.memory = memory or MemoryService(settings)
        self._history: OrderedDict[str, list[dict[str, str]]] = OrderedDict()

    @property
    def provider_name(self) -> str:
        if isinstance(self.brain, AutoBrain):
            return self.brain.active_name
        return self.brain.name

    @classmethod
    def _trim_generic_follow_up(cls, response: str) -> str:
        normalized = (
            response.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("Á", "A")
            .replace("É", "E")
            .replace("Í", "I")
            .replace("Ó", "O")
            .replace("Ú", "U")
        )
        match = cls._GENERIC_FOLLOW_UP.search(normalized)
        trimmed = response[: match.start()].rstrip() if match is not None else response.strip()
        normalized_trimmed = (
            trimmed.replace("á", "a")
            .replace("é", "e")
            .replace("í", "i")
            .replace("ó", "o")
            .replace("ú", "u")
            .replace("Á", "A")
            .replace("É", "E")
            .replace("Í", "I")
            .replace("Ó", "O")
            .replace("Ú", "U")
        )
        closing = cls._GENERIC_CLOSING.search(normalized_trimmed)
        return trimmed[: closing.start()].rstrip() if closing is not None else trimmed

    async def reply(
        self,
        session_id: str,
        message: str,
        *,
        remote: bool = False,
    ) -> ConversationReply:
        safe_command = self.commands.try_handle(message)
        if safe_command is not None:
            if safe_command.reset_history:
                self.reset(session_id)
            return ConversationReply(safe_command.response, "safe-command")

        if await asyncio.to_thread(self.memory.is_command, session_id, message):
            profile_summary = self.profile_store.answer("que sabes de mi") or ""
            memory_answer = await asyncio.to_thread(
                self.memory.handle,
                session_id,
                message,
                profile_summary,
            )
            if memory_answer:
                return ConversationReply(memory_answer, "local-memory")

        action = (
            await self.actions.try_handle(session_id, message, remote=True)
            if remote
            else await self.actions.try_handle(session_id, message)
        )
        if action is not None:
            return ConversationReply(action.message, "action-engine", action)

        await asyncio.to_thread(self.memory.learn, message)
        profile_answer = self.profile_store.answer(message)
        verification = None if profile_answer else await self.verifier.verify(message)
        new_session = session_id not in self._history
        if new_session:
            max_sessions = max(1, self.settings.max_sessions)
            while len(self._history) >= max_sessions:
                self._history.popitem(last=False)
            self._history[session_id] = []
        self._history.move_to_end(session_id)
        history = self._history[session_id]
        history.append({"role": "user", "content": message.strip()})
        max_history = max(1, self.settings.max_history_messages)
        history[:] = history[-max_history:]
        if profile_answer:
            history.append({"role": "assistant", "content": profile_answer})
            history[:] = history[-max_history:]
            return ConversationReply(profile_answer, "personal-profile")
        if verification is not None and verification.direct_answer:
            response = verification.direct_answer
            history.append({"role": "assistant", "content": response})
            history[:] = history[-max_history:]
            return ConversationReply(response, "verified-information")

        verification_context = verification.evidence if verification is not None else ""
        memory_context = await asyncio.to_thread(self.memory.context, message)
        recent_context = (
            await asyncio.to_thread(self.memory.recent_context, session_id)
            if new_session
            else ""
        )
        system_prompt = build_system_prompt(
            profile_context=self.profile_store.system_context(),
            verification_context=verification_context,
            memory_context=memory_context,
            recent_context=recent_context,
        )
        messages = [{"role": "system", "content": system_prompt}, *history]
        response = self._trim_generic_follow_up(await self.brain.chat(messages))
        history.append({"role": "assistant", "content": response})
        history[:] = history[-max_history:]
        await asyncio.to_thread(self.memory.remember_exchange, session_id, message, response)
        return ConversationReply(response, self.provider_name)

    def reset(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self.actions.reset(session_id)
        self.memory.reset_session(session_id)

    async def decide_action(
        self,
        session_id: str,
        action_id: str,
        approve: bool | None,
        choice: str | None = None,
    ) -> ConversationReply:
        outcome = await self.actions.decide(session_id, action_id, approve, choice)
        return ConversationReply(outcome.message, "action-engine", outcome)

    def emergency_stop(self, session_id: str) -> dict[str, int]:
        return self.actions.emergency_stop(session_id)
