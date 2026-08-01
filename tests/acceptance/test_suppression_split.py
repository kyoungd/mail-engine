"""Partner Phase 2 gate (partner-lead-assignment-implementation.md, Batch B, frozen
2026-08-01, 🔴-approved): the suppression split + DNC scrub.

One test per row of S-6's table — five columns × (set, gate, clear) — plus the named
specials: the accepted-reasons regression (do_not_call stays IN the mail audience),
the historical-event trap (opt_out with payload.reason='do_not_mail' derives
mail-only), assignment-ending voice suppressions, scrub idempotency and delisting,
deterministic address_undeliverable recompute, the event-only opt-out backstop,
record_note's note.*-only restriction, and the tombstone surviving re-ingest."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from config.params import HOUSE_PARTNER_ID
from domain.errors import ValidationError
from seams.fakes import FakeDncRegistry
from service.contacts import clear_suppression, load_list, suppress
from service.custody import set_owner
from service.execution import recompute_state
from service.ingestion import ingest_event
from service.waves import resolve_audience
from tests.factories import new_contact

AT = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def _flags(cur, contact_id) -> dict:
    cur.execute(
        "select do_not_mail, do_not_text, do_not_call, dnc_registry, "
        "address_undeliverable from contacts where id = %s",
        (contact_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return dict(
        zip(
            ["do_not_mail", "do_not_text", "do_not_call", "dnc_registry",
             "address_undeliverable"],
            row,
        )
    )


def _stage(cur, contact_id) -> str:
    cur.execute("select stage_snapshot from contacts where id = %s", (contact_id,))
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _audience(cur, rule=None) -> list:
    return resolve_audience(cur, rule if rule is not None else {"trade": ["plumber"]}).ids


def _events(cur, contact_id, etype) -> list[dict]:
    cur.execute(
        "select payload from events where contact_id = %s and type = %s "
        "order by occurred_at, id",
        (contact_id, etype),
    )
    return [r[0] for r in cur.fetchall()]


def _tombstones(cur, **where) -> list[tuple]:
    key, value = next(iter(where.items()))
    cur.execute(
        f"select phone_e164, list_key, channel, reason from suppression_tombstones "  # noqa: S608
        f"where {key} = %s order by channel",
        (value,),
    )
    return cur.fetchall()


def _assign(cur, contact_id, partner_id) -> None:
    """Construct an assignment via Phase 1's set_owner — the verbs are Phase 4."""
    set_owner(
        cur,
        contact_id,
        partner_id,
        event_type="contact.assigned",
        reason="test",
        actor="young",
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )


def _john(cur) -> UUID:
    cur.execute("select id from partners where name = 'John'")
    row = cur.fetchone()
    assert row is not None
    return row[0]


# ----------------------------------------------------------------------------------
# S-6 matrix row 1 — do_not_mail (mail, human, permanent)
# ----------------------------------------------------------------------------------


