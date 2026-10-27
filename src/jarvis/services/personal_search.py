from __future__ import annotations

import asyncio
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9@._+-]+", " ", text).strip()


_FILLERS = frozenset(
    {
        "algo",
        "busca",
        "buscar",
        "donde",
        "encuentra",
        "informacion",
        "jarvis",
        "mio",
        "mis",
        "relacionado",
        "relacionados",
        "sobre",
        "todo",
    }
)


@dataclass(frozen=True, slots=True)
class PersonalSearchResult:
    source: str
    kind: str
    title: str
    detail: str
    timestamp: str
    score: float
    locator: str

    def public(self) -> dict[str, object]:
        return asdict(self)


class PersonalSearchService:
    """Fan-out read-only search across Jarvis' trusted personal data sources."""

    _SOURCE_BONUS = {
        "biblioteca": 7.0,
        "correo": 6.0,
        "memoria": 5.0,
        "appa": 4.0,
        "calendario": 4.0,
        "archivo": 2.0,
    }

    def __init__(self, capabilities: Any) -> None:
        self.capabilities = capabilities
        self.mail: Any | None = None
        self.organizer: Any | None = None
        self.memory: Any | None = None

    def attach(self, *, mail: Any, organizer: Any, memory: Any) -> None:
        self.mail = mail
        self.organizer = organizer
        self.memory = memory

    @staticmethod
    def _tokens(query: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                token
                for token in _normalized(query).split()
                if len(token) >= 2 and token not in _FILLERS
            )
        )[:16]

    @classmethod
    def _score(cls, source: str, text: str, terms: tuple[str, ...], base: float = 0) -> float:
        normalized = _normalized(text)
        matched = sum(term in normalized for term in terms)
        phrase = " ".join(terms)
        score = float(base) + cls._SOURCE_BONUS.get(source, 0.0) + matched * 8.0
        if phrase and phrase in normalized:
            score += 18.0
        return round(score, 2)

    async def _mail(self, query: str, terms: tuple[str, ...]) -> list[PersonalSearchResult]:
        if self.mail is None:
            return []
        payload = await asyncio.to_thread(self.mail.search, query, 12)
        results = []
        for item in payload.get("items", []):
            title = str(item.get("subject") or "Sin asunto")[:240]
            detail = " — ".join(
                part
                for part in (
                    str(item.get("sender") or "")[:180],
                    str(item.get("summary") or "")[:360],
                )
                if part
            )
            results.append(
                PersonalSearchResult(
                    "correo",
                    "mail",
                    title,
                    detail,
                    str(item.get("received") or "")[:80],
                    self._score(
                        "correo",
                        f"{title} {detail}",
                        terms,
                        float(item.get("relevance") or 0) / 4,
                    ),
                    str(item.get("id") or "")[:128],
                )
            )
        return results

    async def _calendar(self, terms: tuple[str, ...]) -> list[PersonalSearchResult]:
        if self.organizer is None:
            return []
        payload = await asyncio.to_thread(self.organizer.calendar_events)
        results = []
        for item in payload.get("events", [])[:500]:
            title = str(item.get("title") or "Evento")[:240]
            detail = str(item.get("description") or item.get("source") or "")[:360]
            combined = f"{title} {detail}"
            if not any(term in _normalized(combined) for term in terms):
                continue
            results.append(
                PersonalSearchResult(
                    "calendario",
                    "event",
                    title,
                    detail,
                    str(item.get("start_at") or "")[:80],
                    self._score("calendario", combined, terms),
                    str(item.get("id") or "")[:256],
                )
            )
        return results

    async def _appa(self, session_id: str, terms: tuple[str, ...]) -> list[PersonalSearchResult]:
        try:
            connector = self.capabilities.connectors.require_appa()
            context = await connector.personal_context()
        except Exception:
            tasks = await self.capabilities.connectors.local.list_tasks(
                session_id, include_completed=False
            )
            context = {
                "tasks": [item.as_dict() for item in tasks],
                "projects": [],
                "inbox": [],
                "events": [],
            }
        results: list[PersonalSearchResult] = []
        mappings = (
            ("tasks", "task", "title", "notes", "due"),
            ("projects", "project", "name", "description", "updated_at"),
            ("inbox", "inbox", "text", "", "created_at"),
        )
        for collection, kind, title_key, detail_key, time_key in mappings:
            for item in context.get(collection, [])[:100]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get(title_key) or "")[:240]
                detail = str(item.get(detail_key) or "")[:360] if detail_key else ""
                combined = f"{title} {detail}"
                if not any(term in _normalized(combined) for term in terms):
                    continue
                results.append(
                    PersonalSearchResult(
                        "appa",
                        kind,
                        title,
                        detail,
                        str(item.get(time_key) or "")[:80],
                        self._score("appa", combined, terms),
                        str(item.get("id") or "")[:128],
                    )
                )
        return results

    async def _memory(self, query: str, terms: tuple[str, ...]) -> list[PersonalSearchResult]:
        if self.memory is None:
            return []
        entries, entities = await asyncio.gather(
            asyncio.to_thread(self.memory.store.relevant, query, 12),
            asyncio.to_thread(self.memory.store.relevant_entities, query, 12),
        )
        results = [
            PersonalSearchResult(
                "memoria",
                "memory",
                item.content[:240],
                item.category[:80],
                item.updated_at,
                self._score("memoria", f"{item.category} {item.content}", terms),
                item.memory_key,
            )
            for item in entries
        ]
        results.extend(
            PersonalSearchResult(
                "memoria",
                "entity",
                item.name[:240],
                " — ".join(part for part in (item.relation, item.details) if part)[:360],
                item.updated_at,
                self._score(
                    "memoria",
                    f"{item.kind} {item.name} {item.relation} {item.details}",
                    terms,
                ),
                item.entity_id,
            )
            for item in entities
        )
        return results

    async def _knowledge(
        self, session_id: str, query: str, terms: tuple[str, ...]
    ) -> list[PersonalSearchResult]:
        items = await asyncio.to_thread(self.capabilities.knowledge.search, session_id, query, 8)
        return [
            PersonalSearchResult(
                "biblioteca",
                "document",
                str(item.title)[:240],
                str(item.excerpt)[:360],
                "",
                self._score("biblioteca", f"{item.title} {item.excerpt}", terms, 10),
                str(item.source_id)[:128],
            )
            for item in items
        ]

    async def _files(self, query: str, terms: tuple[str, ...]) -> list[PersonalSearchResult]:
        payload = await asyncio.to_thread(self.capabilities.file_search.search, query, limit=12)
        return [
            PersonalSearchResult(
                "archivo",
                "file",
                str(item.get("name") or "")[:240],
                str(item.get("path") or "")[:500],
                str(item.get("modified_at") or "")[:80],
                self._score(
                    "archivo",
                    f"{item.get('name', '')} {item.get('path', '')}",
                    terms,
                    float(item.get("score") or 0) / 5,
                ),
                str(item.get("path") or "")[:1_000],
            )
            for item in payload.get("items", [])
        ]

    async def search(self, session_id: str, query: str, *, limit: int = 25) -> dict[str, object]:
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise ValueError("La búsqueda personal debe contener entre 1 y 300 caracteres")
        terms = self._tokens(query)
        if not terms:
            raise ValueError("Indica el tema, nombre o dato que quieres localizar")
        jobs: dict[str, Callable[[], Awaitable[list[PersonalSearchResult]]]] = {
            "correo": lambda: self._mail(query, terms),
            "calendario": lambda: self._calendar(terms),
            "appa": lambda: self._appa(session_id, terms),
            "memoria": lambda: self._memory(query, terms),
            "biblioteca": lambda: self._knowledge(session_id, query, terms),
            "archivo": lambda: self._files(query, terms),
        }

        async def guarded(name: str, factory: Callable[[], Awaitable[list[PersonalSearchResult]]]):
            try:
                return name, await asyncio.wait_for(factory(), timeout=8.0), ""
            except TimeoutError:
                return name, [], "tiempo agotado"
            except Exception:
                return name, [], "no disponible"

        gathered = await asyncio.gather(
            *(guarded(name, factory) for name, factory in jobs.items())
        )
        results: list[PersonalSearchResult] = []
        source_status: dict[str, str] = {}
        for name, items, error in gathered:
            source_status[name] = error or "ok"
            results.extend(items)
        results.sort(key=lambda item: (item.score, item.timestamp), reverse=True)
        safe_limit = max(1, min(int(limit), 50))
        selected = results[:safe_limit]
        return {
            "query": query.strip(),
            "items": [item.public() for item in selected],
            "count": len(selected),
            "sources": source_status,
            "read_only": True,
            "generated_at": datetime.now(UTC).isoformat(),
        }
