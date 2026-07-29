"""Phase 3 frozen acceptance tests — the verification job (design §10 test 7, §5).

Two phases, and the whole design rests on the distinction between them:

  STAMP    a vendor VERDICT is a result — including undeliverable and no-delivery-point.
           Stamp `std_verified_at`, store the verdict verbatim, never call again. A
           vendor ERROR stamps nothing and the next run retries it.
  INHERIT  only a deliverable-family verdict WITH usable components and a delivery point
           puts the standardized address onto the contact. Anything else leaves the raw
           picked address alone, because the raw address is the better fact when
           standardization failed — and the null `addr_validated_at` guard must only ever
           lock in a real standardized address or a human edit, never a clobber.
"""

from datetime import UTC, datetime, timedelta
from typing import Any


from seams.address_verifier import AddressVerificationError
from jobs.verify_addresses import verify_addresses
from seams.fakes import FakeVerifier
from service.contacts import update_contact_address
from tests.factories import add_intake_row, new_contact

RAW: dict[str, Any] = {
    "addr_line1": "200 n spring st",
    "addr_line2": "ste 4",
    "addr_city": "los angeles",
    "addr_state": "ca",
    "addr_zip": "90012",
}


def _contact_with_primary(cur, **over):
    fields = {**RAW, **over}
    contact_id = new_contact(cur, intake=False, segment="plumber-CA", **fields)
    add_intake_row(cur, contact_id, is_primary=True, **fields)
    return contact_id


