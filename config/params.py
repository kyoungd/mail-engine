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

# DNC scrub cadence (partner-lead-assignment.md §6/S-9): re-check a contact when its
# stamp is older than this. 21 days keeps every dialable contact inside the federal
# 31-day safe-harbor window with margin for missed runs.
DNC_RECHECK_DAYS = 21

# The assignment gate's freshness bound (§6): a contact whose check is older than
# the federal safe-harbor window is unassignable until the scrub catches up.
DNC_FRESHNESS_DAYS = 31

# Batch sizing (§5): ~1.5 contacts worked per dial-hour × 8 weeks of capacity,
# rounded to the nearest 50. Floor and cap apply to DERIVED batches only — an
# explicit founder count (the Step 11 trial batch) bypasses both. Expiry — not a
# holdings ceiling — carries the anti-hoarding load (S-3), one global constant.
BATCH_HOURS_MULTIPLIER = 12
BATCH_FLOOR = 100
BATCH_CAP = 500
BATCH_ROUND = 50
ASSIGNMENT_EXPIRY_DAYS = 90
# The personal-list window (partner-sourced-leads.md §4, operator 2026-08-06): a
# number a partner collected is on their sheet for this long from the recorded
# permission date, with NO FTC-registry check. Flat 90 days is the shorter of the
# two legal lives (oral inquiry ~3 months; written until revoked), so it is safe
# for both. Our own do_not_call and tombstones are never waived by it.
PERSONAL_WINDOW_DAYS = 90


def derived_batch_size(weekly_hours: int) -> int:
    """§5's table: batch ≈ 12 × weekly hours, rounded to the nearest 50,
    floor 100, cap 500."""
    raw = BATCH_HOURS_MULTIPLIER * weekly_hours
    rounded = round(raw / BATCH_ROUND) * BATCH_ROUND
    return max(BATCH_FLOOR, min(BATCH_CAP, rounded))


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
    # Nudge YOUNG when the newest registry version ages past this — a week before
    # the 31-day safe-harbor wall (Phase 2).
    dnc_version_alert_days: int = 24
    # The day-30 activity checkpoint on a live batch (§5 amendment 2026-08-05):
    # visibility to the operator, never auto-reclaim.
    batch_checkpoint_days: int = 30


DEFAULT_PARAMS = Params()
