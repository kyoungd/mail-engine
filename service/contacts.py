"""List and contact verbs (service contract §2).

`load_list` is the one-time bulk intake (parse, dedupe, E.164, segment). NCOA/CASS
address validation is deliberately NOT here: it needs the print seam, which the
dependency rule bars from the service layer — it lands as a Phase 3 job that stamps
`addr_validated_at`. `suppress` is one-way (no unsuppress verb exists); `record_outcome`
declares a conversation lost; `set_next_action` is the founder's override of the
judgment slot.
"""

import csv
import re
from datetime import UTC, date, datetime
from uuid import UUID

from psycopg import sql

from db.session import transaction
from domain.errors import ValidationError
from domain.phone import to_e164
from domain.types import IntakeReport, SeedReport
from resolution.pick import coalesce_email, pick_winner
from service.ingestion import ingest_event

_TRUTHY = {"1", "true", "t", "yes", "y"}


def _clean(row: dict, key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


def _segment(trade: str, state: str | None) -> str:
    """Deterministic default segment: trade, narrowed by geography when present.
    A placeholder the operator refines; segments are free text by design."""
    return f"{trade.lower()}-{state.upper()}" if state else trade.lower()


# Source routing is a pinned registry, not a free string (§4). A known source names the
# intake table AND the identity rule that resolves its rows to contacts; an unrecognized
# one raises before a single row is read, so a typo or a stale UI default can never route
# rows into the wrong table silently. A new adapter registers its source when it lands.
PHONE = "phone"
PER_FILING = "per_filing"
_SOURCE_EXACT = {
    "cslb": ("intake_cslb_ca", PHONE),
    "cslb-ca": ("intake_cslb_ca", PHONE),
}
_SOURCE_PREFIX = (("fbn-ca-", ("intake_fbn_ca", PER_FILING)),)

_INTAKE_COLS = sql.SQL(", ").join(
    sql.Identifier(c)
    for c in (
        "list_key", "contact_id", "is_primary", "business_name", "contact_name",
        "trade", "trades", "license_class", "phone_e164", "email", "addr_line1",
        "addr_line2", "addr_city", "addr_state", "addr_zip", "segment", "do_not_mail",
    )
)


def resolve_source(source: str) -> tuple[str, str]:
    """Map a load's `source` to (intake table, identity rule). Fail-loud on anything
    unregistered — §4's guard against silent mis-routing."""
    if source in _SOURCE_EXACT:
        return _SOURCE_EXACT[source]
    for prefix, target in _SOURCE_PREFIX:
        if source.startswith(prefix):
            return target
    known = sorted(_SOURCE_EXACT) + [f"{p}*" for p, _ in _SOURCE_PREFIX]
    raise ValidationError(
        "unknown_source",
        f"source {source!r} is not in the intake registry; known sources: {known}",
    )


def _trades(row: dict) -> list[str]:
    """The adapter emits the sorted distinct union pipe-delimited ('hvac|plumber')."""
    raw = _clean(row, "trades")
    return [t for t in (part.strip() for part in raw.split("|")) if t] if raw else []


def load_list(csv_path: str, source: str = "cslb") -> IntakeReport:
    """Bulk intake of a canonical intake CSV (the output of an intake adapter, see
    intake/), resolve-then-insert in one transaction per file (§4).

    Parse and validate first (dedupe on list_key against this source's intake table and
    within the file, normalize phones to E.164, assign a segment; a row must be
    targetable — trade or segment — else it is invalid and gets no intake row). Then
    resolve every accepted row to a contact IN MEMORY by the source's identity rule,
    which is a property of the adapter and not a universal: CSLB groups by phone, FBN is
    one contact per filing. Only then insert the intake rows, each carrying the
    `contact_id` and `is_primary` it resolved to — which is what keeps `contact_id` NOT
    NULL and set-at-insert.

    Resolution is per-file, not row-at-a-time, so semantics cannot depend on row order
    within the file. A phone group whose phone already has a contact ATTACHES without
    re-picking (§3: pick runs once, when the contact is created); `do_not_mail` is the
    single contact field an attach writes, OR-merged, because suppression is absorbing."""
    table, rule = resolve_source(source)  # before any row is read

    loaded = deduped = invalid = suppressed = 0
    seen: set[str] = set()
    accepted: list[dict] = []

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("select list_key from {}").format(sql.Identifier(table))
            )
            existing = {r[0] for r in cur.fetchall()}

            with open(csv_path, newline="") as handle:
                for row in csv.DictReader(handle):
                    trade = _clean(row, "trade")
                    segment = _clean(row, "segment") or (
                        _segment(trade, _clean(row, "addr_state")) if trade else None
                    )
                    if not segment:
                        invalid += 1
                        continue

                    list_key = _clean(row, "list_key")
                    if list_key and (list_key in existing or list_key in seen):
                        deduped += 1
                        continue
                    if list_key:
                        seen.add(list_key)

                    accepted.append(
                        {
                            "list_key": list_key,
                            "business_name": _clean(row, "business_name"),
                            "contact_name": _clean(row, "contact_name"),
                            "trade": trade,
                            "trades": _trades(row),
                            "license_class": _clean(row, "license_class"),
                            "phone_e164": to_e164(row.get("phone")),
                            "email": _clean(row, "email"),
                            "addr_line1": _clean(row, "addr_line1"),
                            "addr_line2": _clean(row, "addr_line2"),
                            "addr_city": _clean(row, "addr_city"),
                            "addr_state": _clean(row, "addr_state"),
                            "addr_zip": _clean(row, "addr_zip"),
                            "segment": segment,
                            "do_not_mail": (row.get("do_not_mail") or "").strip().lower()
                            in _TRUTHY,
                        }
                    )

            groups = _group(accepted, rule)
            for group in groups:
                contact_id, primary_key = _resolve_group(cur, group, rule, source)
                for member in group:
                    cur.execute(
                        sql.SQL(
                            "insert into {table} ({cols}) "
                            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                        ).format(table=sql.Identifier(table), cols=_INTAKE_COLS),
                        (
                            member["list_key"],
                            contact_id,
                            member["list_key"] == primary_key,
                            member["business_name"],
                            member["contact_name"],
                            member["trade"],
                            member["trades"],
                            member["license_class"],
                            member["phone_e164"],
                            member["email"],
                            member["addr_line1"],
                            member["addr_line2"],
                            member["addr_city"],
                            member["addr_state"],
                            member["addr_zip"],
                            member["segment"],
                            member["do_not_mail"],
                        ),
                    )
                    loaded += 1
                    if member["do_not_mail"]:
                        suppressed += 1

    return IntakeReport(
        loaded=loaded, deduped=deduped, invalid=invalid, suppressed=suppressed
    )


