"""The one nightly orchestration. Strict order: facts in (sync every feed), then
attribution (resolve_orphans), then judgments refreshed (recompute_state). A sync
failure raises before recompute — the "never judge stale state" guarantee. The
judgment job (nudges out) is wired in here in Phase 4.
"""

from datetime import datetime

from seams.response_feed import ResponseFeed
from service.execution import recompute_state
from service.ingestion import resolve_orphans
from jobs.sync import sync


def run_nightly(feeds: list[ResponseFeed], since: datetime) -> None:
    for feed in feeds:
        sync(feed, since)  # a feed failure raises here — before recompute
    resolve_orphans()
    recompute_state()
    # Phase 4: judgment.run(as_of=today) — nudges out, after fresh state.
