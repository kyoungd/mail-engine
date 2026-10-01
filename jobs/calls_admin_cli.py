"""The operator's door to calls left without an outcome
(docs/contact-engine/05a-call-record.md §4.6, decision 7.9): list them, clear one.
"""

import argparse
import sys
from datetime import UTC, datetime
from uuid import UUID

from db.session import transaction
from domain.errors import ValidationError
from service.calls import clear_call


def _open_calls() -> list[tuple]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select c.id, c.opened_at, c.phone_e164, p.name from calls c "
                "join partners p on p.id = c.rep_id "
                "where c.opened_at is not null and c.outcome is null "
                "and c.cleared_at is null order by c.opened_at"
            )
            return list(cur.fetchall())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List or clear calls that have no outcome.",
        epilog=(
            "examples:\n"
            "  python -m jobs.calls_admin_cli list\n"
            "  python -m jobs.calls_admin_cli clear <call_id> --reason 'app crashed'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="open calls, oldest first")
    p_clear = sub.add_parser("clear", help="close an open call without an outcome")
    p_clear.add_argument("call_id", type=UUID)
    p_clear.add_argument("--reason", required=True)
    p_clear.add_argument("--actor", default="young")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            for call_id, opened_at, phone, rep in _open_calls():
                print(f"{call_id}\t{opened_at.isoformat()}\t{phone}\t{rep}")
        else:
            print(clear_call(args.call_id, args.actor, args.reason, datetime.now(UTC)))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
