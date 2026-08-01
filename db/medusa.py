"""The THIRD connection — the read-only Medusa read (nmc-close-feed-contract.md §1,
project plan A2). Deliberately its own module: it must never reuse `db/session.py`
or `db/readonly.py`, because those are mail-engine's OWN database and this is an
external system's (the two-database rule — two connections, correlate in app code,
never a join across them).

Role: `medusa_nmc_ro` — SELECT on exactly three tables (PRD § Production connection
strings). Unset env is a STATE, not an error: the close feed simply stays off
(`nightly_cli` skips it), which is production's posture until Stage B1 turns it on.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


def medusa_readonly_url() -> str | None:
    """The credential if configured, else None — never throws. Callers that can
    run without the feed (the nightly) branch on this; callers that cannot
    (the feed itself) raise their own error."""
    return os.environ.get("MEDUSA_READONLY_URL") or None


@contextmanager
def medusa_connection() -> Iterator[psycopg.Connection]:
    """A read-only connection to the Medusa DB. Raises when unconfigured — reach
    for `medusa_readonly_url()` first if absence is survivable."""
    url = medusa_readonly_url()
    if not url:
        raise RuntimeError(
            "MEDUSA_READONLY_URL is not set (the read-only Medusa credential — "
            "see PRD § Production connection strings)"
        )
    with psycopg.connect(url) as conn:
        conn.read_only = True
        yield conn
