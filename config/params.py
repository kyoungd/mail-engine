"""Judgment parameters (judgment job §4). Start values from the design; injectable so
tests can move a threshold without touching a rule. The runtime-tunable config table
(parameter history as events) is a later enhancement — these defaults are the source
today."""

from dataclasses import dataclass
from uuid import UUID

# The house account's partner row (partner-lead-assignment.md §7, S-11): a fixed,
# migration-seeded uuid — what every return-to-house set_owner call targets, what
# S-8's genesis rule resolves to, and what _resolve_recipient's YOUNG branch returns.
# Must equal the id seeded by db/migrations/0009.partner-custody.sql. Nobody invents
# this value; everybody imports it.
HOUSE_PARTNER_ID = UUID("00000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class Params:
    quiet_days: int = 4
    stall_days: int = 14
    partial_days: int = 4
    fail_pct: float = 0.08
    resp_check_days: int = 10
    lead_days: int = 3
    age_out_days: int = 30
    nudge_budget: int = 5
    cooldown_days: int = 3
    expire_days: int = 5
    orphan_max: int = 20


DEFAULT_PARAMS = Params()
