"""The Q10 close correlation (partner-lead-assignment.md §11 Q10 / S-10, Phase 4;
transport per nmc-close-feed-contract.md). Matches ALL closes by phone — not only
partner-coded ones — so the spine stops mailing and stops assigning a contact who
already became a customer, however they signed up.

Nightly placement, pinned (revision 6): AFTER `resolve_orphans`, BEFORE
`recompute_state` — PostHog signups are contact-less until orphan resolution, so
the double-count guard would see nothing on exactly the both-inlets night it
exists for if it ran earlier.

Double-count guard (binding, `decisions.md` 2026-07-12 as refined by S-10): the
PostHog feed already emits `signup.completed` for coded-funnel closes, and the
`(source, external_id)` key cannot collapse across sources. The correlation ingests
only when the contact has NO existing `signup.completed` from any source. The
reverse ordering (correlation first, PostHog replay later) legitimately produces
two events — `won` derivation is idempotent, the termination step fires once, and
wave attribution prefers the PostHog event (which alone carries the mailer-code →
piece → wave linkage). Consumers that COUNT signups deduplicate per contact.

Watermark: `feed_watermarks['nmc_closes']` on `recorded_at`, with the contract's
combining rule — effective since = min(stored, now − 45 days) — so late-arriving
phones (checkout collects none; the wizard writes it days later) are re-covered and
previously-orphaned events get their payload phone backfilled when it appears.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Json

from db.session import transaction
from domain.phone import to_e164
from seams.nmc_closes import CloseFeed
from service.ingestion import append_event

FEED_NAME = "nmc_closes"
_TRAILING_DAYS = 45


@dataclass(frozen=True)
class CorrelationReport:
    seen: int = 0
    ingested: int = 0
    skipped_existing: int = 0
    orphaned: int = 0
    phones_backfilled: int = 0


def correlate_closes(feed: CloseFeed, *, now: datetime | None = None) -> CorrelationReport:
    now = now or datetime.now(UTC)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select watermark from feed_watermarks where feed_name = %s",
                (FEED_NAME,),
            )
            row = cur.fetchone()
            stored = row[0] if row else None
            trailing = now - timedelta(days=_TRAILING_DAYS)
            since = min(stored, trailing) if stored else trailing

            seen = ingested = skipped = orphaned = backfilled = 0
            newest = stored
            for close in feed.closes(since):
                seen += 1
                if newest is None or close.recorded_at > newest:
                    newest = close.recorded_at
                phone = to_e164(close.phone_e164) if close.phone_e164 else None

                # phone match: exactly one non-seed row or none (grain merge);
                # never fuzzy — unmatched rests as an orphan for resolve_orphans.
                contact_id = None
                if phone:
                    cur.execute(
                        "select id from contacts where phone_e164 = %s "
                        "and is_seed = false",
                        (phone,),
                    )
                    match = cur.fetchone()
                    contact_id = match[0] if match else None

                external_id = close.id
                cur.execute(
                    "select id, contact_id, payload from events "
                    "where source = 'nmc' and external_id = %s",
                    (external_id,),
                )
                existing = cur.fetchone()
                if existing is not None:
                    # the phone-backfill rule (§2): a previously-ingested orphan
                    # whose phone has since arrived gets its payload updated so
                    # resolve_orphans can finally attribute it.
                    if (existing[1] is None and phone
                            and not (existing[2] or {}).get("phone")):
                        cur.execute(
                            "update events set payload = payload || %s::jsonb "
                            "where id = %s",
                            (Json({"phone": phone}), existing[0]),
                        )
                        backfilled += 1
                    continue

                if contact_id is not None:
                    cur.execute(
                        "select exists(select 1 from events where contact_id = %s "
                        "and type = 'signup.completed')",
                        (contact_id,),
                    )
                    row = cur.fetchone()
                    if row is not None and row[0]:
                        skipped += 1  # the guard: the funnel already told the spine
                        continue

                # mailer-code classification, our half (§2/B1): the seam could only
                # rule out registry codes; a surviving candidate is a mailer code
                # only if WE printed it — otherwise it is page-default noise
                # (SMS_SALES etc.) and stores as null.
                mailer_code = None
                if close.mailer_code:
                    cur.execute(
                        "select 1 from pieces where mailer_code = %s",
                        (close.mailer_code.lower(),),
                    )
                    if cur.fetchone() is not None:
                        mailer_code = close.mailer_code.lower()

                payload = {
                    "kind": close.kind,
                    "phone": phone,
                    "partner_code": close.partner_code,
                    "mailer_code": mailer_code,
                    "sold_by": close.sold_by,
                    "signed_up_via": close.signed_up_via,
                    "subscription_status": close.subscription_status,
                }
                append_event(
                    cur, "nmc", "signup.completed", close.occurred_at,
                    payload, external_id=external_id, contact_id=contact_id,
                )
                ingested += 1
                if contact_id is None:
                    orphaned += 1

            if newest is not None:
                cur.execute(
                    "insert into feed_watermarks (feed_name, watermark) "
                    "values (%s, %s) on conflict (feed_name) "
                    "do update set watermark = excluded.watermark, updated_at = now()",
                    (FEED_NAME, newest),
                )

    if backfilled:
        # B1: a backfilled phone is attributable NOW — re-run orphan resolution in
        # the same nightly rather than waiting for tomorrow's pass (the nightly's
        # own resolve_orphans ran before this job, by the pinned ordering).
        from service.ingestion import resolve_orphans

        resolve_orphans()

    return CorrelationReport(
        seen=seen, ingested=ingested, skipped_existing=skipped,
        orphaned=orphaned, phones_backfilled=backfilled,
    )
