"""The NMC close feed (nmc-close-feed-contract.md, RATIFIED 2026-07-29; §2 rewritten
2026-07-31 against the verified Medusa schema). THE one place a Medusa rename must be
repaired — the field mapping below is the contract's table, verbatim.

Transport: a READ-ONLY connection to the Medusa database (`MEDUSA_DATABASE_URL`,
the `select`-only role — which does not exist yet; until it does, only the Fake
runs). Two databases, correlate in app code, never a join across them (the §2 join
is Medusa-internal and legal).

The spine is `customer` — an attribution row exists only for closes that carried a
rep or a `?r=` source, so tag-less closes (organic, landing-page guest checkout)
would be invisible to an attribution-table feed. `raw_code` classification against
`nmc_partner_code` happens here (same connection, granted table); classification
against mail-engine's own piece codes happens in the consumer (no grant needed).
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psycopg

_PAGE_SIZE = 500

# The contract §2 query, verbatim in shape: customer spine, attribution LEFT-JOINed.
_CLOSES_SQL = """
SELECT c.id, c.created_at, c.email,
       c.metadata->>'business_phone'          AS raw_phone,
       c.metadata->>'nmc_subscription_status' AS subscription_status,
       a.sold_by,
       UPPER(COALESCE(a.referral_code, a.source)) AS raw_code,
       a.signed_up_via
FROM customer c
LEFT JOIN nmc_sales_attribution a ON a.customer_id = c.id
WHERE c.created_at > %s
  AND c.email NOT LIKE 'smoke-test+%%'
  AND c.email NOT LIKE 'e2e-%%'
ORDER BY c.created_at, c.id
LIMIT %s
"""


@dataclass(frozen=True)
class Close:
    """One close, in the contract's shape (§2's field table)."""

    id: str                      # customer.id — stable, the idempotency key (§4)
    recorded_at: datetime        # customer.created_at — the watermark field (§5)
    occurred_at: datetime        # := recorded_at for kind signup_completed
    kind: str                    # 'signup_completed' (trial_to_paid: never yet, §6)
    phone_e164: str | None       # normalized by the consumer; late-arriving (§2)
    partner_code: str | None     # raw_code matched in nmc_partner_code
    mailer_code: str | None      # raw_code, for the consumer's own-piece match
    sold_by: int | None          # roster rep id → partners.sales_rep_id
    signed_up_via: str | None    # audit payload only, never branched on
    subscription_status: str | None  # audit payload only, never a conversion signal


class CloseFeed(Protocol):
    def closes(self, since: datetime) -> Iterator[Close]:
        """Yield closes recorded after `since`, ordered by (recorded_at, id).
        Re-serving an already-served row is expected and safe (§4)."""
        ...


class NmcCloseFeed:
    """The real feed over the read-only Medusa connection."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url

    @classmethod
    def from_env(cls) -> "NmcCloseFeed":
        url = os.environ.get("MEDUSA_DATABASE_URL", "")
        if not url:
            raise ValueError("MEDUSA_DATABASE_URL is not set")
        return cls(url)

    def closes(self, since: datetime) -> Iterator[Close]:
        with psycopg.connect(self._url) as conn:
            with conn.cursor() as cur:
                # the registry snapshot for raw_code classification (§2)
                cur.execute("select upper(code) from nmc_partner_code")
                registry = {r[0] for r in cur.fetchall()}

                bound = since
                while True:
                    cur.execute(_CLOSES_SQL, (bound, _PAGE_SIZE))
                    rows = cur.fetchall()
                    for (cid, created_at, _email, raw_phone, sub_status, sold_by,
                         raw_code, signed_up_via) in rows:
                        in_registry = raw_code in registry if raw_code else False
                        yield Close(
                            id=cid,
                            recorded_at=created_at,
                            occurred_at=created_at,
                            kind="signup_completed",
                            phone_e164=raw_phone,
                            partner_code=raw_code if in_registry else None,
                            # not in the registry ⇒ candidate mailer code; the
                            # consumer matches it against its own pieces, and
                            # page-default noise falls out there (§2)
                            mailer_code=None if in_registry else raw_code,
                            sold_by=sold_by,
                            signed_up_via=signed_up_via,
                            subscription_status=sub_status,
                        )
                    if len(rows) < _PAGE_SIZE:
                        return
                    bound = rows[-1][1]