def test_mail_suppression_sets_flag_emits_and_writes_tombstone(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550001", list_key="cslb-M1")
    owner_conn.commit()

    suppress(contact_id, "mail", "asked via postcard reply")

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["do_not_mail"] is True
        assert flags["do_not_text"] is False and flags["do_not_call"] is False
        suppressed = _events(cur, contact_id, "contact.suppressed")
        assert len(suppressed) == 1 and suppressed[0]["channel"] == "mail"
        assert _events(cur, contact_id, "contact.opt_out") == []
        stones = _tombstones(cur, phone_e164="+18185550001")
        assert [(s[2]) for s in stones] == ["mail"]
        assert stones[0][1] == "cslb-M1"  # list_key rides the tombstone


def test_mail_suppression_gates_the_wave_audience(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550002")
    owner_conn.commit()
    suppress(contact_id, "mail", "asked")
    with owner_conn.cursor() as cur:
        assert contact_id not in _audience(cur)


def test_mail_suppression_is_not_clearable(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550003")
    owner_conn.commit()
    suppress(contact_id, "mail", "asked")
    with pytest.raises(ValidationError):
        clear_suppression(contact_id, "mail")


# ----------------------------------------------------------------------------------
# S-6 matrix row 2 — do_not_text (sms, caller STOP, permanent)
# ----------------------------------------------------------------------------------


def test_sms_suppression_sets_flag_and_leaves_mail_alone(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550004")
    owner_conn.commit()

    suppress(contact_id, "sms", "STOP")

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["do_not_text"] is True and flags["do_not_mail"] is False
        # The sms gate's reader is Phase 4's export; the column being set is the gate.
        assert contact_id in _audience(cur)  # sms never gates mail


def test_sms_suppression_is_not_clearable(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550005")
    owner_conn.commit()
    suppress(contact_id, "sms", "STOP")
    with pytest.raises(ValidationError):
        clear_suppression(contact_id, "sms")


# ----------------------------------------------------------------------------------
# S-6 matrix row 3 — do_not_call (voice, human, permanent) — the entity-specific list
# ----------------------------------------------------------------------------------


def test_voice_suppression_sets_flag_and_stays_in_the_mail_audience(clean_db, owner_conn):
    """S-6's cheapest-wrong-edit, asserted directly: a contractor who says 'stop
    calling' keeps receiving postcards."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550006")
    owner_conn.commit()

    suppress(contact_id, "voice", "asked John to stop calling")

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["do_not_call"] is True and flags["do_not_mail"] is False
        assert contact_id in _audience(cur)
        suppressed = _events(cur, contact_id, "contact.suppressed")
        assert len(suppressed) == 1 and suppressed[0]["channel"] == "voice"


def test_voice_suppression_on_an_assigned_contact_ends_the_assignment(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550007")
        _assign(cur, contact_id, _john(cur))
    owner_conn.commit()

    suppress(contact_id, "voice", "asked")

    with owner_conn.cursor() as cur:
        cur.execute("select owner_id from contacts where id = %s", (contact_id,))
        row = cur.fetchone()
        assert row is not None and row[0] == HOUSE_PARTNER_ID
        reclaims = _events(cur, contact_id, "contact.reclaimed")
        assert len(reclaims) == 1 and reclaims[0]["reason"] == "do_not_call"


def test_voice_suppression_is_not_clearable(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550008")
    owner_conn.commit()
    suppress(contact_id, "voice", "asked")
    with pytest.raises(ValidationError):
        clear_suppression(contact_id, "voice")


# ----------------------------------------------------------------------------------
# S-6 matrix row 4 — dnc_registry (voice, external scrub, CLEARABLE)
# ----------------------------------------------------------------------------------


def _subscribe(cur, *codes: str) -> None:
    for code in codes:
        cur.execute(
            "insert into dnc_subscriptions (area_code, subscribed_at) "
            "values (%s, now()) on conflict do nothing",
            (code,),
        )


def test_registry_hit_sets_flag_stamps_and_stays_mailable(clean_db, owner_conn):
    from jobs.dnc_refresh import dnc_refresh

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
        _subscribe(cur, "818")
    owner_conn.commit()

    registry = FakeDncRegistry(version="v1", numbers={"818": {"8185550009"}})
    report = dnc_refresh(registry)
    assert report.checked >= 1 and report.hits == 1

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["dnc_registry"] is True
        cur.execute("select dnc_checked_at from contacts where id = %s", (contact_id,))
        row = cur.fetchone()
        assert row is not None and row[0] is not None
        checked = _events(cur, contact_id, "contact.dnc_checked")
        assert len(checked) == 1 and checked[0]["registry_version"] == "v1"
        assert contact_id in _audience(cur)  # registry-listed is still mailable


def test_registry_hit_on_an_assigned_contact_ends_the_assignment(clean_db, owner_conn):
    from jobs.dnc_refresh import dnc_refresh

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550010")
        _subscribe(cur, "818")
        _assign(cur, contact_id, _john(cur))
    owner_conn.commit()

    dnc_refresh(FakeDncRegistry(version="v1", numbers={"818": {"8185550010"}}))

    with owner_conn.cursor() as cur:
        cur.execute("select owner_id from contacts where id = %s", (contact_id,))
        row = cur.fetchone()
        assert row is not None and row[0] == HOUSE_PARTNER_ID
        reclaims = _events(cur, contact_id, "contact.reclaimed")
        assert len(reclaims) == 1 and reclaims[0]["reason"] == "dnc_registry"


def test_scrub_is_idempotent_on_the_registry_version(clean_db, owner_conn):
    """Same registry version twice ⇒ no duplicate events (external_id dedupe)."""
    from jobs.dnc_refresh import dnc_refresh

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550011")
        _subscribe(cur, "818")
    owner_conn.commit()

    registry = FakeDncRegistry(version="v1", numbers={"818": {"8185550011"}})
    dnc_refresh(registry)
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_checked_at = now() - interval '30 days' "
            "where id = %s",
            (contact_id,),
        )
    owner_conn.commit()
    dnc_refresh(registry)  # stale again, same version

    with owner_conn.cursor() as cur:
        assert len(_events(cur, contact_id, "contact.dnc_checked")) == 1


def test_delisting_clears_the_registry_flag_with_an_event(clean_db, owner_conn):
    """The clear path has a writer — through the JOB, not only the verb (S-9)."""
    from jobs.dnc_refresh import dnc_refresh

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550012")
        _subscribe(cur, "818")
    owner_conn.commit()

    dnc_refresh(FakeDncRegistry(version="v1", numbers={"818": {"8185550012"}}))
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_checked_at = now() - interval '30 days' "
            "where id = %s",
            (contact_id,),
        )
    owner_conn.commit()
    dnc_refresh(FakeDncRegistry(version="v2", numbers={"818": set()}))

    with owner_conn.cursor() as cur:
        assert _flags(cur, contact_id)["dnc_registry"] is False
        cleared = _events(cur, contact_id, "contact.suppression_cleared")
        assert len(cleared) == 1 and cleared[0]["channel"] == "dnc_registry"


def test_clear_suppression_accepts_only_dnc_registry(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550013")
        cur.execute(
            "update contacts set dnc_registry = true where id = %s", (contact_id,)
        )
    owner_conn.commit()

    clear_suppression(contact_id, "dnc_registry")

    with owner_conn.cursor() as cur:
        assert _flags(cur, contact_id)["dnc_registry"] is False
        assert len(_events(cur, contact_id, "contact.suppression_cleared")) == 1


# ----------------------------------------------------------------------------------
# S-6 matrix row 5 — address_undeliverable (mail, derived, until-corrected)
# ----------------------------------------------------------------------------------


def test_two_returned_pieces_derive_address_undeliverable_not_suppressed(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550014")
    owner_conn.commit()
    ingest_event("lob", "piece.returned", AT, {}, contact_id=contact_id)
    ingest_event("lob", "piece.returned", AT + timedelta(days=3), {}, contact_id=contact_id)

    recompute_state()

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["address_undeliverable"] is True
        assert _stage(cur, contact_id) != "suppressed"  # v3: no longer a stage fact
        assert contact_id not in _audience(cur)  # but still gates mail


def test_address_undeliverable_recompute_is_deterministic(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550015")
    owner_conn.commit()
    ingest_event("lob", "piece.returned", AT, {}, contact_id=contact_id)
    ingest_event("lob", "piece.returned", AT + timedelta(days=3), {}, contact_id=contact_id)

    recompute_state()
    with owner_conn.cursor() as cur:
        first = (_flags(cur, contact_id)["address_undeliverable"], _stage(cur, contact_id))
    recompute_state()
    with owner_conn.cursor() as cur:
        second = (_flags(cur, contact_id)["address_undeliverable"], _stage(cur, contact_id))
    assert first == second == (True, first[1])


def test_address_undeliverable_is_not_clearable_by_the_verb(clean_db, owner_conn):
    """The clear path is an address change, not an eraser — and none ships yet."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550016")
        cur.execute(
            "update contacts set address_undeliverable = true where id = %s",
            (contact_id,),
        )
    owner_conn.commit()
    with pytest.raises(ValidationError):
        clear_suppression(contact_id, "address_undeliverable")


# ----------------------------------------------------------------------------------
# The all-channel case — opt_out
# ----------------------------------------------------------------------------------


def test_opt_out_sets_all_three_flags_and_writes_three_tombstones(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550017")
        _assign(cur, contact_id, _john(cur))
    owner_conn.commit()

    suppress(contact_id, "all", "asked to be left alone entirely")

    with owner_conn.cursor() as cur:
        flags = _flags(cur, contact_id)
        assert flags["do_not_mail"] and flags["do_not_text"] and flags["do_not_call"]
        opt_outs = _events(cur, contact_id, "contact.opt_out")
        assert len(opt_outs) == 1
        assert opt_outs[0]["reason"] != "do_not_mail"
        stones = _tombstones(cur, phone_e164="+18185550017")
        assert [s[2] for s in stones] == ["mail", "sms", "voice"]
        # all-channel blocks voice, so the assignment ends too
        cur.execute("select owner_id from contacts where id = %s", (contact_id,))
        row = cur.fetchone()
        assert row is not None and row[0] == HOUSE_PARTNER_ID
        assert contact_id not in _audience(cur)


def test_opt_out_rejects_the_reason_that_would_rearm_the_trap(clean_db, owner_conn):
    """channel='all' with reason='do_not_mail' would make the new event derive
    mail-only under v3 — the exact ambiguity the split exists to end."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550018")
    owner_conn.commit()
    with pytest.raises(ValidationError):
        suppress(contact_id, "all", "do_not_mail")


def test_suppress_rejects_unknown_channels(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550019")
    owner_conn.commit()
    with pytest.raises(ValidationError):
        suppress(contact_id, "carrier_pigeon", "no")


# ----------------------------------------------------------------------------------
# The historical-event trap (v3 derivation reads payload.reason)
# ----------------------------------------------------------------------------------


def test_historical_do_not_mail_opt_out_derives_mail_only(clean_db, owner_conn):
    """A day-one `contact.opt_out {reason: do_not_mail}` (the old collapsed shape)
    must NOT keep the contact fully SUPPRESSED under v3 — flag gates mail, stage
    frees the phone."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550020", do_not_mail=True)
    owner_conn.commit()
    ingest_event(
        "human", "contact.opt_out", AT, {"reason": "do_not_mail"}, contact_id=contact_id
    )

    recompute_state()

    with owner_conn.cursor() as cur:
        assert _stage(cur, contact_id) != "suppressed"
        assert contact_id not in _audience(cur)  # the flag still gates mail


def test_historical_real_opt_out_still_derives_suppressed(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550021", do_not_mail=True)
    owner_conn.commit()
    ingest_event(
        "human", "contact.opt_out", AT, {"reason": "opt_out"}, contact_id=contact_id
    )
    recompute_state()
    with owner_conn.cursor() as cur:
        assert _stage(cur, contact_id) == "suppressed"


# ----------------------------------------------------------------------------------
# The event-only backstop and the record_note restriction
# ----------------------------------------------------------------------------------


def test_an_event_only_opt_out_is_excluded_from_every_wave_audience(
    clean_db, owner_conn
):
    """Fixture bypasses suppress(): the event lands with no column writes. The stage
    clause is the belt-and-suspenders that still excludes the contact."""
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550022")
    owner_conn.commit()
    ingest_event(
        "human", "contact.opt_out", AT, {"reason": "phone"}, contact_id=contact_id
    )
    recompute_state()
    with owner_conn.cursor() as cur:
        assert _flags(cur, contact_id)["do_not_mail"] is False  # no column write
        assert contact_id not in _audience(cur)


def test_record_note_accepts_only_note_types(clean_db, owner_conn):
    from service.ingestion import record_note

    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550023")
    owner_conn.commit()

    record_note(contact_id, "note.general", "fine")  # note.* still works
    with pytest.raises(ValidationError):
        record_note(contact_id, "contact.opt_out", "sneaky opt-out as a note")


def test_note_web_routes_reject_non_note_types(clean_db, owner_conn):
    from fastapi.testclient import TestClient

    from web.api import app

    client = TestClient(app, raise_server_exceptions=False)
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550024")
    owner_conn.commit()

    api = client.post(
        f"/api/contacts/{contact_id}/note",
        json={"note_type": "contact.opt_out", "text": "x"},
    )
    assert api.status_code == 409  # the app-wide ValidationError status
    ui = client.post(
        f"/contacts/{contact_id}/note",
        data={"note_type": "contact.opt_out", "text": "x"},
        follow_redirects=False,
    )
    assert ui.status_code == 409


# ----------------------------------------------------------------------------------
# Tombstones survive deletion and re-ingest
# ----------------------------------------------------------------------------------

_CSV_HEADER = (
    "list_key,business_name,contact_name,trade,trades,license_class,phone,email,"
    "addr_line1,addr_line2,addr_city,addr_state,addr_zip,segment,do_not_mail\n"
)


def _write_csv(path, rows: list[str]) -> str:
    path.write_text(_CSV_HEADER + "".join(rows))
    return str(path)


def test_reingest_after_hard_delete_reacquires_suppression(
    clean_db, owner_conn, tmp_path
):
    """FR-8's hard-delete removes the row; the tombstone is the only thing a
    re-ingest of the same phone or list row runs into."""
    path = _write_csv(
        tmp_path / "first.csv",
        ["cslb-T1,Tomb Co,,plumber,plumber,C36,818-555-0025,,1 A St,,LA,CA,90001,,\n"],
    )
    load_list(path, source="cslb-ca")
    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where phone_e164 = '+18185550025'")
        row = cur.fetchone()
        assert row is not None
        contact_id = row[0]
    owner_conn.commit()

    suppress(contact_id, "all", "lose my number")

    # FR-8-style hard delete (unbuilt as a verb; simulated as the fixture)
    with owner_conn.cursor() as cur:
        cur.execute("delete from events where contact_id = %s", (contact_id,))
        cur.execute(
            "delete from intake_cslb_ca where contact_id = %s", (contact_id,)
        )
        cur.execute("delete from contacts where id = %s", (contact_id,))
    owner_conn.commit()

    path2 = _write_csv(
        tmp_path / "second.csv",
        ["cslb-T2,Tomb Co,,plumber,plumber,C36,818-555-0025,,1 A St,,LA,CA,90001,,\n"],
    )
    load_list(path2, source="cslb-ca")

    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where phone_e164 = '+18185550025'")
        row = cur.fetchone()
        assert row is not None
        flags = _flags(cur, row[0])
    assert flags["do_not_mail"] and flags["do_not_text"] and flags["do_not_call"]


def test_load_list_emits_suppressed_per_do_not_mail_csv_row(
    clean_db, owner_conn, tmp_path
):
    path = _write_csv(
        tmp_path / "dnm.csv",
        ["cslb-T3,Quiet Co,,plumber,plumber,C36,818-555-0026,,2 B St,,LA,CA,90001,,true\n"],
    )
    load_list(path, source="cslb-ca")

    with owner_conn.cursor() as cur:
        cur.execute("select id, do_not_mail from contacts where phone_e164 = '+18185550026'")
        row = cur.fetchone()
        assert row is not None and row[1] is True
        suppressed = _events(cur, row[0], "contact.suppressed")
        assert len(suppressed) == 1
        assert suppressed[0]["channel"] == "mail"
        assert suppressed[0]["source"] == "intake"


# ----------------------------------------------------------------------------------
# The before/after report exists
# ----------------------------------------------------------------------------------


def test_suppression_report_covers_causes_and_predictions(clean_db, owner_conn):
    from jobs.suppression_report import build_report

    with owner_conn.cursor() as cur:
        # one of each cause: real opt-out, historical do-not-mail opt-out, returned
        # mail — all staged 'suppressed', the v2 stamp the report inventories (the
        # production shape after deploy, before the first v3 recompute)
        a = new_contact(cur, phone_e164="+18185550027", stage_snapshot="suppressed")
        b = new_contact(
            cur, phone_e164="+18185550028", do_not_mail=True,
            stage_snapshot="suppressed",
        )
        c = new_contact(cur, phone_e164="+18185550029", stage_snapshot="suppressed")
    owner_conn.commit()
    ingest_event("human", "contact.opt_out", AT, {"reason": "phone"}, contact_id=a)
    ingest_event("human", "contact.opt_out", AT, {"reason": "do_not_mail"}, contact_id=b)
    ingest_event("lob", "piece.returned", AT, {}, contact_id=c)
    ingest_event("lob", "piece.returned", AT + timedelta(days=1), {}, contact_id=c)

    report = build_report()

    assert report["opt_out_reasons"] == {"phone": 1, "do_not_mail": 1}
    assert report["predicted"]["stays_suppressed"] == 1
    assert report["predicted"]["moves_stage"] >= 2
