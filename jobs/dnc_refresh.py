"""The DNC scrub (partner-lead-assignment.md §6/S-9, Phase 2). Runs DAILY —
cron/CLI, never a route — and is a cheap no-op when nothing has crossed the
21-day threshold, which is what makes "a couple of missed runs cost nothing"
true. The subscription — not the assignment — bounds the scrub: every contact
in a subscribed area code is covered, assigned contacts first, because the
§310.4(b)(3) safe harbor demands calling against a registry version no more
than 31 days old and the assignable pool must stay warm.

Idempotency is the events table's `unique (source, external_id)`:
`dnc:<contact_id>:<registry_version>` — the same version twice appends nothing.
A hit sets `dnc_registry` on the row (the row IS the phone since the grain
merge) and ends any live assignment via `set_owner`. A previously-hit number
ABSENT from the current version clears through `clear_suppression`, keyed
contact + version like the check event (S-9's delisting writer).

TWO ENTRY POINTS (Architecture B, Phase 4):

  `dnc_refresh(registry)` is the single-registry primitive — one snapshot for
  every subscribed code. Unchanged, and pinned by the frozen S-9 suite: it is
  what `--fake`, `--snapshot DIR`, dnc-daily.sh and the rehearsal still use, and
  it keeps the version-keyed external_id.

  `dnc_refresh_all()` is the hybrid path. NMC's own SAN and any partner SANs
  cover an overlapping set of codes, so each code resolves to its own recorded
  snapshot and the external_id is keyed on the SNAPSHOT — `dnc:<id>:snap:<uuid>`.
  A date-keyed id could not tell two holders' same-day files apart, and since
  append_event is ON CONFLICT DO NOTHING the second holder's check would vanish
  silently while its verdict still landed. Separate namespaces, no collision
  either way.
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from config.params import DNC_RECHECK_DAYS, HOUSE_PARTNER_ID
from db.session import transaction
from seams.dnc_registry import DncRegistry, DncRegistryError, FileDncRegistry
from service.contacts import clear_suppression
from service.custody import set_owner
from service.ingestion import append_event

LISTS_ROOT = Path(__file__).resolve().parents[2] / "dnc-lists"


@dataclass(frozen=True)
class DncReport:
    checked: int = 0
    hits: int = 0
    cleared: int = 0
    skips: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Coverage:
    """One area code and the recorded snapshot that will judge it."""

    area_code: str
    snapshot_id: UUID
    san_holder_id: UUID
    version: str
    directory: Path


def _national(phone_e164: str) -> str:
    """+18185550123 -> 8185550123 (the registry lists 10-digit national numbers)."""
    return phone_e164.removeprefix("+1")


def _subscribed_codes(cur) -> list[str]:
    """DISTINCT: since the holder joined the primary key, one code can carry a row
    per SAN holder — NMC's and a partner's — and a naive read would scrub it twice."""
    cur.execute("select distinct area_code from dnc_subscriptions")
    return [row[0] for row in cur.fetchall()]


def _due(subscribed: list[str], limit: int | None) -> list[tuple]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, phone_e164, owner_id, dnc_registry, "
                "substring(phone_e164 from 3 for 3) as area_code "
                "from contacts "
                "where phone_e164 is not null and is_seed = false "
                "and substring(phone_e164 from 3 for 3) = any(%s) "
                "and (dnc_checked_at is null or dnc_checked_at < now() - "
                "make_interval(days => %s)) "
                "order by (owner_id = %s), id "  # assigned (non-house) first
                + ("limit %s" if limit is not None else ""),
                (subscribed, DNC_RECHECK_DAYS, HOUSE_PARTNER_ID)
                + ((limit,) if limit is not None else ()),
            )
            return cur.fetchall()


def _group(due: list[tuple]) -> dict[str, list[tuple]]:
    by_code: dict[str, list[tuple]] = {}
    for row in due:
        by_code.setdefault(row[4], []).append(row)
    return by_code


def _apply(
    rows: list[tuple],
    on_registry: frozenset[str],
    *,
    version: str,
    snapshot_id: UUID | None,
    san_holder_id: UUID | None,
) -> tuple[int, int, int]:
    """Scrub one area code's due contacts against an already-resolved hit set. Each
    contact commits in its own transaction, so one bad row cannot roll back the rows
    already stamped."""
    payload_extra = (
        {"snapshot_id": str(snapshot_id), "san_holder": str(san_holder_id)}
        if snapshot_id is not None
        else {}
    )
    key = f"snap:{snapshot_id}" if snapshot_id is not None else version
    checked = hits = cleared = 0

    for contact_id, phone, owner_id, already_listed, _ in rows:
        hit = _national(phone) in on_registry
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update contacts set dnc_checked_at = now(), dnc_registry = %s, "
                    "dnc_snapshot_id = coalesce(%s, dnc_snapshot_id) where id = %s",
                    (hit, snapshot_id, contact_id),
                )
                append_event(
                    cur, "system", "contact.dnc_checked", datetime.now(UTC),
                    {"registry_version": version, "hit": hit, **payload_extra},
                    external_id=f"dnc:{contact_id}:{key}",
                    contact_id=contact_id,
                )
                if hit and owner_id != HOUSE_PARTNER_ID:
                    # S-9: a listed number leaves its assignment immediately.
                    set_owner(
                        cur, contact_id, HOUSE_PARTNER_ID,
                        event_type="contact.reclaimed",
                        reason="dnc_registry", actor="system",
                    )
        checked += 1
        if hit:
            hits += 1
        elif already_listed:
            # The delisting writer (S-9): absent from the current version clears
            # the flag with its event — outside the row transaction above because
            # clear_suppression owns its own (the flag update there is idempotent
            # with the one we just wrote).
            clear_suppression(
                contact_id, "dnc_registry",
                reason=f"absent from registry {version}",
                source="system",
                external_id=f"dnc-clear:{contact_id}:{key}",
            )
            cleared += 1
    return checked, hits, cleared


def dnc_refresh(registry: DncRegistry, *, limit: int | None = None) -> DncReport:
    """One scrub pass against ONE registry: re-check contacts in subscribed area
    codes whose `dnc_checked_at` is older than the 21-day threshold (or never set),
    assigned contacts first."""
    version = registry.version()

    with transaction() as conn:
        with conn.cursor() as cur:
            subscribed = _subscribed_codes(cur)
            if not subscribed:
                return DncReport()

    due = _due(subscribed, limit)
    by_code = _group(due)

    # One listed() call per area code over OUR due numbers — the registry file
    # streams past our set, never the reverse (decisions.md 2026-08-03). Resolved
    # for EVERY code before any contact is stamped: a DncRegistryError here aborts
    # the whole pass rather than leaving half the codes scrubbed.
    on_registry = {
        code: registry.listed(code, frozenset(_national(r[1]) for r in rows))
        for code, rows in by_code.items()
    }

    checked = hits = cleared = 0
    for code, rows in by_code.items():
        c, h, cl = _apply(rows, on_registry[code], version=version,
                          snapshot_id=None, san_holder_id=None)
        checked, hits, cleared = checked + c, hits + h, cleared + cl
    return DncReport(checked=checked, hits=hits, cleared=cleared)


def _coverage(codes: list[str], lists_root: Path) -> dict[str, Coverage]:
    """The newest ACCEPTED snapshot per code, from any holder. Ties on version_date
    break toward the most recently recorded."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select distinct on (area_code) area_code, id, san_holder_id, "
                "version_date from dnc_snapshots "
                "where status = 'accepted' and area_code = any(%s) "
                "order by area_code, version_date desc, recorded_at desc",
                (codes,),
            )
            rows = cur.fetchall()
    return {
        area_code: Coverage(
            area_code=area_code,
            snapshot_id=snapshot_id,
            san_holder_id=holder,
            version=version_date.isoformat(),
            directory=lists_root / str(holder) / version_date.isoformat(),
        )
        for area_code, snapshot_id, holder, version_date in rows
    }


