"""The Rule contract the nightly job discovers and runs, plus the shapes the digest
produces. Tier 1: a rule detects WHO and WHEN (deterministic SQL over state). Tier 2:
the composer writes WHAT. A rule never decides *whether* to fire beyond its condition."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from config.params import Params


class Recipient(Enum):
    YOUNG = "young"          # always Young, regardless of contact
    DEAL_OWNER = "deal_owner"  # the founder who owns the contact


@dataclass(frozen=True)
class Hit:
    contact_id: UUID | None  # None for wave-level and roll-up hits
    wave_id: UUID | None
    facts: dict[str, Any] = field(default_factory=dict)  # what matched — the audit answer


class Rule(Protocol):
    name: str      # 'quiet_reengage' — appears verbatim in the nudge.sent payload
    priority: int  # digest ranking; lower fires first
    recipient: Recipient
    nudge: str     # short intent, used by the template brief

    def evaluate(self, cur, params: Params, as_of: date) -> list[Hit]:
        ...


@dataclass(frozen=True)
class ComposedNudge:
    rule: str
    recipient: str  # resolved founder
    contact_id: UUID | None
    wave_id: UUID | None
    brief: str
    priority: int


@dataclass(frozen=True)
class JudgmentResult:
    sent: dict[str, list[ComposedNudge]]  # founder -> nudges sent this morning, in order
    deferred: list[ComposedNudge]         # over budget, re-evaluated tomorrow
