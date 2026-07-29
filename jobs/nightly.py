"""The one nightly orchestration. Strict order: facts in (sync every feed), then
attribution (resolve_orphans), then judgments refreshed (recompute_state). A sync
failure raises before recompute — the "never judge stale state" guarantee. The
judgment job (nudges out) is wired in here in Phase 4.
"""

from datetime import UTC, date, datetime

from jobs.sync import sync
from jobs.verify_addresses import verify_addresses
from judgment import digest
from seams.address_verifier import AddressVerifier
from seams.response_feed import ResponseFeed
from seams.sender import Sender
from service.execution import recompute_state
from service.ingestion import resolve_orphans


def run_nightly(
    feeds: list[ResponseFeed],
    since: datetime,
    as_of: date | None = None,
    sender: Sender | None = None,
    verifier: AddressVerifier | None = None,
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
    resolve_orphans()
    recompute_state()
    digest.run(as_of or datetime.now(UTC).date(), sender=sender)  # nudges out, after fresh state
