"""The operator's door to a contact's time zone (docs/contact-engine/03-time-zone.md
§4.4, §4.5): show its zones and calling hours now, or set its zone as an admin.
"""

import argparse
import sys
from datetime import UTC, datetime
from uuid import UUID

from domain.errors import ValidationError
from service.zones import calling_hours, set_zone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show or set a contact's time zone.",
        epilog=(
            "examples:\n"
            "  python -m jobs.zone_admin_cli show 3f2b…\n"
            "  python -m jobs.zone_admin_cli set 3f2b… America/Los_Angeles"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show", help="the contact's zones, who set them, and now there")
    p_show.add_argument("contact_id", type=UUID)

    p_set = sub.add_parser("set", help="set the contact's zone as an admin")
    p_set.add_argument("contact_id", type=UUID)
    p_set.add_argument("zone")
    p_set.add_argument("--actor", default="young")

    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.cmd == "show":
            hours = calling_hours(args.contact_id, now)
            if hours.set_by is None:
                print("set by: nobody (from the phone and the state)")
            else:
                print(f"set by: {hours.set_by.actor} at {hours.set_by.at.isoformat()}")
            for zone, local in sorted(hours.local.items()):
                print(f"{zone}\t{local.strftime('%Y-%m-%d %H:%M')}")
            print(f"inside calling hours: {hours.inside}")
        else:
            print(set_zone(args.contact_id, args.zone, now, actor=args.actor))
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
