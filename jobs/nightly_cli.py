"""Cron's entry point for the nightly: resolve orphans, read the customer feed when it
is set up, recompute derived state, and run the assignment steps (jobs/nightly.py).

The customer feed is gated on MEDUSA_READONLY_URL (the medusa_nmc_ro credential,
never the owner's MEDUSA_DATABASE_URL); without it the nightly runs without closes.
"""

import argparse

from db.medusa import medusa_readonly_url
from jobs.nightly import run_nightly


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jobs.nightly_cli",
        description="Run the nightly: resolve orphans, read the customer feed when "
        "configured, recompute derived state, run the assignment steps.",
        epilog=(
            "examples:\n"
            "  python -m jobs.nightly_cli\n"
            "  python -m jobs.nightly_cli --dry-run   # show the customer feed, run nothing\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report whether the customer feed is configured, then exit without running",
    )
    args = parser.parse_args(argv)

    configured = medusa_readonly_url() is not None
    print(f"customer feed: {'configured' if configured else 'not configured'}")
    if args.dry_run:
        print("dry-run — nothing ran")
        return 0

    close_feed = None
    if configured:
        from seams.nmc_closes import NmcCloseFeed

        close_feed = NmcCloseFeed.from_env()
    # DNC registry: none handed in — the ledger scrub runs from daily-run.sh.
    run_nightly(dnc_registry=None, close_feed=close_feed)
    print("nightly complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
