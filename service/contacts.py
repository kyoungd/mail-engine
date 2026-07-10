"""List and contact verbs (service contract §2).

`load_list` is the one-time bulk intake (parse, dedupe, E.164, segment). NCOA/CASS
address validation is deliberately NOT here: it needs the print seam, which the
dependency rule bars from the service layer — it lands as a Phase 3 job that stamps
`addr_validated_at`. `suppress` is one-way (no unsuppress verb exists); `record_outcome`
declares a conversation lost; `set_next_action` is the founder's override of the
judgment slot.
"""

import csv
from datetime import UTC, date, datetime
from uuid import UUID

from db.session import transaction
from domain.errors import ValidationError
from domain.phone import to_e164
from domain.types import IntakeReport
from service.ingestion import ingest_event

_TRUTHY = {"1", "true", "t", "yes", "y"}


def _clean(row: dict, key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


def _segment(trade: str, state: str | None) -> str:
    """Deterministic default segment: trade, narrowed by geography when present.
    A placeholder the operator refines; segments are free text by design."""
    return f"{trade.lower()}-{state.upper()}" if state else trade.lower()


def load_list(csv_path: str, source: str = "cslb") -> IntakeReport:
    """Bulk intake. Dedupes on cslb_license (against the DB and within the file),
    normalizes phones to E.164, assigns a segment. Rows without a trade are invalid
    and skipped. do_not_mail rows load suppressed. Returns the counts."""
    loaded = deduped = invalid = suppressed = 0
    seen: set[str] = set()

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select cslb_license from contacts where cslb_license is not null"
            )
            existing = {r[0] for r in cur.fetchall()}

            with open(csv_path, newline="") as handle:
                for row in csv.DictReader(handle):
                    trade = (row.get("trade") or "").strip()
                    if not trade:
                        invalid += 1
                        continue

                    license_no = _clean(row, "cslb_license")
                    if license_no and (license_no in existing or license_no in seen):
                        deduped += 1
                        continue
                    if license_no:
                        seen.add(license_no)

                    do_not_mail = (row.get("do_not_mail") or "").strip().lower() in _TRUTHY
                    segment = _clean(row, "segment") or _segment(
                        trade, _clean(row, "addr_state")
                    )

                    cur.execute(
                        "insert into contacts "
                        "(cslb_license, business_name, contact_name, trade, license_class, "
                        "phone_e164, email, addr_line1, addr_line2, addr_city, addr_state, "
                        "addr_zip, segment, source, do_not_mail) "
                        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            license_no,
                            _clean(row, "business_name"),
                            _clean(row, "contact_name"),
                            trade,
                            _clean(row, "license_class"),
                            to_e164(row.get("phone")),
                            _clean(row, "email"),
                            _clean(row, "addr_line1"),
                            _clean(row, "addr_line2"),
                            _clean(row, "addr_city"),
                            _clean(row, "addr_state"),
                            _clean(row, "addr_zip"),
                            segment,
                            source,
                            do_not_mail,
                        ),
                    )
                    loaded += 1
                    if do_not_mail:
                        suppressed += 1

    return IntakeReport(
        loaded=loaded, deduped=deduped, invalid=invalid, suppressed=suppressed
    )


def suppress(contact_id: UUID, reason: str) -> None:
    """Set the human-authored flag AND append contact.opt_out. Irreversible by design:
    there is no unsuppress verb, and recomputation preserves the flag."""
    if reason not in ("do_not_mail", "opt_out"):
        raise ValidationError(
            "bad_reason", f"reason must be do_not_mail or opt_out, got {reason!r}"
        )
    ingest_event(
        source="human",
        type="contact.opt_out",
        occurred_at=datetime.now(UTC),
        payload={"reason": reason},
        contact_id=contact_id,
    )
    with transaction() as conn:
        with conn.cursor() as cur:
            if reason == "do_not_mail":
                cur.execute(
                    "update contacts set do_not_mail = true where id = %s", (contact_id,)
                )
            else:
                cur.execute(
                    "update contacts set do_not_text = true where id = %s", (contact_id,)
                )


def record_outcome(contact_id: UUID, outcome: str, reason: str) -> int:
    """Human judgment that a conversation is over. 'won' is never declared manually —
    it derives from signup.completed."""
    if outcome != "lost":
        raise ValidationError(
            "bad_outcome",
            "record_outcome only declares 'lost'; 'won' derives from signup.completed",
        )
    return ingest_event(
        source="human",
        type="contact.lost",
        occurred_at=datetime.now(UTC),
        payload={"reason": reason},
        contact_id=contact_id,
    )


def set_next_action(contact_id: UUID, action_date: date, note: str) -> None:
    """Founder override of the judgment job's slot. The nightly job won't overwrite a
    human-set action until it passes (enforced by the job, Phase 4)."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update contacts set next_action_at = %s, next_action_note = %s "
                "where id = %s",
                (action_date, note, contact_id),
            )
