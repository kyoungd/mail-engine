"""Load a canonical intake CSV into the contacts spine (the door the upload page was).

The file is the form the converters in intake/ write. What loading does — dedupe,
E.164, resolution onto contacts — is service.contacts.load_list's; this prints the
four counts it returns.
"""

import argparse
import sys

from domain.errors import ValidationError
from service.contacts import load_list


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Load a canonical intake CSV (the output of an intake/ converter).",
        epilog=(
            "examples:\n"
            "  python -m jobs.intake_cli la-plumbers.csv --source cslb-ca\n"
            "  python -m jobs.intake_cli fbn-2026.csv --source fbn-ca-2026\n"
            "prints: loaded=N deduped=N invalid=N suppressed=N"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv_path", help="canonical intake CSV")
    parser.add_argument(
        "--source", required=True, help="the list's source, e.g. cslb-ca or fbn-ca-2026"
    )
    args = parser.parse_args(argv)

    try:
        report = load_list(args.csv_path, source=args.source)
    except ValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"loaded={report.loaded} deduped={report.deduped} "
        f"invalid={report.invalid} suppressed={report.suppressed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
