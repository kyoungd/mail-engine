"""Address standardization — the job behind the `AddressVerifier` seam (design §5).

Verification is a JOB rather than part of ingest for a structural reason, not a
scheduling one: the dependency rule bars `service` from importing `seams`, so
`load_list` cannot call a verifier — which is exactly why NCOA/CASS was never in it.

Two phases, and the design turns on the distinction:

  STAMP    Sweep intake rows where `std_verified_at is null`, call the seam once per
           row, store the result. A vendor VERDICT — including `undeliverable` and
           "no delivery point" — is a RESULT: stamp it and never call again, because
           USPS data shifts and the snapshot is what keeps audience resolution
           reproducible. A vendor ERROR stamps nothing: the row stays unverified and
           the NEXT run retries it. No per-call retry loop, and a transient failure
           never permanently consumes the one call this row gets.

  INHERIT  Contacts were created with the raw picked address, before any verification
           existed. For every contact whose PRIMARY row now carries a usable
           standardized address and whose `addr_validated_at` is still null, copy it up
           and stamp. Any other outcome leaves the raw address alone — it is the better
           fact when standardization failed — and leaves the guard null rather than
           locking in a non-address.

The null guard is the whole safety property: it makes re-runs no-ops, and because
`update_contact_address` stamps the same column, an operator's correction is never
overwritten. Enforced by code, not convention.

Runner: the nightly (a no-op when nothing is unverified), plus manual invocation for the
one-time backfill or right after a large ingest. Verification may therefore lag an ingest
by up to a day, which is safe: an unverified row is never excluded from an audience,
merely not yet deduplicable.
"""

import argparse
import sys

from psycopg import sql

from db.session import transaction
from domain.types import VerifyReport
from seams.address_verifier import (
    UNDELIVERABLE,
    AddressVerificationError,
    AddressVerifier,
    VerificationResult,
)

INTAKE_TABLES = ("intake_cslb_ca", "intake_fbn_ca")

_ADDRESS_COLS = ("addr_line1", "addr_line2", "addr_city", "addr_state", "addr_zip")


def _unverified(cur, table: str) -> list[tuple]:
    cur.execute(
        sql.SQL("select id, {cols} from {t} where std_verified_at is null order by id").format(
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in _ADDRESS_COLS),
            t=sql.Identifier(table),
        )
    )
    return cur.fetchall()


def _stamp(cur, table: str, row_id, result: VerificationResult) -> None:
    cur.execute(
        sql.SQL(
            "update {t} set std_addr_line1 = %s, std_addr_line2 = %s, std_addr_city = %s, "
            "std_addr_state = %s, std_addr_zip = %s, delivery_point = %s, "
            "deliverability = %s, std_verified_at = now() where id = %s"
        ).format(t=sql.Identifier(table)),
        (
            result.std_addr_line1,
            result.std_addr_line2,
            result.std_addr_city,
            result.std_addr_state,
            result.std_addr_zip,
            result.delivery_point,
            result.deliverability,
            row_id,
        ),
    )


def _inherit(cur, table: str) -> int:
    """Copy usable standardized addresses from primary rows onto their contacts.

    The WHERE clause is the design's inherit condition in full: the row is the contact's
    primary, it has been verified, its verdict is deliverable-family (only `undeliverable`
    disqualifies — the `deliverable_*_unit` variants are mailable, §6), it has a delivery
    point AND the components to write, and the contact's guard is still null."""
    cur.execute(
        sql.SQL(
            "update contacts c set addr_line1 = i.std_addr_line1, "
            "addr_line2 = i.std_addr_line2, addr_city = i.std_addr_city, "
            "addr_state = i.std_addr_state, addr_zip = i.std_addr_zip, "
            "addr_validated_at = now() "
            "from {t} i "
            "where i.contact_id = c.id and i.is_primary "
            "and i.std_verified_at is not null "
            "and i.deliverability is distinct from %s "
            "and coalesce(i.delivery_point, '') <> '' "
            "and coalesce(i.std_addr_line1, '') <> '' "
            "and coalesce(i.std_addr_city, '') <> '' "
            "and coalesce(i.std_addr_zip, '') <> '' "
            "and c.addr_validated_at is null"
        ).format(t=sql.Identifier(table)),
        (UNDELIVERABLE,),
    )
    return cur.rowcount


def verify_addresses(verifier: AddressVerifier, limit: int | None = None) -> VerifyReport:
    """Stamp every unverified intake row, then inherit onto the contacts that earned it.

    Each row is stamped in its own transaction so one vendor error cannot roll back the
    rows already done — a row that errors forever must stay visible as ever-unverified
    without holding up everything behind it."""
    stamped = errored = inherited = 0
    remaining = limit

    for table in INTAKE_TABLES:
        with transaction() as conn:
            with conn.cursor() as cur:
                rows = _unverified(cur, table)
        if remaining is not None:
            rows = rows[:remaining]

        for row_id, *address in rows:
            payload: dict[str, str] = {
                col: (value or "") for col, value in zip(_ADDRESS_COLS, address, strict=True)
            }
            try:
                result = verifier.verify(payload)
            except AddressVerificationError:
                errored += 1
                continue
            with transaction() as conn:
                with conn.cursor() as cur:
                    _stamp(cur, table, row_id, result)
            stamped += 1
            if remaining is not None:
                remaining -= 1

    with transaction() as conn:
        with conn.cursor() as cur:
            for table in INTAKE_TABLES:
                inherited += _inherit(cur, table)

    return VerifyReport(stamped=stamped, errored=errored, inherited=inherited)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_addresses",
        description="Standardize intake addresses through the address-verification seam "
        "and inherit the result onto contacts (design ingest-contact-migration.md §5).",
        epilog=(
            "Each row is verified ONCE: a verdict (including undeliverable) is stamped and\n"
            "never re-requested, while a vendor error leaves the row for the next run.\n\n"
            "Examples:\n"
            "  uv run python -m jobs.verify_addresses              # sweep everything unverified\n"
            "  uv run python -m jobs.verify_addresses --limit 100  # a costed slice first\n"
            "  uv run python -m jobs.verify_addresses --fake       # no vendor calls, no spend\n\n"
            "Runs nightly as well; the sweep is a no-op when nothing is unverified.\n"
            "Requires OWNER_DATABASE_URL and (unless --fake) LOB_API_KEY — make targets\n"
            "source .env; this module does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="stamp at most N rows per intake table (the backfill is billable — cost it first)",
    )
    parser.add_argument(
        "--fake", action="store_true",
        help="use the FakeVerifier: no vendor calls, no spend (smoke-testing the wiring)",
    )
    args = parser.parse_args(argv)

    if args.fake:
        from seams.fakes import FakeVerifier

        verifier: AddressVerifier = FakeVerifier()
    else:
        from seams.lob_address import LobAddressVerifier

        verifier = LobAddressVerifier.from_env()

    report = verify_addresses(verifier, limit=args.limit)
    print(
        f"stamped={report.stamped} errored={report.errored} inherited={report.inherited}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
