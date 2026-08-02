"""The one nightly orchestration. Strict order: facts in (sync every feed), then
attribution (resolve_orphans), then judgments refreshed (recompute_state). A sync
failure raises before recompute — the "never judge stale state" guarantee. The
judgment job (nudges out) is wired in here in Phase 4.
"""

from datetime import UTC, date, datetime

from jobs.close_correlation import correlate_closes
from jobs.dnc_refresh import dnc_refresh
from jobs.sync import sync
from jobs.verify_addresses import verify_addresses
from judgment import digest
from judgment.partner_report import run_partner_reports
from seams.address_verifier import AddressVerifier
from seams.dnc_registry import DncRegistry
from seams.nmc_closes import CloseFeed
from seams.nmc_demos import DemosClient
from seams.response_feed import ResponseFeed
from seams.sender import Sender
from service.assignment import run_expiry_step, run_won_termination_step
from service.execution import recompute_state
from service.ingestion import resolve_orphans


def run_nightly(
    feeds: list[ResponseFeed],
    since: datetime,
    as_of: date | None = None,
    sender: Sender | None = None,
    verifier: AddressVerifier | None = None,
    dnc_registry: DncRegistry | None = None,
    close_feed: CloseFeed | None = None,
    demos_client: DemosClient | None = None,
) -> None:
    for feed in feeds:
        sync(feed, since)  # a feed failure raises here — before recompute
    if verifier is not None:
        # Address standardization is facts-in, like the feeds: it enriches intake rows
        # and can promote a standardized address onto a contact, but it feeds no
        # derivation, so it sits outside the "never judge stale state" ordering. A
        # no-op when nothing is unverified (design §5), and a vendor error on one row
        # never raises — that row simply stays unverified for tomorrow.
        verify_addresses(verifier)
    if dnc_registry is not None:
        # The daily scrub (S-9): facts-in like the feeds — writes dnc_registry and
        # dnc_checked_at columns plus audit events; a no-op when nothing has crossed
        # the 21-day threshold. Skipped when unconfigured (no SAN yet): a missing
        # registry delays scrubbing, and Phase 4's stale-check gate — not this job —
        # is what fails closed for assignment.
        dnc_refresh(dnc_registry)
    resolve_orphans()
    if close_feed is not None:
        # Q10 placement, pinned (revision 6): AFTER resolve_orphans — PostHog signups
        # are contact-less until resolution, so the double-count guard would see
        # nothing on exactly the both-inlets night it exists for — and BEFORE
        # recompute, so `won` derives the same night and the termination step acts.
        correlate_closes(close_feed)
    recompute_state()
    # S-4/S-1 nightly steps — the ordering is load-bearing: after recompute (won
    # derives from fresh state), before digest (nudges route on post-return
    # ownership).
    run_expiry_step()
    run_won_termination_step()
    digest.run(as_of or datetime.now(UTC).date(), sender=sender)  # nudges out, after fresh state
    # The partner report runs LAST — binding: composed before expiry it would tell
    # a partner they hold contacts already returned to the pool (R2, review
    # 2026-07-29). Dark when no sender is configured; failures raise after every
    # partner has been attempted.
    run_partner_reports(sender=sender, demos=demos_client)
