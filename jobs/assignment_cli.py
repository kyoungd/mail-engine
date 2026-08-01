"""Operator CLI for the assignment verbs (partner-lead-assignment.md §7, Phase 4).

The verbs ship CLI-first with no web routes at v1 (Phase 0's FR-11 exemption). This
is also the cutover tool: the day S-1 goes live, Young issues John's first real
batch with the explicit id-list form pinning the surviving sheet rows — one manual
act, no migration code.
"""

import argparse
import json
import sys
from uuid import UUID

from db.session import transaction
from service.assignment import assign_batch, export_batch, reclaim


def _partner_id(name_or_id: str) -> UUID:
    try:
        return UUID(name_or_id)
    except ValueError:
        pass
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("select id from partners where name = %s", (name_or_id,))
            row = cur.fetchone()
            if row is None:
                print(f"no partner named {name_or_id!r}", file=sys.stderr)
                raise SystemExit(2)
            return row[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="assignment_cli",
        description="Assign, export, and reclaim partner lead batches "
        "(partner-lead-assignment.md §7). Custody moves only through set_owner; "
        "this is the operator's front door to it.",
        epilog=(
            "Examples:\n"
            "  # derived batch from the partner's weekly hours, SFV plumbers\n"
            '  uv run python -m jobs.assignment_cli assign John --key john-b1 \\\n'
            '      --rule \'{"trade": ["plumber"], "zip_prefix": ["913","914","916"]}\'\n'
            "  # the Step 11 trial batch (explicit count bypasses the floor)\n"
            "  uv run python -m jobs.assignment_cli assign John --key john-trial "
            "--rule '{}' --count 25\n"
            "  # the cutover form: exact ids from the surviving sheet rows\n"
            "  uv run python -m jobs.assignment_cli assign John --key john-cutover "
            "--ids-file sheet-ids.txt\n"
            "  # the partner's working file (fresh every pull — the re-pull rule)\n"
            "  uv run python -m jobs.assignment_cli export John -o john-leads.csv\n"
            "  # end of the road\n"
            "  uv run python -m jobs.assignment_cli reclaim John --reason 'partnership ended'\n\n"
            "A same --key retry returns the original batch (a receipt, not a re-run);\n"
            "a reused key with different parameters is rejected.\n"
            "Requires OWNER_DATABASE_URL — make targets source .env; this module does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_assign = sub.add_parser("assign", help="assign a batch to a partner")
    p_assign.add_argument("partner", help="partner name or id")
    p_assign.add_argument("--key", required=True, help="idempotency key (retry-safe)")
    p_assign.add_argument("--actor", default="young")
    p_assign.add_argument("--rule", help="audience rule as JSON (wave-grammar keys)")
    p_assign.add_argument("--count", type=int, help="explicit count (founder override)")
    p_assign.add_argument(
        "--ids-file", help="file of contact uuids, one per line (the cutover form)"
    )

    p_export = sub.add_parser("export", help="regenerate a partner's working CSV")
    p_export.add_argument("partner")
    p_export.add_argument("-o", "--out", help="write CSV here (default stdout)")

    p_reclaim = sub.add_parser("reclaim", help="return all of a partner's holdings")
    p_reclaim.add_argument("partner")
    p_reclaim.add_argument("--reason", required=True)
    p_reclaim.add_argument("--actor", default="young")

    args = parser.parse_args(argv)
    partner = _partner_id(args.partner)

    if args.command == "assign":
        contact_ids = None
        if args.ids_file:
            with open(args.ids_file) as handle:
                contact_ids = [UUID(line.strip()) for line in handle if line.strip()]
        rule = json.loads(args.rule) if args.rule else None
        report = assign_batch(
            partner, args.key, args.actor,
            audience_rule=rule, count=args.count, contact_ids=contact_ids,
        )
        tag = "RETRY (receipt)" if report.retry else "assigned"
        print(f"batch {report.batch_id}: {len(report.assigned)} {tag}")
        for cause, ids in sorted(report.shortfall.items()):
            print(f"  shortfall {cause}: {len(ids)}")
        if report.released:
            print(f"  released since assignment: {len(report.released)}")
        return 0

    if args.command == "export":
        result = export_batch(partner)
        if args.out:
            with open(args.out, "w") as handle:
                handle.write(result.csv)
            print(f"wrote {args.out}", file=sys.stderr)
        else:
            print(result.csv, end="")
        for cause, ids in sorted(result.shortfall.items()):
            print(f"shortfall {cause}: {len(ids)}", file=sys.stderr)
        return 0

    returned = reclaim(partner, args.reason, args.actor)
    print(f"reclaimed {returned} contact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
