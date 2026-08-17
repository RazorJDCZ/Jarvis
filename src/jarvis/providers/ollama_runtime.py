from __future__ import annotations

import asyncio

# Every Ollama consumer shares one gate. Jarvis can receive local and mobile requests at the
# same time, but this PC does not have enough spare memory to load conversation, planning and
# vision models concurrently. Serializing inference prevents the orphan/overcommit failures that
# previously disabled the voice pipeline.
OLLAMA_RUNTIME_LOCK = asyncio.Lock()
