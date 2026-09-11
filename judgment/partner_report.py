"""The partner report (partner-report-design.md, APPROVED; R2 as amended; Stage C2).

A nightly decision, not a scheduler: per active partner (house excluded), send when
the heartbeat (7 days) or a trigger (batch assigned / removal since last report)
says so. Three sections, each rendered ONLY from real data — no placeholders, no
effort language, no money language. Never writes `nudge.sent`, never stamps
`next_action_at`; its one write is `partners.last_report_at`, stamped ONLY after a
successful send so a failed send retries next nightly. Follows digest.py's
precedent: pure compose here, the Sender injected at the jobs edge, no `seams`
import in `judgment/`.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from config.params import HOUSE_PARTNER_ID
from db.session import transaction

HEARTBEAT_DAYS = 7
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_LA = ZoneInfo("America/Los_Angeles")  # DISPLAYED dates only — never window math

# Voice-blocking suppression reasons — the "opted out" bucket of the removal line
# (S-6's reclaim reasons; other reclaims render as "reclaimed"). A registry listing
# is not an opt-out: it gets its own bucket and is named, not counted (2026-09-10).
_OPT_OUT_REASONS = ("do_not_call", "opt_out")
_REGISTRY_REASON = "dnc_registry"


def _day(dt: datetime) -> str:
    return dt.astimezone(_LA).strftime("%Y-%m-%d")


def _phone(e164: str) -> str:
    national = e164.removeprefix("+1")
    return f"({national[:3]}) {national[3:6]}-{national[6:]}"


def _removals(cur, partner_id: UUID, since: datetime) -> dict[str, int]:
    cur.execute(
        "select type, payload->>'reason', count(*) from events "
        "where type in ('contact.assignment_expired', 'contact.reclaimed') "
        "and payload->>'previous_owner_id' = %s and occurred_at > %s "
        "group by 1, 2",
        (str(partner_id), since),
    )
    counts = {"opted_out": 0, "reclaimed": 0, "expired": 0, "registry": 0}
    for etype, reason, n in cur.fetchall():
        if etype == "contact.assignment_expired":
            counts["expired"] += n
        elif reason == _REGISTRY_REASON:
            counts["registry"] += n
        elif reason in _OPT_OUT_REASONS:
            counts["opted_out"] += n
        else:
            counts["reclaimed"] += n
    return counts


def _registry_removals(
    cur, partner_id: UUID, since: datetime
) -> tuple[list[tuple[str, str]], datetime]:
    """The exclusion list: each number the scrub took back from this partner
    because it is on the national registry — (company, phone) — and when the
    latest one left, since every sheet exported before then still carries it."""
    cur.execute(
        "select coalesce(c.business_name, c.contact_name, 'Business Owner'), "
        "c.phone_e164, e.occurred_at "
        "from events e join contacts c on c.id = e.contact_id "
        "where e.type = 'contact.reclaimed' and e.payload->>'reason' = %s "
        "and e.payload->>'previous_owner_id' = %s and e.occurred_at > %s "
        "order by 1, 2",
        (_REGISTRY_REASON, str(partner_id), since),
    )
    rows = cur.fetchall()
    return [(name, phone) for name, phone, _ in rows], max(r[2] for r in rows)


def _should_send(cur, partner_id: UUID, last_report_at: datetime | None,
                 now: datetime) -> bool:
    if last_report_at is None or last_report_at <= now - timedelta(days=HEARTBEAT_DAYS):
        return True  # heartbeat
    cur.execute(
        "select exists(select 1 from assignment_batches "
        "where partner_id = %s and created_at > %s)",
        (partner_id, last_report_at),
    )
    row = cur.fetchone()
    if row is not None and row[0]:
        return True  # a batch was assigned
    removals = _removals(cur, partner_id, last_report_at)
    return any(removals.values())  # a removal — the re-pull case


def _holdings_section(cur, partner_id: UUID, since: datetime,
                      last_export_at: datetime | None, now: datetime) -> str | None:
    cur.execute(
        "select delivered_count, created_at, expires_at from assignment_batches "
        "where partner_id = %s and expires_at > %s order by created_at",
        (partner_id, now),
    )
    batches = cur.fetchall()
    cur.execute(
        "select count(*) from contacts where owner_id = %s "
        "and assignment_batch_id is not null",
        (partner_id,),
    )
    row = cur.fetchone()
    holding = row[0] if row else 0
    removals = _removals(cur, partner_id, since)

    if not batches and not any(removals.values()):
        return None  # nothing to say — the empty partner gets no email (R2 1b)

    lines = ["Your list"]
    if batches:
        earliest = min(b[2] for b in batches)
        lines.append(f"{max((earliest - now).days, 0)} days left on your earliest batch")
        for delivered, created_at, expires_at in batches:
            noun = "contact" if delivered == 1 else "contacts"
            lines.append(
                f"- assigned {delivered} {noun} on {_day(created_at)}, "
                f"expires {_day(expires_at)}"
            )
    lines.append(f"Contacts currently yours: {holding}")
    if removals["opted_out"] or removals["reclaimed"] or removals["expired"]:
        lines.append(
            f"Removed since your last report: {removals['opted_out']} opted out, "
            f"{removals['reclaimed']} reclaimed, {removals['expired']} expired"
        )
    if removals["registry"]:
        listed, latest = _registry_removals(cur, partner_id, since)
        lines.append(
            "Now on the national Do Not Call registry — removed from your list, "
            "do not call:"
        )
        lines.extend(f"- {name}, {_phone(phone)}" for name, phone in listed)
        lines.append(
            f"These numbers are still on any sheet you exported before {_day(latest)}."
        )
    if last_export_at is not None:
        age = max((now - last_export_at).days, 0)
        lines.append(
            f"Your last export was generated {_day(last_export_at)} ({age} days ago)"
        )
    if any(removals.values()):
        lines.append("Re-pull your sheet before your next calling session.")
    return "\n".join(lines)


def _closes_section(cur, partner_code: str | None, sales_rep_id: int | None,
                    since: datetime) -> str | None:
    if partner_code is None and sales_rep_id is None:
        return None
    where = (
        "type = 'signup.completed' and "
        "((%s::text is not null and payload->>'partner_code' = %s) "
        " or (%s::bigint is not null and (payload->>'sold_by')::bigint = %s))"
    )
    params = (partner_code, partner_code, sales_rep_id, sales_rep_id)
    cur.execute(
        f"select e.occurred_at, c.business_name, e.contact_id from events e "  # noqa: S608
        f"left join contacts c on c.id = e.contact_id where {where} "
        f"order by e.occurred_at",
        params,
    )
    rows = cur.fetchall()
    if not rows:
        return None  # no line appears unless its data is real

    recent = [r for r in rows if r[0] > since]
    lines = [f"Closes credited since your last report: {len(recent)}"]
    for occurred_at, business_name, contact_id in recent:
        if contact_id is None or not business_name:
            # orphaned-but-credited (design 2026-07-31): counted immediately,
            # named when correlation lands — never dropped, never guessed.
            lines.append(f"- new close — details pending ({_day(occurred_at)})")
        else:
            lines.append(f"- {business_name} ({_day(occurred_at)})")
    lines.append(f"Total closes to date: {len(rows)}")
    return "\n".join(lines)


def _demos_section(demos, sales_rep_id: int | None, since: datetime,
                   now: datetime) -> str | None:
    if demos is None or sales_rep_id is None:
        return None
    try:
        partners = demos.summary(since, now)
    except Exception:
        return None  # unreachable feed → the section is omitted, no placeholder
    mine = [p for p in partners if p.get("salesRepId") == str(sales_rep_id)]
    if not mine:
        return None
    calls = sum(int(p["calls"]) for p in mine)
    prospects = sum(int(p["uniqueProspects"]) for p in mine)
    blocked = sum(int(p["blockedCalls"]) for p in mine)
    texts = sum(int(p["textsForwarded"]) for p in mine)
    if calls == 0 and texts == 0:
        return None
    return (
        f"On your demo line since your last report: {calls} calls "
        f"({prospects} unique prospects, {blocked} from blocked numbers), "
        f"{texts} texts forwarded to you"
    )


def compose(cur, partner_row: tuple, now: datetime, demos=None) -> str | None:
    """The full report for one partner, or None when no section has real data.
    First line = the email subject (the Sender's convention)."""
    (partner_id, name, partner_code, sales_rep_id, last_report_at,
     last_export_at) = partner_row
    since = last_report_at or _EPOCH

    sections = [
        _holdings_section(cur, partner_id, since, last_export_at, now),
        _closes_section(cur, partner_code, sales_rep_id, since),
        _demos_section(demos, sales_rep_id, since, now),
    ]
    real = [s for s in sections if s]
    if not real:
        return None
    header = f"Your NeverMissCall partner report — {_day(now)}"
    return "\n\n".join([header, *real])


def run_partner_reports(*, sender, now: datetime | None = None, demos=None) -> int:
    """The nightly report step — runs LAST, after the expiry job (binding: a report
    composed before expiry tells a partner they hold contacts already gone). One
    partner's failure never blocks another's send; failures re-raise at the end so
    the nightly exits loud. Returns the number of reports sent."""
    if sender is None:
        return 0  # dark — same posture as every unconfigured seam
    now = now or datetime.now(UTC)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, name, partner_code, sales_rep_id, last_report_at, "
                "last_export_at from partners "
                "where status = 'active' and id <> %s order by name",
                (HOUSE_PARTNER_ID,),
            )
            partners = cur.fetchall()

    sent = 0
    failures: list[str] = []
    for row in partners:
        partner_id, name, _code, _rep, last_report_at, _exp = row
        with transaction() as conn:
            with conn.cursor() as cur:
                if not _should_send(cur, partner_id, last_report_at, now):
                    continue
                body = compose(cur, row, now, demos=demos)
        if body is None:
            continue  # nothing sent → nothing stamped; the heartbeat stays due
        try:
            sender.send(str(partner_id), body)
        except Exception as exc:  # noqa: BLE001 — isolate, report, continue
            failures.append(f"{name} ({partner_id}): {exc}")
            continue
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update partners set last_report_at = %s where id = %s",
                    (now, partner_id),
                )
        sent += 1

    if failures:
        raise RuntimeError(
            "partner report send failures (watermarks left for retry): "
            + "; ".join(failures)
        )
    return sent
