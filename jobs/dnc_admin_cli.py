"""The operator's door to "don't call me again" (docs/contact-engine/02-dnc-filtering.md
§4.6, §4.7): record a request, read a phone's history, lift a block.
"""

import argparse
import sys
from datetime import UTC, datetime

from domain.errors import ValidationError
from service.dnc import dnc_history, lift_do_not_call, record_do_not_call_request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record, read, or lift a do-not-call block on a phone.",
        epilog=(
            "examples:\n"
            "  python -m jobs.dnc_admin_cli block 818-555-0123 --reason 'asked by email'\n"
            "  python -m jobs.dnc_admin_cli history 818-555-0123\n"
            "  python -m jobs.dnc_admin_cli lift 818-555-0123 --seen 42 --reason 'entered in error'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_block = sub.add_parser("block", help="record a do-not-call request")
    p_block.add_argument("phone")
    p_block.add_argument("--reason", required=True)
    p_block.add_argument("--actor", default="young")

    p_history = sub.add_parser("history", help="print a phone's blocks and lifts")
    p_history.add_argument("phone")

    p_lift = sub.add_parser("lift", help="lift a block recorded by a rep or an admin")
    p_lift.add_argument("phone")
    p_lift.add_argument("--seen", type=int, required=True,
                        help="the latest seq read from history")
    p_lift.add_argument("--reason", required=True)
    p_lift.add_argument("--actor", default="young")

    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.cmd == "block":
            print(record_do_not_call_request(args.phone, args.actor, args.reason, now))
        elif args.cmd == "history":
            for e in dnc_history(args.phone):
                print(f"{e.seq}\t{e.at.isoformat()}\t{e.kind}\t{e.actor}\t{e.reason or ''}")
        else:
            print(lift_do_not_call(args.phone, args.seen, args.actor, args.reason, now))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
