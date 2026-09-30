"""Part 2 gate: DNC filtering (docs/contact-engine/02-dnc-filtering.md §4, §7).

One record of "don't call me again", keyed by phone: every path that blocks turns the
phone's `dnc_numbers` row on and writes `dnc_log`; every reader — the status, the gate,
the export, door B — refuses a live row; only an admin's lift turns it off, and only for
blocks the verbs recorded.
"""

import csv
import io
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from domain.types import RepRow
from jobs import dnc_refresh as scrub
from seams.fakes import FakeDncRegistry
from service import dnc, rep_intake
from service.assignment import assign_batch, export_batch, reclaim
from service.contacts import load_list, suppress
from service.custody import set_owner
from service.ingestion import ingest_event
from tests.factories import new_contact

AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
CONFIRMATION = "These are businesses I found through my own prospecting."


# --- fixtures and helpers ---------------------------------------------------------


@pytest.fixture()
def reps(clean_db, owner_conn):
    """Reps for the test; at teardown their log rows, intake rows, holdings, and the reps
    themselves are removed (clean_db never truncates partners)."""
    made: list[UUID] = []

    def make(status: str = "active") -> UUID:
        with owner_conn.cursor() as cur:
            cur.execute(
                "insert into partners (name, status) values (%s, %s) returning id",
                (f"Rep-{uuid4().hex[:8]}", status),
            )
            row = cur.fetchone()
            assert row is not None
        owner_conn.commit()
        made.append(row[0])
        return row[0]

    yield make
    owner_conn.rollback()
    with owner_conn.cursor() as cur:
        cur.execute("delete from dnc_log where rep_id = any(%s)", (made,))
        cur.execute("delete from intake_rep where rep_id = any(%s)", (made,))
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = any(%s)",
            (HOUSE_PARTNER_ID, made),
        )
        cur.execute("delete from assignment_batches where partner_id = any(%s)", (made,))
        cur.execute("delete from partners where id = any(%s)", (made,))
    owner_conn.commit()


def _contact(owner_conn, phone: str | None, **fields) -> UUID:
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, **fields)
    owner_conn.commit()
    return contact


def _sql(owner_conn, query: str, params=()):
    with owner_conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall() if cur.description else []
    owner_conn.commit()
    return rows


def _blocked(owner_conn, phone: str):
    """True / False from the phone's row; None when the phone has no row."""
    rows = _sql(owner_conn, "select blocked from dnc_numbers where phone_e164 = %s", (phone,))
    return rows[0][0] if rows else None


def _kinds(owner_conn, phone: str) -> list[str]:
    rows = _sql(
        owner_conn, "select kind from dnc_log where phone_e164 = %s order by seq", (phone,)
    )
    return [r[0] for r in rows]


def _subscribe(owner_conn, code: str = "818") -> None:
    _sql(
        owner_conn,
        "insert into dnc_subscriptions (area_code, subscribed_at) values (%s, now()) "
        "on conflict do nothing",
        (code,),
    )


def _clean_contact(owner_conn, phone: str) -> UUID:
    """A callable NMC contact: subscribed code, checked now, no link."""
    _subscribe(owner_conn, phone[2:5])
    return _contact(owner_conn, phone, dnc_checked_at=datetime.now(UTC))


def _hold(owner_conn, contact: UUID, rep: UUID) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep, event_type="contact.assigned", reason="test", actor="t")
    owner_conn.commit()


def _owner(owner_conn, contact: UUID) -> UUID:
    return _sql(owner_conn, "select owner_id from contacts where id = %s", (contact,))[0][0]


def _snapshot(owner_conn, code: str, version_date, status: str = "accepted") -> UUID:
    rows = _sql(
        owner_conn,
        "insert into dnc_snapshots (area_code, san_holder_id, version_date, file_guid, "
        "sha256, object_key, uploaded_at, status) "
        "values (%s, %s, %s, %s, %s, %s, now(), %s) returning id",
        (code, HOUSE_PARTNER_ID, version_date, uuid4().hex, uuid4().hex,
         f"dnc/t/{uuid4().hex}", status),
    )
    return rows[0][0]


