"""Upsert the founder seed addresses (PRD FR-4) from config/seeds.json.

Seeds are config, not a management UI: a small gitignored JSON file of founder
addresses that this CLI loads and upserts as is_seed contacts. Idempotent — safe to
run on every deploy or from cron. Each seed rides every wave as one extra piece (the
physical print-quality check) and is excluded from all response metrics.

config/seeds.json is a list of objects:
  [{"name": "Young HQ", "line1": "...", "line2": "", "city": "...",
    "state": "CA", "zip": "90012"}]
See config/seeds.example.json.
"""

import argparse
import json
import sys
from pathlib import Path

from service.contacts import ensure_seed_contacts

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "seeds.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upsert founder seed addresses (is_seed contacts) from a JSON file.",
        epilog=(
            "examples:\n"
            "  python -m jobs.seed_cli                 # load config/seeds.json\n"
            "  python -m jobs.seed_cli -f other.json   # load a different file\n"
            "  make seed-contacts                      # the wrapped, env-sourced form\n\n"
            "The file is a JSON list of {name, line1, line2?, city, state, zip}. "
            "Idempotent: re-running never duplicates a seed (keyed on name)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        default=_DEFAULT_PATH,
        help=f"seed JSON file (default: {_DEFAULT_PATH})",
    )
    args = parser.parse_args(argv)

    if not args.file.exists():
        print(
            f"error: {args.file} not found — copy config/seeds.example.json to "
            f"config/seeds.json and fill in the founder addresses",
            file=sys.stderr,
        )
        return 1

    seeds = json.loads(args.file.read_text())
    if not isinstance(seeds, list) or not seeds:
        print(f"error: {args.file} must be a non-empty JSON list of addresses", file=sys.stderr)
        return 1

    report = ensure_seed_contacts(seeds)
    print(f"seeds: {report.total} total, {report.created} created this run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
