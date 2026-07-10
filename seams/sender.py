"""The outbound-message seam: one morning digest per founder through NMC's own
sending path. Only the interface lives here; the real NMC-backed sender is deferred
until credentials, exactly like the print and response vendors. The judgment digest
calls a sender only when one is injected — silence needs none."""

from typing import Protocol


class Sender(Protocol):
    def send(self, founder: str, message: str) -> None:
        """Deliver one assembled digest to a founder (SMS or email, the impl's choice)."""
        ...