def _intake(conn, contact_id):
    with conn.cursor() as cur:
        cur.execute(
            "select deliverability, delivery_point, std_addr_line1, std_addr_city, "
            "std_addr_zip, std_verified_at from intake_cslb_ca where contact_id = %s",
            (contact_id,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(
            zip(
                ["deliverability", "delivery_point", "line1", "city", "zip", "verified_at"],
                row,
                strict=True,
            )
        )


def _contact(conn, contact_id):
    with conn.cursor() as cur:
        cur.execute(
            "select addr_line1, addr_city, addr_zip, addr_validated_at "
            "from contacts where id = %s",
            (contact_id,),
        )
        row = cur.fetchone()
        assert row is not None
        return dict(zip(["line1", "city", "zip", "validated_at"], row, strict=True))


# --- stamp phase ----------------------------------------------------------------


def test_a_deliverable_verdict_is_stamped_and_stored_verbatim(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    report = verify_addresses(FakeVerifier())

    row = _intake(owner_conn, contact_id)
    assert row["deliverability"] == "deliverable"
    assert row["delivery_point"] == "01234567890"
    assert row["verified_at"] is not None
    assert report.stamped == 1


def test_an_undeliverable_verdict_is_a_result_and_is_stamped(clean_db, owner_conn):
    """Stamping undeliverable is the point: it is a verdict, not a failure, so the
    vendor is never asked about this row again."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    verify_addresses(FakeVerifier(deliverability="undeliverable"))

    row = _intake(owner_conn, contact_id)
    assert row["deliverability"] == "undeliverable"
    assert row["verified_at"] is not None


def test_a_no_delivery_point_verdict_is_stamped_too(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    verify_addresses(FakeVerifier(delivery_point=""))

    row = _intake(owner_conn, contact_id)
    assert row["verified_at"] is not None
    assert row["delivery_point"] == ""


def test_a_stamped_row_is_never_re_called(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        _contact_with_primary(cur)
    owner_conn.commit()
    verify_addresses(FakeVerifier())

    second = FakeVerifier()
    report = verify_addresses(second)

    assert second.calls == []  # the snapshot is what keeps resolution reproducible
    assert report.stamped == 0


def test_a_vendor_error_stamps_nothing_and_the_next_run_retries(clean_db, owner_conn):
    """No per-call retry loop inside a run, and no permanent consumption of the 'once'
    by a transient failure."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    report = verify_addresses(FakeVerifier(fail=True))

    assert report.errored == 1
    assert report.stamped == 0
    row = _intake(owner_conn, contact_id)
    assert row["verified_at"] is None
    assert row["deliverability"] is None

    retry = FakeVerifier()
    verify_addresses(retry)

    assert len(retry.calls) == 1  # still unverified, so still swept
    assert _intake(owner_conn, contact_id)["verified_at"] is not None


def test_one_row_erroring_does_not_stop_the_sweep(clean_db, owner_conn):
    """A row that errors forever stays visible as ever-unverified; it must not hold up
    every other row behind it."""

    class OneBadAddress(FakeVerifier):
        def verify(self, address):
            if (address.get("addr_line1") or "").startswith("999"):
                raise AddressVerificationError("vendor blew up on this one")
            return super().verify(address)

    with owner_conn.cursor() as cur:
        bad = _contact_with_primary(cur, addr_line1="999 broken st")
        good = _contact_with_primary(cur, addr_line1="1 fine ave")
    owner_conn.commit()

    report = verify_addresses(OneBadAddress())

    assert (report.stamped, report.errored) == (1, 1)
    assert _intake(owner_conn, bad)["verified_at"] is None
    assert _intake(owner_conn, good)["verified_at"] is not None


def test_the_sweep_is_a_no_op_when_nothing_is_unverified(clean_db, owner_conn):
    verifier = FakeVerifier()

    report = verify_addresses(verifier)

    assert verifier.calls == []
    assert (report.stamped, report.errored, report.inherited) == (0, 0, 0)


def test_both_intake_tables_are_swept(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cslb = _contact_with_primary(cur)
        fbn = new_contact(cur, intake=False, segment="fbn-ca-2026", **RAW)
        add_intake_row(cur, fbn, table="intake_fbn_ca", is_primary=True, **RAW)
    owner_conn.commit()

    report = verify_addresses(FakeVerifier())

    assert report.stamped == 2
    assert _intake(owner_conn, cslb)["verified_at"] is not None
    with owner_conn.cursor() as cur:
        cur.execute(
            "select std_verified_at from intake_fbn_ca where contact_id = %s", (fbn,)
        )
        assert cur.fetchone()[0] is not None


# --- inherit phase --------------------------------------------------------------


def test_deliverable_with_components_puts_the_standardized_address_on_the_contact(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    report = verify_addresses(FakeVerifier())

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "200 N SPRING ST"  # the fake standardizes by upcasing
    assert contact["city"] == "LOS ANGELES"
    assert contact["validated_at"] is not None
    assert report.inherited == 1


def test_an_undeliverable_verdict_leaves_the_raw_address_and_a_null_guard(
    clean_db, owner_conn
):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    report = verify_addresses(FakeVerifier(deliverability="undeliverable"))

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "200 n spring st"  # untouched
    assert contact["validated_at"] is None  # never guard-locked
    assert report.inherited == 0


def test_a_no_delivery_point_verdict_does_not_inherit(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    verify_addresses(FakeVerifier(delivery_point=""))

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "200 n spring st"
    assert contact["validated_at"] is None


def test_missing_components_do_not_inherit(clean_db, owner_conn):
    """The raw address is the better fact when standardization returned nothing usable."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    verify_addresses(FakeVerifier(components=False))

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "200 n spring st"
    assert contact["validated_at"] is None


def test_a_re_run_is_a_no_op(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()
    verify_addresses(FakeVerifier())
    first = _contact(owner_conn, contact_id)

    report = verify_addresses(FakeVerifier())

    assert _contact(owner_conn, contact_id) == first
    assert report.inherited == 0


def test_an_operator_edited_address_is_never_overwritten(clean_db, owner_conn):
    """`update_contact_address` stamps `addr_validated_at`; that stamp is what makes the
    inherit guard safe. Enforced by code, not convention."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()
    update_contact_address(
        contact_id, "1 Operator Way", None, "Sacramento", "CA", "95814"
    )

    report = verify_addresses(FakeVerifier())

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "1 Operator Way"
    assert contact["city"] == "Sacramento"
    assert report.inherited == 0


def test_only_the_primary_row_is_inherited_from(clean_db, owner_conn):
    """A contact's mailing address comes from the row that was actually picked; other
    licence records for the same business are not other addresses to choose between."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
        add_intake_row(
            cur, contact_id, is_primary=False,
            addr_line1="999 secondary st", addr_city="oakland",
            addr_state="ca", addr_zip="94612",
        )
    owner_conn.commit()

    verify_addresses(FakeVerifier())

    assert _contact(owner_conn, contact_id)["line1"] == "200 N SPRING ST"


def test_a_contact_whose_primary_row_errored_is_not_inherited_yet(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
    owner_conn.commit()

    verify_addresses(FakeVerifier(fail=True))

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "200 n spring st"
    assert contact["validated_at"] is None


def test_inherit_catches_up_a_contact_stamped_by_an_earlier_run(clean_db, owner_conn):
    """The two phases are not required to happen in the same run: a row stamped when the
    contact already had a guard, or a run that died between phases, is picked up next
    time. The null guard is the only thing gating it."""
    with owner_conn.cursor() as cur:
        contact_id = _contact_with_primary(cur)
        # a row already stamped by a prior run, with the contact never inherited
        add_intake_row(
            cur, contact_id, is_primary=False, list_key="cslb-prior",
            addr_line1="x", addr_city="y", addr_state="ca", addr_zip="1",
        )
        cur.execute(
            "update intake_cslb_ca set std_verified_at = %s, deliverability = 'deliverable', "
            "delivery_point = '01234567890', std_addr_line1 = 'PRIOR RUN ST', "
            "std_addr_city = 'LOS ANGELES', std_addr_state = 'CA', std_addr_zip = '90012-1234' "
            "where contact_id = %s and is_primary",
            (datetime.now(UTC) - timedelta(days=1), contact_id),
        )
    owner_conn.commit()

    report = verify_addresses(FakeVerifier())

    contact = _contact(owner_conn, contact_id)
    assert contact["line1"] == "PRIOR RUN ST"
    assert contact["validated_at"] is not None
    assert report.inherited == 1


def test_the_deliverable_unit_variants_still_inherit(clean_db, owner_conn):
    """Operator-approved 2026-07-29. §5 says the inherit runs over "deliverable"
    outcomes and names the blocked ones — undeliverable, no delivery point, missing
    components — without placing the three `deliverable_*_unit` variants. They are
    deliverable-FAMILY per §6 (CSLB unit data is spotty, and dropping them costs real
    reach for no deliverability gain), so they inherit like any other deliverable row.
    Pinned here because the looser reading is a choice, not a reading of silence."""
    for verdict in (
        "deliverable_missing_unit",
        "deliverable_incorrect_unit",
        "deliverable_unnecessary_unit",
    ):
        with owner_conn.cursor() as cur:
            cur.execute(
                "truncate contacts, intake_cslb_ca, intake_fbn_ca restart identity cascade"
            )
            contact_id = _contact_with_primary(cur)
        owner_conn.commit()

        report = verify_addresses(FakeVerifier(deliverability=verdict))

        contact = _contact(owner_conn, contact_id)
        assert contact["line1"] == "200 N SPRING ST", verdict
        assert contact["validated_at"] is not None, verdict
        assert report.inherited == 1, verdict