def _group(rows: list[dict], rule: str) -> list[list[dict]]:
    """Partition accepted rows into resolution groups. CSLB: same phone ⇒ same group
    (a row with no phone is its own group — §3's "one contact per row"). FBN: every row
    is its own group, no phone grouping ever, even should a filing carry a phone."""
    if rule == PER_FILING:
        return [[row] for row in rows]
    by_phone: dict[str, list[dict]] = {}
    groups: list[list[dict]] = []
    for row in rows:
        phone = row["phone_e164"]
        if not phone:
            groups.append([row])
        else:
            by_phone.setdefault(phone, []).append(row)
    return groups + list(by_phone.values())


def _resolve_group(cur, group: list[dict], rule: str, source: str) -> tuple[UUID, str | None]:
    """Resolve one group to (contact_id, the list_key of the row to mark primary).

    An existing contact for the group's phone means ATTACH: no re-pick, no field writes
    beyond the absorbing `do_not_mail` merge, and no primary — the contact already has
    one, and the partial unique index would reject a second."""
    phone = group[0]["phone_e164"] if rule == PHONE else None
    suppress_group = any(member["do_not_mail"] for member in group)

    if phone:
        cur.execute(
            "select id from contacts where phone_e164 = %s and is_seed = false", (phone,)
        )
        found = cur.fetchone()
        if found is not None:
            if suppress_group:
                cur.execute(
                    "update contacts set do_not_mail = true where id = %s", (found[0],)
                )
            return found[0], None

    winner = pick_winner(group)
    cur.execute(
        "insert into contacts "
        "(business_name, contact_name, phone_e164, email, addr_line1, addr_line2, "
        "addr_city, addr_state, addr_zip, segment, source, do_not_mail) "
        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
        (
            winner["business_name"],
            winner["contact_name"],
            # FBN identity never carries a phone onto the contact (§3): the phone stays
            # on the intake row, so it can never collide with the unique index nor merge
            # two filings.
            phone,
            coalesce_email(group, winner),
            winner["addr_line1"],
            winner["addr_line2"],
            winner["addr_city"],
            winner["addr_state"],
            winner["addr_zip"],
            winner["segment"],
            source,
            suppress_group,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0], winner["list_key"]


def _seed_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return f"seed-{slug}"


def ensure_seed_contacts(seeds: list[dict]) -> SeedReport:
    """Upsert founder addresses as is_seed contacts (PRD FR-4) — the seed addresses are
    config, not a management UI. Idempotent on a derived list_key (seed-<slug of name>):
    re-running this (a deploy, a cron) never duplicates a seed. Seeds carry no trade and
    segment='seed'; they ride every wave as one extra piece (resolve_audience) and are
    excluded from all response metrics (FR-7/FR-13)."""
    created = 0
    with transaction() as conn:
        with conn.cursor() as cur:
            for seed in seeds:
                cur.execute(
                    "insert into contacts (seed_key, business_name, is_seed, segment, "
                    "addr_line1, addr_line2, addr_city, addr_state, addr_zip) "
                    "values (%s, %s, true, 'seed', %s, %s, %s, %s, %s) "
                    "on conflict (seed_key) do update set "
                    "business_name = excluded.business_name, is_seed = true, "
                    "addr_line1 = excluded.addr_line1, addr_line2 = excluded.addr_line2, "
                    "addr_city = excluded.addr_city, addr_state = excluded.addr_state, "
                    "addr_zip = excluded.addr_zip "
                    "returning (xmax = 0)",  # xmax = 0 => this row was inserted, not updated
                    (
                        _seed_key(seed["name"]),
                        seed["name"],
                        seed["line1"],
                        seed.get("line2"),
                        seed["city"],
                        seed["state"],
                        seed["zip"],
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                if row[0]:
                    created += 1
            cur.execute("select count(*) from contacts where is_seed")
            total_row = cur.fetchone()
            assert total_row is not None

    return SeedReport(total=total_row[0], created=created)


def retire_seed(contact_id: UUID) -> None:
    """Take a founder seed out of service (§10 test 10). Clearing `is_seed` alone would
    only stop the per-wave seed append while leaving the row eligible for a rule-less
    full-list wave, so the flag clear and the suppression are one statement: a retired
    seed is in no audience under any rule. `ensure_seed_contacts` cannot revive it once
    its config entry is gone, because that verb only touches the seeds it is given."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update contacts set is_seed = false, do_not_mail = true where id = %s",
                (contact_id,),
            )
            if cur.rowcount == 0:
                raise ValidationError("no_contact", f"no contact {contact_id}")


def update_contact_address(
    contact_id: UUID,
    addr_line1: str | None,
    addr_line2: str | None,
    addr_city: str | None,
    addr_state: str | None,
    addr_zip: str | None,
) -> None:
    """The one sanctioned operator write of `contacts.addr_*` (§5). Raw SQL edits are out
    of contract. Stamping `addr_validated_at` is what makes the `verify_addresses` inherit
    guard safe: the job only ever fills a null stamp, so a human correction is never
    overwritten — enforced by code rather than convention."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "update contacts set addr_line1 = %s, addr_line2 = %s, addr_city = %s, "
                "addr_state = %s, addr_zip = %s, addr_validated_at = now() where id = %s",
                (addr_line1, addr_line2, addr_city, addr_state, addr_zip, contact_id),
            )
            if cur.rowcount == 0:
                raise ValidationError("no_contact", f"no contact {contact_id}")


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
                # opt_out halts both channels immediately: mail via do_not_mail (so the
                # audience resolver excludes them before the next recompute), SMS via
                # do_not_text. Matches the suppressed derivation (opt_out => suppressed).
                cur.execute(
                    "update contacts set do_not_mail = true, do_not_text = true "
                    "where id = %s",
                    (contact_id,),
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
