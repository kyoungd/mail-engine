"""Cron's entry point for the nightly. FR-11 keeps the nightly job-first — it is
deliberately never a web route — so this is the only way it runs.

Builds the response feeds that are configured, then hands them to run_nightly, which
does the rest in its documented order: facts in, attribution, recompute, digest out.

Two refusals worth knowing about:

  * A feed whose env is absent is SKIPPED and SAID SO. PostHog keys are not collected
    yet, so that is every run today — and a silent skip would read as "we synced
    everything" while web response, currently the only wired response channel, was
    never pulled.

  * Zero configured feeds is a hard failure. run_nightly would otherwise happily
    resolve_orphans -> recompute_state -> digest.run and mail nudges computed over
    nothing new. nightly.py guards against a feed ERROR; nothing guards against feed
    ABSENCE.
"""

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta

from jobs.nightly import run_nightly
from seams.lob_status import LobStatusFeed
from seams.posthog import PostHogFeed

# Overlap is free — ingestion dedupes on (source, external_id) — but a short window
# loses scans permanently if the box was off for a few days. Lob pages every postcard
# regardless, so a generous lookback costs nothing but a filter.
_DEFAULT_LOOKBACK_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC)


def _build_feeds() -> tuple[list, list[str]]:
    """Every configured feed, plus the names of those skipped for missing env."""
    feeds = []
    skipped = []

    lob_key = os.environ.get("LOB_API_KEY")
    if lob_key:
        feeds.append(LobStatusFeed(lob_key))
    else:
        skipped.append("lob (LOB_API_KEY)")

    posthog_key = os.environ.get("POSTHOG_API_KEY")
    posthog_project = os.environ.get("POSTHOG_PROJECT_ID")
    if posthog_key and posthog_project:
        feeds.append(PostHogFeed(posthog_key, posthog_project))
    else:
        skipped.append("posthog (POSTHOG_API_KEY, POSTHOG_PROJECT_ID)")

    return feeds, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jobs.nightly_cli",
        description="Run the nightly: sync every configured feed, resolve orphans, "
        "recompute derived state, send the founder digest.",
        epilog=(
            "examples:\n"
            "  python -m jobs.nightly_cli                      # 30-day lookback\n"
            "  python -m jobs.nightly_cli --since 2026-07-01   # explicit window\n"
            "  python -m jobs.nightly_cli --dry-run            # show feeds, run nothing\n"
            "\n"
            "cron (sources .env, as make run does):\n"
            "  0 3 * * *  cd /path/to/mail-engine && set -a && . ./.env && set +a && \\\n"
            "             uv run python -m jobs.nightly_cli >> nightly.log 2>&1\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--since",
        help=f"pull events at or after this date (YYYY-MM-DD). "
        f"Default: {_DEFAULT_LOOKBACK_DAYS} days ago. Overlap is free — ingestion "
        f"dedupes on (source, external_id).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report which feeds are configured, then exit without running",
    )
    args = parser.parse_args(argv)

    feeds, skipped = _build_feeds()

    for name in skipped:
        print(f"SKIPPED feed: {name} — not configured", file=sys.stderr)

    if not feeds:
        print(
            "error: no feeds configured — refusing to run.\n"
            "A nightly with no feeds still recomputes state and mails a digest, over "
            "data nothing refreshed. Configure at least one feed's env.",
            file=sys.stderr,
        )
        return 1

    since = (
        datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        if args.since
        else _now() - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    )

    print(f"feeds: {', '.join(f.source for f in feeds)} | since: {since.isoformat()}")
    if args.dry_run:
        print("dry-run — nothing ran")
        return 0

    run_nightly(feeds, since)
    print("nightly complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
