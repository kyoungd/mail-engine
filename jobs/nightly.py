"""The one nightly orchestration. Strict order: facts in (the DNC scrub, when a
registry is handed in), then attribution (resolve_orphans), then the customer feed,
then judgments refreshed (recompute_state), then the assignment steps that read them.
"""

from jobs.close_correlation import correlate_closes
from jobs.dnc_refresh import dnc_refresh
from seams.dnc_registry import DncRegistry
from seams.nmc_closes import CloseFeed
from service.assignment import run_expiry_step, run_won_termination_step
from service.ingestion import resolve_orphans
from service.state import recompute_state


def run_nightly(
    dnc_registry: DncRegistry | None = None,
    close_feed: CloseFeed | None = None,
) -> None:
    if dnc_registry is not None:
        # The daily scrub (S-9): writes dnc_registry and dnc_checked_at columns plus
        # audit events; a no-op when nothing has crossed the 21-day threshold. Skipped
        # when unconfigured: a missing registry delays scrubbing, and the stale-check
        # gate — not this job — is what fails closed for assignment.
        dnc_refresh(dnc_registry)
    resolve_orphans()
    if close_feed is not None:
        # Q10 placement, pinned (revision 6): AFTER resolve_orphans, and BEFORE
        # recompute, so `won` derives the same night and the termination step acts.
        correlate_closes(close_feed)
    recompute_state()
    # The ordering is load-bearing: after recompute (won derives from fresh state).
    run_expiry_step()
    run_won_termination_step()
