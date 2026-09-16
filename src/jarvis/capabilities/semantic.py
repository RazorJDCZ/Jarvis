from __future__ import annotations

import heapq
import json
import math
import re
from urllib.parse import urlsplit

import httpx

from jarvis.capabilities.stores import KnowledgeResult, KnowledgeStore


class SemanticKnowledgeStore(KnowledgeStore):
    """Hybrid local retrieval. Vectors are generated only for explicitly indexed documents."""

    def __init__(self, path, settings):
        super().__init__(path)
        self.settings = settings
        self.model = "embeddinggemma"
        self.last_error = ""
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS knowledge_chunks (
                source_id TEXT NOT NULL, part INTEGER NOT NULL, text TEXT NOT NULL,
                vector TEXT NOT NULL, model TEXT NOT NULL, PRIMARY KEY(source_id, part))""")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        url = urlsplit(self.settings.ollama_url)
        if url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Los documentos sólo pueden procesarse en Ollama local")
        with httpx.Client(timeout=45, trust_env=False) as client:
            response = client.post(
                self.settings.ollama_url + "/api/embed",
                json={
                    "model": self.model,
                    "input": texts,
                    "keep_alive": "0s",
                    "options": {"num_gpu": 0, "num_thread": 2},
                },
            )
            response.raise_for_status()
        vectors = response.json()["embeddings"]
        if len(vectors) != len(texts) or any(
            not v or not all(isinstance(x, int | float) and math.isfinite(x) for x in v)
            for v in vectors
        ):
            raise ValueError("Representación semántica inválida")
        return vectors

    def index_vectors(self, source_id: str, session: str) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT text FROM capability_knowledge_sources WHERE source_id=? AND session_id=?",
                (source_id, session),
            ).fetchone()
        if row is None:
            raise ValueError("Fuente no encontrada en esta sesión")
        chunks = []
        for page in re.split(r"(?=\[Página \d+\])", row["text"]):
            label = re.match(r"\[Página \d+\]", page)
            prefix = label.group() + " " if label else ""
            for offset in range(0, len(page), 1000):
                chunk = page[offset : offset + 1200].strip()
                if chunk:
                    chunks.append(prefix + chunk)
        chunks = chunks[:120]
        vectors = []
        for offset in range(0, len(chunks), 16):
            vectors.extend(self._embed(chunks[offset : offset + 16]))
        with self._connect() as db:
            db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source_id,))
            db.executemany(
                "INSERT INTO knowledge_chunks VALUES (?, ?, ?, ?, ?)",
                [
                    (source_id, n + 1, chunk, json.dumps(vector), self.model)
                    for n, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
        self.last_error = ""
        return len(chunks)

    def upsert_source(self, session_id, title, text, origin):
        source = super().upsert_source(session_id, title, text, origin)
        with self._connect() as db:
            db.execute("DELETE FROM knowledge_chunks WHERE source_id=?", (source.source_id,))
        if not self.settings.semantic_enabled:
            return source
        try:
            self.index_vectors(source.source_id, session_id)
        except (httpx.HTTPError, ValueError, KeyError):
            self.last_error = "Índice textual listo; el modelo semántico no está disponible."
        return source

    def search(self, session_id, query, limit=5):
        lexical = super().search(session_id, query, limit)
        if not self.settings.semantic_enabled:
            return lexical
        with self._connect() as db:
            exists = db.execute(
                """SELECT 1 FROM knowledge_chunks c
                JOIN capability_knowledge_sources s ON c.source_id=s.source_id
                WHERE s.session_id=? AND c.model=? LIMIT 1""",
                (session_id, self.model),
            ).fetchone()
        if not exists:
            return lexical
        try:
            query_vector = self._embed([query])[0]
        except (httpx.HTTPError, ValueError, KeyError):
            return lexical
        lexical_ids = {item.source_id for item in lexical}
        ranked = []
        with self._connect() as db:
            rows = db.execute(
                """SELECT c.*, s.title, s.origin FROM knowledge_chunks c
                JOIN capability_knowledge_sources s ON c.source_id=s.source_id
                WHERE s.session_id=? AND c.model=?""",
                (session_id, self.model),
            )
            # Stream vectors from SQLite and retain only top results, not the whole library.
            for index, row in enumerate(rows):
                vector = json.loads(row["vector"])
                if len(vector) != len(query_vector):
                    continue
                similarity = sum(a * b for a, b in zip(vector, query_vector, strict=True))
                norm = math.sqrt(sum(a * a for a in vector) * sum(b * b for b in query_vector))
                similarity /= max(norm, 1e-12)
                if similarity >= 0.3:
                    score = similarity + (0.04 if row["source_id"] in lexical_ids else 0)
                    heapq.heappush(ranked, (score, index, row))
                    if len(ranked) > max(1, min(limit, 20)):
                        heapq.heappop(ranked)
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        result = [
            KnowledgeResult(
                row["source_id"],
                row["title"],
                row["origin"],
                row["text"],
                f"{row['title']} — {row['origin']} — fragmento {row['part']}",
            )
            for _, _, row in ranked
        ]
        return tuple(result) if result else lexical
