"""The single model-call wrapper. The composer and (later) note structuring share it.
Only the interface lives here today; the real Anthropic-backed client is deferred until
credentials and the dependency are wired — the composer falls back to a template when no
client is supplied, so nothing downstream depends on the model."""

from typing import Protocol


class AiClient(Protocol):
    def complete(self, prompt: str) -> str:
        """Return the model's completion for `prompt`. May raise on failure — the
        composer catches it and falls back to a template."""
        ...
