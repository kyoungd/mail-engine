"""The DNC-registry seam (partner-lead-assignment.md §6/S-9, Phase 2).

Anti-corruption boundary for the FTC national do-not-call registry. The portal at
telemarketing.donotcall.gov serves per-area-code FULL lists and change lists under
an org Subscription Account Number (SAN); full-list diff is the correct v1, change
lists an optimization. Per the dependency rule, `seams` is imported only by `jobs`
and `service/execution` — the scrub is `jobs/dnc_refresh`; `assign_batch` never
touches this (it reads the columns the scrub wrote).

The real FTC client requires the SAN, which does not exist yet (Phase 0's lead-time
item) — and the portal's file format is unverifiable from this repo until it does
(the verify-external-facts rule). Until then `FakeDncRegistry` is the only
implementation; the real client lands as a sibling class here once the SAN grants
access to a real file to pin the parser against.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class DncRegistry(Protocol):
    """A registry snapshot: one version string, per-area-code number sets."""

    def version(self) -> str:
        """The registry version this snapshot represents. The scrub stamps it on
        every check event; same version twice must be a no-op (external_id
        dedupe), which is what makes re-runs idempotent."""
        ...

    def numbers(self, area_code: str) -> frozenset[str]:
        """Registered numbers for one area code, as 10-digit national strings
        (no +1). Contacts' E.164 phones are stripped of the +1 before the
        membership test."""
        ...