def _bump(snapshot_id: UUID, checked: int) -> None:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update dnc_snapshots set checks_written = checks_written + %s "
                "where id = %s",
                (checked, snapshot_id),
            )


def dnc_refresh_all(*, lists_root: Path = LISTS_ROOT, limit: int | None = None) -> DncReport:
    """The hybrid pass: every subscribed code against ITS OWN recorded snapshot.

    A code with no accepted snapshot, or whose working copy is gone, is SKIPPED —
    its contacts stay stale and therefore unassignable. Nobody jumps the scrub, and
    nothing is ever scrubbed against a file we cannot read. Per-code isolation is
    deliberate here: one partner's bad file must not stop every other code."""
    with transaction() as conn:
        with conn.cursor() as cur:
            subscribed = _subscribed_codes(cur)
            if not subscribed:
                return DncReport()

    coverage = _coverage(subscribed, lists_root)
    by_code = _group(_due(subscribed, limit))

    checked = hits = cleared = 0
    skips: list[tuple[str, str]] = []
    for code in subscribed:
        cover = coverage.get(code)
        if cover is None:
            skips.append((code, "no_snapshot"))
            continue
        rows = by_code.get(code, [])
        if not rows:
            continue
        try:
            on_registry = FileDncRegistry(cover.directory).listed(
                code, frozenset(_national(r[1]) for r in rows)
            )
        except DncRegistryError:
            skips.append((code, "working_copy_missing"))
            continue

        c, h, cl = _apply(rows, on_registry, version=cover.version,
                          snapshot_id=cover.snapshot_id,
                          san_holder_id=cover.san_holder_id)
        _bump(cover.snapshot_id, c)
        checked, hits, cleared = checked + c, hits + h, cleared + cl

    return DncReport(checked=checked, hits=hits, cleared=cleared, skips=skips)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dnc_refresh",
        description="Re-scrub contacts in subscribed area codes against the DNC "
        "registry (partner-lead-assignment.md §6/S-9). Runs daily; no-op when "
        "nothing has crossed the 21-day threshold.",
        epilog=(
            "Real runs read a downloaded snapshot directory (see\n"
            "scripts/dnc-download.py; layout marketing/dnc-lists/<YYYY-MM-DD>/ —\n"
            "the directory name is the registry version stamped on check events).\n\n"
            "Examples:\n"
            "  uv run python -m jobs.dnc_refresh --from-ledger   # recorded snapshots\n"
            "  uv run python -m jobs.dnc_refresh --snapshot ../dnc-lists/2026-08-05\n"
            "  uv run python -m jobs.dnc_refresh --fake v1              # empty fake registry\n"
            "  uv run python -m jobs.dnc_refresh --fake v1 --listed 8185550123\n"
            "  uv run python -m jobs.dnc_refresh --fake v1 --limit 100\n\n"
            "Requires OWNER_DATABASE_URL — make targets source .env; this module does not."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--snapshot", metavar="DIR", default=None,
        help="use the real FileDncRegistry over a downloaded snapshot directory",
    )
    parser.add_argument(
        "--fake", metavar="VERSION", default=None,
        help="use FakeDncRegistry with this version string (no SAN, no network)",
    )
    parser.add_argument(
        "--listed", action="append", default=[], metavar="NATIONAL10",
        help="with --fake: a 10-digit national number the fake registry lists "
        "(repeatable)",
    )
    parser.add_argument(
        "--from-ledger", action="store_true",
        help="scrub each subscribed code against ITS OWN newest accepted recorded "
        "snapshot (the hybrid path; NMC + partner SANs)",
    )
    parser.add_argument(
        "--lists-root", metavar="DIR", default=None,
        help=f"with --from-ledger: where working copies live (default {LISTS_ROOT})",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="check at most N contacts this run (next N stale, assigned first)",
    )
    args = parser.parse_args(argv)

    if args.from_ledger:
        if args.snapshot is not None or args.fake is not None:
            print(
                "dnc_refresh: --from-ledger resolves its own snapshots; it cannot be "
                "combined with --snapshot or --fake.",
                file=sys.stderr,
            )
            return 2
        ledger_report = dnc_refresh_all(
            lists_root=Path(args.lists_root) if args.lists_root else LISTS_ROOT,
            limit=args.limit,
        )
        print(
            f"checked={ledger_report.checked} hits={ledger_report.hits} "
            f"cleared={ledger_report.cleared}"
        )
        for area_code, reason in ledger_report.skips:
            print(f"  SKIP  {area_code}: {reason}")
        return 0

    if (args.snapshot is None) == (args.fake is None):
        print(
            "dnc_refresh: exactly one of --snapshot DIR (real registry files), "
            "--fake VERSION (dev), or --from-ledger is required.",
            file=sys.stderr,
        )
        return 2

    registry: DncRegistry
    if args.snapshot is not None:
        registry = FileDncRegistry(Path(args.snapshot))
    else:
        from seams.fakes import FakeDncRegistry

        by_code: dict[str, set[str]] = {}
        for number in args.listed:
            by_code.setdefault(number[:3], set()).add(number)
        registry = FakeDncRegistry(version=args.fake, numbers=by_code)

    report = dnc_refresh(registry, limit=args.limit)
    print(
        f"checked={report.checked} hits={report.hits} cleared={report.cleared}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
