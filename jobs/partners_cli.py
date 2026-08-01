"""Operator CLI for the partners table (partner-lead-assignment.md Phase 1).

Upsert by name: `set` on a name that does not exist yet CREATES it (revision 6 — a
mutate-only CLI cannot create partner #2, the same insert-path hole as TD-2's
activation table). The table needs a writer beyond its migration seed: Phase 0's
answers land through it, S-3's batch resizing actuates through weekly_hours, and
Step 12's "remove lead access" flips status. The registration runbook (implementation
plan, Phase 1): create the roster row on the main site first, then `set` here with
--sales-rep-id <roster id> and --partner-code <code>.
"""

import argparse
import sys

from psycopg import sql

from db.session import transaction

_EXAMPLES = """\
examples:
  # Register a partner (roster row exists on the main site; prod rep id shown)
  python -m jobs.partners_cli set "John" --channel email \\
      --channel-address john@example.com --hours 10 --radius 20 \\
      --sales-rep-id 3 --partner-code JO-01

  # Step 12: remove lead access
  python -m jobs.partners_cli set "John" --status inactive

  # Show the roster
  python -m jobs.partners_cli list
"""

# CLI flag -> column. Only flags the operator actually passed are written, so a
# bare `set NAME --hours 15` never nulls the untouched columns.
_FIELD_COLUMNS = {
    "channel": "channel",
    "channel_address": "channel_address",
    "weekly_hours": "weekly_hours",
    "radius_miles": "radius_miles",
    "status": "status",
    "sales_rep_id": "sales_rep_id",
    "partner_code": "partner_code",
    "addr_line1": "base_addr_line1",
    "addr_city": "base_addr_city",
    "addr_state": "base_addr_state",
    "addr_zip": "base_addr_zip",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partners",
        description="Create, update, and list partner rows (upsert by name).",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    set_parser = sub.add_parser(
        "set", help="Create or update a partner by name (upsert)"
    )
    set_parser.add_argument("name", help="Partner name (the upsert key)")
    set_parser.add_argument("--channel", choices=["email", "sms"])
    set_parser.add_argument("--channel-address", dest="channel_address")
    set_parser.add_argument("--hours", dest="weekly_hours", type=int,
                            help="Stated weekly dial-hours (sizes the batch, §5)")
    set_parser.add_argument("--radius", dest="radius_miles", type=int)
    set_parser.add_argument("--status", choices=["active", "inactive"])
    set_parser.add_argument("--sales-rep-id", dest="sales_rep_id", type=int,
                            help="Main-site roster id (nmc_sales_rep.id)")
    set_parser.add_argument("--partner-code", dest="partner_code",
                            help="The close feed's correlation key (unique)")
    set_parser.add_argument("--addr-line1", dest="addr_line1")
    set_parser.add_argument("--addr-city", dest="addr_city")
    set_parser.add_argument("--addr-state", dest="addr_state")
    set_parser.add_argument("--addr-zip", dest="addr_zip")

    sub.add_parser("list", help="Print the partner roster")
    return parser


def _set(args: argparse.Namespace) -> int:
    provided = {
        column: getattr(args, field)
        for field, column in _FIELD_COLUMNS.items()
        if getattr(args, field) is not None
    }
    columns = ["name", *provided]
    values = [args.name, *provided.values()]
    updates: sql.Composable = sql.SQL(", ").join(
        sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(col))
        for col in provided
    ) if provided else sql.SQL("name = excluded.name")
    query = sql.SQL(
        "insert into partners ({columns}) values ({placeholders}) "
        "on conflict (name) do update set {updates} returning id"
    ).format(
        columns=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        updates=updates,
    )
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
            row = cur.fetchone()
            assert row is not None
            print(f"partner {args.name!r} -> {row[0]}")
    return 0


def _list() -> int:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select name, status, channel, channel_address, weekly_hours, "
                "radius_miles, sales_rep_id, partner_code from partners order by name"
            )
            for row in cur.fetchall():
                print("\t".join("" if v is None else str(v) for v in row))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "set":
        return _set(args)
    return _list()


if __name__ == "__main__":
    sys.exit(main())