def _gate_cause(owner_conn, contact: UUID, partner: UUID) -> str | None:
    report = assign_batch(partner, f"k-{uuid4().hex[:8]}", "test", contact_ids=[contact])
    causes = [c for c, ids in report.shortfall.items() if contact in ids]
    return causes[0] if causes else None


def _add(rep: UUID, phone: str):
    return rep_intake.add_numbers(rep, [RepRow(phone=phone)], "referral", CONFIRMATION,
                                  datetime.now(UTC))[0].result


def _now() -> datetime:
    return datetime.now(UTC)


# --- each path writes the row -----------------------------------------------------


def test_a_report_writes_a_rep_row(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185557001")
    _hold(owner_conn, contact, rep)
    assert dnc.report_do_not_call(rep, contact, "asked", AT) == "blocked"
    assert _blocked(owner_conn, "+18185557001") is True
    assert _kinds(owner_conn, "+18185557001") == ["rep"]


def test_an_admin_request_with_a_contact_writes_an_admin_row(clean_db, owner_conn):
    _contact(owner_conn, "+18185557002")
    assert dnc.record_do_not_call_request("+18185557002", "young", "email", AT) == "blocked"
    assert _blocked(owner_conn, "+18185557002") is True
    assert _kinds(owner_conn, "+18185557002") == ["admin"]


def test_an_admin_request_without_a_contact_writes_the_row_by_phone(clean_db, owner_conn):
    assert dnc.record_do_not_call_request("(818) 555-7003", "young", "call", AT) == "blocked"
    assert _blocked(owner_conn, "+18185557003") is True
    assert _kinds(owner_conn, "+18185557003") == ["admin"]
    assert _sql(owner_conn, "select count(*) from contacts")[0][0] == 0


def test_suppress_voice_writes_an_event_row(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185557004")
    suppress(contact, "voice", "asked")
    assert _blocked(owner_conn, "+18185557004") is True
    assert _kinds(owner_conn, "+18185557004") == ["event"]


@pytest.mark.parametrize("payload", [{"reason": "phone"}, {}, ["not", "an", "object"]])
def test_an_opt_out_on_a_contact_writes_an_event_row(clean_db, owner_conn, payload):
    contact = _contact(owner_conn, "+18185557005")
    ingest_event("human", "contact.opt_out", AT, payload, contact_id=contact)  # type: ignore[arg-type]
    assert _blocked(owner_conn, "+18185557005") is True
    assert _kinds(owner_conn, "+18185557005") == ["event"]


def test_a_suppressed_event_with_no_channel_writes_an_event_row(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185557006")
    ingest_event("human", "contact.suppressed", AT, {"reason": "x"}, contact_id=contact)
    assert _kinds(owner_conn, "+18185557006") == ["event"]


@pytest.mark.parametrize("payload", [
    {"phone_e164": "+18185557007"},
    {"phone": "(818) 555-7007"},
    {"phone": 8185557007},
])
def test_an_unmatched_opt_out_carrying_the_phone_writes_its_row(clean_db, owner_conn, payload):
    ingest_event("human", "contact.opt_out", AT, {"reason": "phone", **payload})
    assert _blocked(owner_conn, "+18185557007") is True
    assert _kinds(owner_conn, "+18185557007") == ["event"]


def test_attaching_an_opt_out_to_a_contact_blocks_the_contacts_phone(clean_db, owner_conn):
    """The update trigger: an unmatched opt-out with no phone (a mailer code only)
    blocks nothing until it is attached — then the contact's phone."""
    contact = _contact(owner_conn, "+18185557008")
    ingest_event("human", "contact.opt_out", AT, {"reason": "phone", "mailer_code": "m1"})
    assert _blocked(owner_conn, "+18185557008") is None
    _sql(owner_conn,
         "update events set contact_id = %s where type = 'contact.opt_out'", (contact,))
    assert _blocked(owner_conn, "+18185557008") is True
    assert _kinds(owner_conn, "+18185557008") == ["event"]


def _one_row_csv(tmp_path: Path, list_key: str, phone: str) -> str:
    path = tmp_path / f"{list_key}.csv"
    path.write_text(
        "list_key,business_name,contact_name,trade,trades,license_class,phone,email,"
        "addr_line1,addr_line2,addr_city,addr_state,addr_zip,segment,do_not_mail\n"
        f"{list_key},Biz,Owner,plumber,plumber,C36,{phone},,1 Main St,,Reseda,CA,91335,"
        "plumber-ca,\n"
    )
    return str(path)


def test_door_a_creating_a_contact_from_a_voice_tombstone_writes_an_intake_row(
    clean_db, owner_conn, tmp_path
):
    _sql(owner_conn, "insert into suppression_tombstones (phone_e164, channel, reason) "
                     "values ('+18185557009', 'voice', 'asked')")
    load_list(_one_row_csv(tmp_path, "cslb-t-9", "818-555-7009"), source="cslb")
    assert _blocked(owner_conn, "+18185557009") is True
    assert _kinds(owner_conn, "+18185557009") == ["intake"]


def test_door_a_attaching_a_list_row_whose_key_has_a_voice_tombstone_writes_an_intake_row(
    clean_db, owner_conn, tmp_path
):
    _contact(owner_conn, "+18185557010")
    _sql(owner_conn, "insert into suppression_tombstones (list_key, channel, reason) "
                     "values ('cslb-t-10', 'voice', 'asked')")
    load_list(_one_row_csv(tmp_path, "cslb-t-10", "818-555-7010"), source="cslb")
    assert _blocked(owner_conn, "+18185557010") is True
    assert _kinds(owner_conn, "+18185557010") == ["intake"]


# --- not blocks --------------------------------------------------------------------


def test_a_mail_only_opt_out_writes_no_row(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185557011")
    ingest_event("human", "contact.opt_out", AT, {"reason": "do_not_mail"}, contact_id=contact)
    assert _blocked(owner_conn, "+18185557011") is None


def test_a_mail_channel_suppression_writes_no_row(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185557012")
    ingest_event("human", "contact.suppressed", AT, {"channel": "mail"}, contact_id=contact)
    assert _blocked(owner_conn, "+18185557012") is None


def test_an_unmatched_event_with_a_non_object_payload_writes_no_row_and_crashes_nothing(
    reps, owner_conn
):
    rep = reps()
    contact = _clean_contact(owner_conn, "+18185557013")
    ingest_event("human", "contact.opt_out", AT, ["+18185557013"])  # type: ignore[arg-type]
    assert _sql(owner_conn, "select count(*) from dnc_numbers")[0][0] == 0
    assert dnc.dnc_status(contact, _now()) == "clear"
    assert _add(rep, "+18185557014") == "added"


# --- each reader refuses a bare live row ------------------------------------------


def _bare_row(owner_conn, phone: str) -> None:
    """A live row and its log entry, and nothing else: no flag, tombstone, or event."""
    _sql(owner_conn, "select dnc_block(%s, 'admin', 'test', null, null, 'x', now())", (phone,))


def test_a_live_row_alone_is_do_not_call_in_the_status(clean_db, owner_conn):
    contact = _clean_contact(owner_conn, "+18185557015")
    _bare_row(owner_conn, "+18185557015")
    assert dnc.dnc_status(contact, _now()) == "do_not_call"


def test_a_live_row_alone_is_refused_by_the_gate_as_voice_suppressed(reps, owner_conn):
    partner = reps()
    contact = _clean_contact(owner_conn, "+18185557016")
    _bare_row(owner_conn, "+18185557016")
    assert _gate_cause(owner_conn, contact, partner) == "voice_suppressed"


def test_a_live_row_turned_on_after_assignment_keeps_it_off_the_sheet(reps, owner_conn):
    partner = reps()
    contact = _clean_contact(owner_conn, "+18185557017")
    assert assign_batch(partner, "k-17", "test", contact_ids=[contact]).assigned == [contact]
    _bare_row(owner_conn, "+18185557017")
    result = export_batch(partner)
    phones = {r["phone"] for r in csv.DictReader(io.StringIO(result.csv))}
    assert "+18185557017" not in phones
    assert all(contact not in ids for ids in result.shortfall.values())


def test_door_b_refuses_a_live_row_on_an_existing_contact_and_on_a_new_number(
    reps, owner_conn
):
    rep = reps()
    _contact(owner_conn, "+18185557018")
    _bare_row(owner_conn, "+18185557018")
    _bare_row(owner_conn, "+18185557019")
    assert _add(rep, "+18185557018") == "do_not_call"
    assert _add(rep, "+18185557019") == "do_not_call"
    assert _sql(owner_conn, "select count(*) from contacts where phone_e164 = %s",
                ("+18185557019",))[0][0] == 0


# --- the backfill -----------------------------------------------------------------


def test_the_backfill_writes_a_row_for_every_legacy_form(clean_db, owner_conn):
    _contact(owner_conn, "+18185557020", do_not_call=True)
    _sql(owner_conn, "insert into suppression_tombstones (phone_e164, channel, reason) "
                     "values ('+18185557021', 'voice', 'x')")
    _contact(owner_conn, "+18185557022", list_key="cslb-bf-22")
    _sql(owner_conn, "insert into suppression_tombstones (list_key, channel, reason) "
                     "values ('cslb-bf-22', 'voice', 'x')")
    opted = _contact(owner_conn, "+18185557023")
    ingest_event("human", "contact.opt_out", AT, {"reason": "phone"}, contact_id=opted)
    ingest_event("human", "contact.opt_out", AT, {"phone": "818-555-7024"})
    mail_only = _contact(owner_conn, "+18185557025")
    ingest_event("human", "contact.opt_out", AT, {"reason": "do_not_mail"},
                 contact_id=mail_only)
    _sql(owner_conn, "truncate dnc_numbers, dnc_log restart identity")

    count = _sql(owner_conn, "select dnc_backfill()")[0][0]

    blocked = {r[0] for r in _sql(owner_conn,
                                  "select phone_e164 from dnc_numbers where blocked")}
    assert blocked == {"+18185557020", "+18185557021", "+18185557022",
                       "+18185557023", "+18185557024"}
    assert count == 5
    assert {r[0] for r in _sql(owner_conn, "select distinct kind from dnc_log")} == {"backfill"}


# --- the status -------------------------------------------------------------------


def test_the_status_refuses_a_naive_time_and_an_unknown_contact(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185557030")
    with pytest.raises(ValidationError) as err:
        dnc.dnc_status(contact, datetime(2026, 9, 30, 12, 0))
    assert err.value.code == "bad_time"
    with pytest.raises(ValidationError) as err:
        dnc.dnc_status(uuid4(), _now())
    assert err.value.code == "no_contact"


def test_status_seed_no_phone_on_file_clear(clean_db, owner_conn):
    _subscribe(owner_conn)
    seed = _contact(owner_conn, "+18185557031", is_seed=True, seed_key="s31", intake=False)
    phoneless = _contact(owner_conn, None)
    listed = _contact(owner_conn, "+18185557032", dnc_checked_at=_now(), dnc_registry=True)
    clear = _contact(owner_conn, "+18185557033", dnc_checked_at=_now())
    assert dnc.dnc_status(seed, _now()) == "seed"
    assert dnc.dnc_status(phoneless, _now()) == "no_phone"
    assert dnc.dnc_status(listed, _now()) == "on_dnc_file"
    assert dnc.dnc_status(clear, _now()) == "clear"


def test_status_not_checked_until_a_run_then_not_covered(clean_db, owner_conn):
    uncovered = _contact(owner_conn, "+13105557034")
    before_run = _now()
    assert dnc.dnc_status(uncovered, _now()) == "not_checked"
    scrub.dnc_refresh_all()
    assert dnc.dnc_status(uncovered, _now()) == "not_covered"
    assert dnc.dnc_status(uncovered, before_run) == "not_checked"
    later = _contact(owner_conn, "+13105557035")
    assert dnc.dnc_status(later, _now()) == "not_checked"


def test_status_a_claim_after_the_run_waits_for_the_next(reps, owner_conn):
    old = _contact(owner_conn, "+13105557036")
    scrub.dnc_refresh_all()
    rep = reps()
    _sql(owner_conn,
         "insert into intake_rep (contact_id, rep_id, phone_e164, how_obtained, "
         "confirmation, added_at) values (%s, %s, '+13105557036', 'referral', 'c', now())",
         (old, rep))
    assert dnc.dnc_status(old, _now()) == "not_checked"


def test_limited_and_single_registry_runs_do_not_count(clean_db, owner_conn):
    uncovered = _contact(owner_conn, "+13105557037")
    scrub.dnc_refresh_all(limit=1)
    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={}))
    assert dnc.dnc_status(uncovered, _now()) == "not_checked"


def test_status_not_checked_forms(clean_db, owner_conn):
    _subscribe(owner_conn)
    never = _contact(owner_conn, "+18185557038")
    future = _contact(owner_conn, "+18185557039", dnc_checked_at=_now() + timedelta(hours=1))
    other_code = _contact(owner_conn, "+18185557040", dnc_checked_at=_now(),
                          dnc_snapshot_id=_snapshot(owner_conn, "714", _now().date()))
    rejected = _contact(owner_conn, "+18185557041", dnc_checked_at=_now(),
                        dnc_snapshot_id=_snapshot(owner_conn, "818", _now().date(),
                                                  status="rejected"))
    for contact in (never, future, other_code, rejected):
        assert dnc.dnc_status(contact, _now()) == "not_checked"


def test_status_the_31_days(clean_db, owner_conn):
    _subscribe(owner_conn)
    at = _now()
    inside = _contact(owner_conn, "+18185557042",
                      dnc_checked_at=at - timedelta(days=31) + timedelta(minutes=1))
    past = _contact(owner_conn, "+18185557043",
                    dnc_checked_at=at - timedelta(days=31) - timedelta(minutes=1))
    utc_today = at.date()
    list_31 = _contact(owner_conn, "+18185557044", dnc_checked_at=at,
                       dnc_snapshot_id=_snapshot(owner_conn, "818",
                                                 utc_today - timedelta(days=31)))
    list_32 = _contact(owner_conn, "+18185557045", dnc_checked_at=at,
                       dnc_snapshot_id=_snapshot(owner_conn, "818",
                                                 utc_today - timedelta(days=32)))
    assert dnc.dnc_status(inside, at) == "clear"
    assert dnc.dnc_status(past, at) == "check_too_old"
    assert dnc.dnc_status(list_31, at) == "clear"
    assert dnc.dnc_status(list_32, at) == "check_too_old"


def test_status_the_order(clean_db, owner_conn):
    _subscribe(owner_conn)
    blocked_and_listed = _contact(owner_conn, "+18185557046", dnc_checked_at=_now(),
                                  dnc_registry=True, do_not_call=True)
    listed_and_stale = _contact(owner_conn, "+18185557047", dnc_registry=True,
                                dnc_checked_at=_now() - timedelta(days=40))
    uncovered_listed = _contact(owner_conn, "+13105557048", dnc_registry=True,
                                dnc_checked_at=_now())
    scrub.dnc_refresh_all()
    assert dnc.dnc_status(blocked_and_listed, _now()) == "do_not_call"
    assert dnc.dnc_status(listed_and_stale, _now()) == "on_dnc_file"
    assert dnc.dnc_status(uncovered_listed, _now()) == "not_covered"


# --- the run record ---------------------------------------------------------------


def _runs(owner_conn) -> int:
    return _sql(owner_conn, "select count(*) from dnc_runs")[0][0]


def test_dnc_refresh_all_records_a_run_even_with_nothing_subscribed(clean_db, owner_conn):
    scrub.dnc_refresh_all()
    assert _runs(owner_conn) == 1


def test_a_run_that_raises_records_nothing(clean_db, owner_conn, monkeypatch):
    _subscribe(owner_conn)

    def broken(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(scrub, "_coverage", broken)
    with pytest.raises(RuntimeError):
        scrub.dnc_refresh_all()
    assert _runs(owner_conn) == 0


def test_the_single_registry_scrub_records_no_run(clean_db, owner_conn):
    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={}))
    assert _runs(owner_conn) == 0


# --- a rep's report ----------------------------------------------------------------


def test_report_refusals_write_nothing(reps, owner_conn):
    rep, stranger = reps(), reps()
    contact = _contact(owner_conn, "+18185557050")
    phoneless = _contact(owner_conn, None)
    _hold(owner_conn, phoneless, rep)
    _hold(owner_conn, contact, rep)
    cases = [
        ((rep, contact, "x", datetime(2026, 9, 30)), "bad_time"),
        ((rep, uuid4(), "x", AT), "no_contact"),
        ((rep, phoneless, "x", AT), "no_phone"),
        ((uuid4(), contact, "x", AT), "bad_rep"),
        ((HOUSE_PARTNER_ID, contact, "x", AT), "bad_rep"),
        ((stranger, contact, "x", AT), "not_yours"),
    ]
    for args, code in cases:
        with pytest.raises(ValidationError) as err:
            dnc.report_do_not_call(*args)
        assert err.value.code == code
    assert _sql(owner_conn, "select count(*) from dnc_log")[0][0] == 0


def test_a_report_writes_only_the_row_and_the_log_and_keeps_custody(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185557051")
    _hold(owner_conn, contact, rep)
    events_before = _sql(owner_conn, "select count(*) from events")[0][0]
    dnc.report_do_not_call(rep, contact, "  ", AT)
    assert _owner(owner_conn, contact) == rep
    flag, = _sql(owner_conn, "select do_not_call from contacts where id = %s", (contact,))[0]
    assert flag is False
    assert _sql(owner_conn, "select count(*) from suppression_tombstones")[0][0] == 0
    assert _sql(owner_conn, "select count(*) from events")[0][0] == events_before
    entry = dnc.dnc_history("+18185557051")[0]
    assert (entry.kind, entry.rep_id, entry.reason, entry.at) == (
        "rep", rep, "asked not to be called", AT
    )


def test_a_rep_who_held_it_and_lost_it_can_report(reps, owner_conn):
    rep = reps(status="active")
    contact = _contact(owner_conn, "+18185557052")
    _hold(owner_conn, contact, rep)
    reclaim(rep, "back", "young")
    _sql(owner_conn, "update partners set status = 'inactive' where id = %s", (rep,))
    assert dnc.report_do_not_call(rep, contact, "asked", AT) == "blocked"
    assert _owner(owner_conn, contact) == HOUSE_PARTNER_ID


def test_a_report_on_a_blocked_phone_is_another_log_entry(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185557053")
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "a", AT)
    dnc.report_do_not_call(rep, contact, "b", AT)
    assert _kinds(owner_conn, "+18185557053") == ["rep", "rep"]


# --- an admin's request -------------------------------------------------------------


def test_admin_request_refusals(clean_db, owner_conn):
    for args, code in [
        (("+18185557060", "young", "x", datetime(2026, 9, 30)), "bad_time"),
        (("+18185557060", "young", "  ", AT), "no_reason"),
        (("12345", "young", "x", AT), "invalid_phone"),
        (("８１８５５５７０６０", "young", "x", AT), "invalid_phone"),
    ]:
        with pytest.raises(ValidationError) as err:
            dnc.record_do_not_call_request(*args)
        assert err.value.code == code
    assert _sql(owner_conn, "select count(*) from dnc_log")[0][0] == 0


def test_an_admin_request_keeps_custody_and_door_a_then_reads_the_row(
    reps, owner_conn, tmp_path
):
    rep = reps()
    contact = _contact(owner_conn, "+18185557061")
    _hold(owner_conn, contact, rep)
    dnc.record_do_not_call_request("+18185557061", "young", "email", AT)
    assert _owner(owner_conn, contact) == rep
    dnc.record_do_not_call_request("+18185557062", "young", "email", AT)
    load_list(_one_row_csv(tmp_path, "cslb-t-62", "818-555-7062"), source="cslb")
    created = _sql(owner_conn, "select id from contacts where phone_e164 = '+18185557062'")
    assert dnc.dnc_status(created[0][0], _now()) == "do_not_call"


# --- the lift -------------------------------------------------------------------------


def _latest(phone: str) -> int:
    return dnc.dnc_history(phone)[-1].seq


def test_lift_refusals_write_nothing(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185557070")
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "x", AT)
    dnc.record_do_not_call_request("+18185557071", "young", "x", AT)
    seq = _latest("+18185557070")
    other = _latest("+18185557071")
    for args, code in [
        (("+18185557070", seq, "young", "r", datetime(2026, 9, 30)), "bad_time"),
        (("+18185557070", seq, "young", " ", AT), "no_reason"),
        (("123", seq, "young", "r", AT), "invalid_phone"),
        (("+18185557079", seq, "young", "r", AT), "nothing_to_lift"),
        (("+18185557070", seq - 1, "young", "r", AT), "changed"),
        (("+18185557070", other, "young", "r", AT), "changed"),
    ]:
        with pytest.raises(ValidationError) as err:
            dnc.lift_do_not_call(*args)
        assert err.value.code == code
    assert _blocked(owner_conn, "+18185557070") is True
    assert _kinds(owner_conn, "+18185557070") == ["rep"]


@pytest.mark.parametrize("form", ["event", "intake", "backfill", "tombstone", "flag"])
def test_a_block_from_any_other_path_is_not_liftable(reps, owner_conn, form, tmp_path):
    rep = reps()
    phone = "+18185557072"
    if form == "intake":
        _sql(owner_conn, "insert into suppression_tombstones (phone_e164, channel, reason) "
                         "values (%s, 'voice', 'x')", (phone,))
        load_list(_one_row_csv(tmp_path, "cslb-t-72", "818-555-7072"), source="cslb")
        _sql(owner_conn, "delete from suppression_tombstones")
        contact = _sql(owner_conn, "select id from contacts")[0][0]
        _sql(owner_conn, "update contacts set do_not_call = false")
    else:
        contact = _contact(owner_conn, phone)
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "x", AT)
    if form == "event":
        ingest_event("human", "contact.opt_out", AT, {"reason": "phone"}, contact_id=contact)
    elif form == "backfill":
        _sql(owner_conn, "select dnc_block(%s, 'backfill', 'backfill', null, null, null, now())",
             (phone,))
    elif form == "tombstone":
        _sql(owner_conn, "insert into suppression_tombstones (phone_e164, channel, reason) "
                         "values (%s, 'voice', 'x')", (phone,))
    elif form == "flag":
        _sql(owner_conn, "update contacts set do_not_call = true where id = %s", (contact,))
    with pytest.raises(ValidationError) as err:
        dnc.lift_do_not_call(phone, _latest(phone), "young", "mistake", AT)
    assert err.value.code == "not_liftable"
    assert _blocked(owner_conn, phone) is True


def test_a_lift_turns_the_row_off_and_a_new_report_blocks_again(reps, owner_conn):
    rep = reps()
    contact = _clean_contact(owner_conn, "+18185557073")
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "x", AT)
    dnc.record_do_not_call_request("+18185557073", "young", "email", AT)
    assert dnc.lift_do_not_call("+18185557073", _latest("+18185557073"), "young",
                                "rep tapped by mistake", AT) == "lifted"
    assert _blocked(owner_conn, "+18185557073") is False
    last = dnc.dnc_history("+18185557073")[-1]
    assert (last.kind, last.actor, last.reason) == ("lift", "young", "rep tapped by mistake")
    assert dnc.dnc_status(contact, _now()) == "clear"
    dnc.report_do_not_call(rep, contact, "again", AT)
    assert dnc.dnc_status(contact, _now()) == "do_not_call"


# --- locking --------------------------------------------------------------------------


def _wait_until_blocked(owner_url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    with psycopg.connect(owner_url, autocommit=True) as probe:
        while time.monotonic() < deadline:
            row = probe.execute("select count(*) from pg_locks where not granted").fetchone()
            if row is not None and row[0] > 0:
                return
            time.sleep(0.02)
    raise AssertionError("nothing waited on a lock")


def _paused(monkeypatch, owner_url: str, then) -> threading.Thread:
    """Make the verbs' `_after_lock` hook start `then` in a thread, wait until it blocks
    on a lock, and carry on — so the verb commits with the other writer waiting."""
    worker = threading.Thread(target=then)

    def hook(cur):
        if threading.current_thread() is worker:
            return
        worker.start()
        _wait_until_blocked(owner_url)

    monkeypatch.setattr(dnc, "_after_lock", hook)
    return worker


def test_a_report_waiting_on_a_lift_blocks_again_after_it(reps, owner_conn, owner_url,
                                                          monkeypatch):
    rep = reps()
    contact = _contact(owner_conn, "+18185557080")
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "x", AT)
    seq = _latest("+18185557080")
    worker = _paused(monkeypatch, owner_url,
                     lambda: dnc.report_do_not_call(rep, contact, "again", AT))
    dnc.lift_do_not_call("+18185557080", seq, "young", "mistake", AT)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert _blocked(owner_conn, "+18185557080") is True


def test_an_opt_out_waiting_on_a_lift_blocks_again_after_it(reps, owner_conn, owner_url,
                                                            monkeypatch):
    rep = reps()
    contact = _contact(owner_conn, "+18185557081")
    _hold(owner_conn, contact, rep)
    dnc.report_do_not_call(rep, contact, "x", AT)
    seq = _latest("+18185557081")
    worker = _paused(monkeypatch, owner_url, lambda: ingest_event(
        "human", "contact.opt_out", AT, {"reason": "phone"}, contact_id=contact))
    dnc.lift_do_not_call("+18185557081", seq, "young", "mistake", AT)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert _blocked(owner_conn, "+18185557081") is True


def test_a_report_committing_while_the_gate_waits_is_seen_by_its_second_read(
    reps, owner_conn, owner_url, monkeypatch
):
    rep, partner = reps(), reps()
    contact = _clean_contact(owner_conn, "+18185557082")
    _hold(owner_conn, contact, rep)
    # the rep held it (so may report); it is back with the house, so a batch may take it
    _sql(owner_conn, "update contacts set owner_id = %s where id = %s",
         (HOUSE_PARTNER_ID, contact))
    result = {}
    worker = _paused(monkeypatch, owner_url, lambda: result.update(
        cause=_gate_cause(owner_conn, contact, partner)))
    dnc.report_do_not_call(rep, contact, "x", AT)
    worker.join(timeout=10)
    assert result["cause"] == "voice_suppressed"


def test_a_report_committing_while_door_b_waits_is_seen(reps, owner_conn, owner_url,
                                                        monkeypatch):
    rep, other = reps(), reps()
    contact = _contact(owner_conn, "+18185557083")
    _hold(owner_conn, contact, rep)
    result = {}
    worker = _paused(monkeypatch, owner_url,
                     lambda: result.update(out=_add(other, "+18185557083")))
    dnc.report_do_not_call(rep, contact, "x", AT)
    worker.join(timeout=10)
    assert result["out"] == "do_not_call"


def test_two_events_crossing_phones_do_not_deadlock(clean_db, owner_url):
    first = psycopg.connect(owner_url)
    try:
        first.execute(
            "insert into events (source, type, occurred_at, payload) values "
            "('human', 'contact.opt_out', now(), "
            "'{\"phone\": \"+18185557085\", \"phone_e164\": \"+18185557084\"}')"
        )
        errors = []

        def second():
            try:
                with psycopg.connect(owner_url) as conn:
                    conn.execute(
                        "insert into events (source, type, occurred_at, payload) values "
                        "('human', 'contact.opt_out', now(), "
                        "'{\"phone\": \"+18185557084\", \"phone_e164\": \"+18185557085\"}')"
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        worker = threading.Thread(target=second)
        worker.start()
        _wait_until_blocked(owner_url)
        first.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert errors == []
    finally:
        first.close()


# --- the single-registry scrub ----------------------------------------------------------


def test_the_single_registry_scrub_runs_only_on_an_allowed_database(
    clean_db, owner_conn, monkeypatch
):
    contact = _clean_contact(owner_conn, "+18185557090")
    _sql(owner_conn, "update contacts set dnc_checked_at = null where id = %s", (contact,))
    monkeypatch.setattr(scrub, "SINGLE_REGISTRY_DATABASES", frozenset())
    with pytest.raises(ValidationError) as err:
        scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={}))
    assert err.value.code == "not_a_dev_database"
    assert _sql(owner_conn, "select dnc_checked_at from contacts where id = %s",
                (contact,))[0][0] is None
    monkeypatch.undo()
    scrub.dnc_refresh(FakeDncRegistry(version="v1", numbers={}))
    assert _sql(owner_conn, "select dnc_checked_at from contacts where id = %s",
                (contact,))[0][0] is not None
