"""Part 3 gate: time zone (docs/contact-engine/03-time-zone.md §4, §7).

The zones a business could be in come from NANPA's area-code file and the contact's
state (their union); a zone the holding rep or an admin set replaces them. A moment is
inside calling hours only when it is inside 9 AM to 7 PM in every zone; with no zone
known the answer is None, never True.
"""

import csv
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from config.params import HOUSE_PARTNER_ID
from domain import zones as zt
from domain.errors import ValidationError
from service import zones as svc
from service.custody import set_owner
from tests.factories import new_contact

NY = "America/New_York"
CHI = "America/Chicago"
DEN = "America/Denver"
PHX = "America/Phoenix"
LA = "America/Los_Angeles"
ANC = "America/Anchorage"
ADAK = "America/Adak"
HNL = "Pacific/Honolulu"
PR = "America/Puerto_Rico"
GUAM = "Pacific/Guam"
PAGO = "Pacific/Pago_Pago"

AT = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0016.contact-zones.sql"
CA_CODES = (
    "209 213 279 310 323 341 350 357 369 408 415 424 442 510 530 559 562 619 626 628 650 "
    "657 661 669 707 714 738 747 760 805 818 820 831 837 840 858 909 916 925 949 951"
).split()


def utc(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# --- the zone table: the real file ---------------------------------------------------


def test_the_file_reads_378_codes_and_california_is_los_angeles():
    assert len(zt.TABLE.codes) == 378
    assert len(CA_CODES) == 41
    for code in CA_CODES:
        assert zt.TABLE.area(code) == {LA}, code


@pytest.mark.parametrize(
    ("code", "zones"),
    [
        ("212", {NY}),
        ("312", {CHI}),
        ("303", {DEN}),
        ("818", {LA}),
        ("850", {NY, CHI}),
        ("915", {CHI, DEN}),
        ("208", {DEN, LA}),
        ("787", {PR}),
        ("907", {ANC, ADAK}),
        ("808", {HNL}),
        ("671", {GUAM}),
        ("684", {PAGO}),
        ("775", {LA, DEN}),
        ("602", {PHX}),
        ("928", {PHX, DEN}),
    ],
)
def test_each_zone_value_maps_exactly(code, zones):
    assert zt.TABLE.area(code) == zones


def test_overlays_in_the_real_file_carry_their_group_s_zones():
    assert zt.TABLE.area("986") == {DEN, LA}
    assert zt.TABLE.area("930") == {NY, CHI}


def test_a_code_not_in_the_file_has_no_zone():
    assert zt.TABLE.area("800") == frozenset()
    assert zt.TABLE.area("514") == frozenset()


@pytest.mark.parametrize(
    ("state", "zones"),
    [("TX", {CHI, DEN}), ("AZ", {PHX, DEN}), ("CA", {LA}), ("MP", {GUAM}), ("ZZ", set())],
)
def test_a_state_s_zones_are_its_codes_zones(state, zones):
    assert zt.TABLE.state(state) == zones


def test_every_zone_loads_and_the_migration_lists_exactly_them():
    for zone in zt.ZONES:
        ZoneInfo(zone)
    assert len(zt.ZONES) == 11
    check = MIGRATION.read_text().split("check (zone in (", 1)[1].split("))", 1)[0]
    assert set(re.findall(r"'([^']+)'", check)) == set(zt.ZONES)


# --- the zone table: synthetic files -------------------------------------------------


def _header() -> list[str]:
    with open(zt.DEFAULT_PATH, newline="") as f:
        f.readline()
        return next(csv.reader(f))


def _file(tmp_path, rows, *, first_line="File Date,09/30/2026", hand=True) -> Path:
    """A NANPA-shaped file. Each row is (NPA_ID, LOCATION, TIME_ZONE, OVERLAY_COMPLEX) or a
    dict of columns; 928 and 907 are added unless `hand` is False or the rows carry them."""
    rows = [
        dict(zip(("NPA_ID", "LOCATION", "TIME_ZONE", "OVERLAY_COMPLEX"), r, strict=True))
        if isinstance(r, tuple) else r
        for r in rows
    ]
    present = {r["NPA_ID"] for r in rows}
    if hand:
        rows += [r for r in ({"NPA_ID": "928", "LOCATION": "AZ", "TIME_ZONE": "M",
                              "OVERLAY_COMPLEX": ""},
                             {"NPA_ID": "907", "LOCATION": "AK", "TIME_ZONE": "AK",
                              "OVERLAY_COMPLEX": ""})
                 if r["NPA_ID"] not in present]
    path = tmp_path / "npa.csv"
    header = _header()
    with open(path, "w", newline="") as f:
        f.write(first_line + "\r\n")
        writer = csv.DictWriter(f, fieldnames=header, restval="")
        writer.writeheader()
        for r in rows:
            writer.writerow({"COUNTRY": "US", "USE": "G", "IN_SERVICE": "Y", **r})
    return path


def test_a_well_formed_synthetic_file_loads(tmp_path):
    table = zt.load(_file(tmp_path, [("212", "NY", "E", "")]))
    assert table.area("212") == {NY}
    assert table.area("928") == {PHX, DEN}


@pytest.mark.parametrize(
    ("rows", "kwargs"),
    [
        ([("212", "NY", "E", "")], {"first_line": "NPA_ID,type_of_code"}),
        ([("212", "NY", "Z", "")], {}),
        ([("212", "NY", "", "")], {}),
        ([("602", "AZ", "MP", "")], {}),
        ([("212", "Cal", "E", "")], {}),
        ([("212", "", "E", "")], {}),
        ([("212", "NY", "E", ""), ("212", "NY", "E", "")], {}),
        ([("212", "NY", "E", ""), ("907", "AK", "AK", "")], {"hand": False}),
    ],
    ids=["first-line", "unknown-value", "empty-value", "arizona-not-M", "bad-location",
         "empty-location", "repeated-code", "hand-addition-missing"],
)
def test_the_import_fails_loud(tmp_path, rows, kwargs):
    with pytest.raises(ValueError):
        zt.load(_file(tmp_path, rows, **kwargs))


def test_rows_the_filter_drops_are_not_read(tmp_path):
    dropped = {"NPA_ID": "613", "LOCATION": "ON", "TIME_ZONE": "CMP", "OVERLAY_COMPLEX": "",
               "COUNTRY": "CANADA"}
    blank = {"NPA_ID": "200", "LOCATION": "", "TIME_ZONE": "", "OVERLAY_COMPLEX": "",
             "COUNTRY": "", "USE": "N", "IN_SERVICE": "N"}
    table = zt.load(_file(tmp_path, [("212", "NY", "E", ""), dropped, blank]))
    assert table.area("613") == frozenset()
    assert table.area("200") == frozenset()


def test_a_code_named_only_on_another_row_joins_its_group(tmp_path):
    table = zt.load(_file(tmp_path, [("201", "NJ", "E", ""), ("202", "NJ", "C", "201/202")]))
    assert table.area("201") == {NY, CHI}


def test_a_comma_row_is_the_only_link(tmp_path):
    table = zt.load(_file(tmp_path, [
        ("301", "MD", "E", "301/302, 301/303 "),
        ("302", "MD", "E", ""),
        ("303", "MD", "C", ""),
    ]))
    assert table.area("302") == {NY, CHI}


def test_groups_join_through_a_chain_of_rows(tmp_path):
    table = zt.load(_file(tmp_path, [
        ("401", "RI", "E", "401/402"),
        ("402", "RI", "E", ""),
        ("403", "RI", "C", "402/403"),
    ]))
    assert table.area("401") == {NY, CHI}


def test_a_member_not_kept_is_ignored(tmp_path):
    table = zt.load(_file(tmp_path, [("501", "AR", "E", "501/999")]))
    assert table.area("501") == {NY}


def test_a_row_s_own_code_is_in_its_group_even_when_its_string_leaves_it_out(tmp_path):
    table = zt.load(_file(tmp_path, [
        ("601", "MS", "E", "602/603"),
        ("602", "MS", "C", ""),
        ("603", "MS", "E", ""),
    ]))
    assert table.area("601") == {NY, CHI}


def test_a_hand_addition_passes_to_its_group(tmp_path):
    table = zt.load(_file(tmp_path, [
        ("928", "AZ", "M", "928/929"),
        ("929", "AZ", "M", ""),
    ]))
    assert table.area("929") == {PHX, DEN}


# --- contacts -------------------------------------------------------------------------


@pytest.fixture()
def reps(clean_db, owner_conn):
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
        cur.execute("delete from contact_zones where rep_id = any(%s)", (made,))
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = any(%s)",
            (HOUSE_PARTNER_ID, made),
        )
        cur.execute("delete from partners where id = any(%s)", (made,))
    owner_conn.commit()


def _contact(owner_conn, phone: str | None, state: str | None) -> UUID:
    with owner_conn.cursor() as cur:
        contact = new_contact(cur, phone_e164=phone, addr_state=state)
    owner_conn.commit()
    return contact


def _hold(owner_conn, contact: UUID, rep: UUID) -> None:
    with owner_conn.cursor() as cur:
        set_owner(cur, contact, rep, event_type="contact.assigned", reason="test", actor="t")
    owner_conn.commit()


def _rows(owner_conn) -> list[tuple]:
    with owner_conn.cursor() as cur:
        cur.execute("select contact_id, zone, actor, rep_id, at from contact_zones order by seq")
        rows = cur.fetchall()
    owner_conn.commit()
    return rows


def _zones(contact: UUID) -> set[str]:
    return set(svc.calling_hours(contact, AT).zones)


@pytest.mark.parametrize(
    ("phone", "state", "zones"),
    [
        (None, None, set()),
        ("+13035550100", None, {DEN}),
        (None, "CO", {DEN}),
        ("+12145550100", "TX", {CHI, DEN}),
        ("+14805550100", "CA", {PHX, LA}),
        ("+18655550100", "TN", {NY, CHI}),
        ("+18005550100", "CA", {LA}),
        ("+18005550100", " ca ", {LA}),
        ("+18005550100", None, set()),
        (None, "CNMI", set()),
        ("+18185550100", "CA", {LA}),
    ],
)
def test_the_zones_are_the_union_of_phone_and_state(clean_db, owner_conn, phone, state, zones):
    contact = _contact(owner_conn, phone, state)
    assert _zones(contact) == zones


# --- calling hours --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (utc(2026, 1, 15, 17, 0), True),
        (utc(2026, 1, 16, 2, 59), True),
        (utc(2026, 1, 16, 3, 0), False),
        (utc(2026, 1, 15, 16, 59), False),
        (utc(2026, 7, 15, 16, 0), True),
        (utc(2026, 7, 16, 1, 59), True),
        (utc(2026, 7, 16, 2, 0), False),
        (utc(2026, 7, 15, 15, 59), False),
    ],
    ids=["winter-9:00", "winter-18:59", "winter-19:00", "winter-8:59",
         "summer-9:00", "summer-18:59", "summer-19:00", "summer-8:59"],
)
def test_the_window_edges_in_los_angeles(clean_db, owner_conn, at, inside):
    contact = _contact(owner_conn, "+18185550100", "CA")
    assert svc.calling_hours(contact, at).inside is inside


def test_local_is_each_zone_s_wall_clock(clean_db, owner_conn):
    contact = _contact(owner_conn, "+14805550100", "CA")
    hours = svc.calling_hours(contact, utc(2026, 1, 15, 16, 59))
    assert hours.local[LA].replace(tzinfo=None) == datetime(2026, 1, 15, 8, 59)
    assert hours.local[PHX].replace(tzinfo=None) == datetime(2026, 1, 15, 9, 59)
    assert set(hours.local) == {LA, PHX}


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (utc(2026, 1, 15, 16, 30), False),
        (utc(2026, 1, 16, 2, 30), False),
        (utc(2026, 1, 15, 20, 0), True),
    ],
    ids=["8:30-pacific", "6:30pm-pacific", "noon-pacific"],
)
def test_inside_only_when_inside_in_every_zone(clean_db, owner_conn, at, inside):
    contact = _contact(owner_conn, "+14805550100", "CA")
    assert svc.calling_hours(contact, at).inside is inside


def test_no_zone_known_is_none_never_true(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18005550100", None)
    hours = svc.calling_hours(contact, AT)
    assert hours.inside is None
    assert hours.zones == frozenset()
    assert hours.set_by is None


def test_zones_far_apart_are_false_not_none(clean_db, owner_conn):
    contact = _contact(owner_conn, "+16715550100", "NY")
    assert svc.calling_hours(contact, utc(2026, 1, 15, 17, 0)).inside is False


# --- a set zone -----------------------------------------------------------------------


def test_a_set_zone_replaces_the_phone_in_calling_hours(clean_db, owner_conn):
    contact = _contact(owner_conn, "+12125550100", None)
    assert svc.calling_hours(contact, utc(2026, 1, 15, 16, 30)).inside is True
    svc.set_zone(contact, LA, AT, actor="young")
    assert svc.calling_hours(contact, utc(2026, 1, 15, 16, 30)).inside is False


def test_a_set_zone_replaces_the_union_and_says_who(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+14805550100", "CA")
    _hold(owner_conn, contact, rep)
    set_at = utc(2026, 1, 10, 18, 0)
    assert svc.set_zone(contact, LA, set_at, rep=rep) == "set"
    hours = svc.calling_hours(contact, utc(2026, 1, 16, 2, 30))
    assert hours.zones == {LA}
    assert hours.inside is True
    assert hours.set_by is not None
    assert (hours.set_by.actor, hours.set_by.rep, hours.set_by.at) == (str(rep), rep, set_at)


def test_the_highest_seq_wins_not_the_latest_at(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185550100", "CA")
    svc.set_zone(contact, DEN, utc(2026, 1, 20, 12), actor="young")
    svc.set_zone(contact, LA, utc(2026, 1, 10, 12), actor="young")
    assert _zones(contact) == {LA}


# --- setting a zone -------------------------------------------------------------------


def test_setting_refusals_write_nothing(reps, owner_conn):
    rep, other = reps(), reps()
    contact = _contact(owner_conn, "+18185550100", "CA")
    _hold(owner_conn, contact, rep)
    cases = [
        ("bad_time", lambda: svc.set_zone(contact, LA, datetime(2026, 1, 15, 12), rep=rep)),
        ("bad_actor", lambda: svc.set_zone(contact, LA, AT, rep=rep, actor="young")),
        ("bad_actor", lambda: svc.set_zone(contact, LA, AT)),
        ("bad_actor", lambda: svc.set_zone(contact, LA, AT, actor="   ")),
        ("bad_zone", lambda: svc.set_zone(contact, "Mars/Base", AT, rep=rep)),
        ("no_contact", lambda: svc.set_zone(uuid4(), LA, AT, rep=rep)),
        ("bad_rep", lambda: svc.set_zone(contact, LA, AT, rep=HOUSE_PARTNER_ID)),
        ("bad_rep", lambda: svc.set_zone(contact, LA, AT, rep=uuid4())),
        ("not_yours", lambda: svc.set_zone(contact, LA, AT, rep=other)),
    ]
    for code, call in cases:
        with pytest.raises(ValidationError) as err:
            call()
        assert err.value.code == code
    assert _rows(owner_conn) == []


def test_a_rep_s_row_carries_the_rep_id_as_actor(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185550100", "CA")
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, DEN, AT, rep=rep)
    assert _rows(owner_conn) == [(contact, DEN, str(rep), rep, AT)]


def test_the_holding_rep_sets_over_the_phone_s_single_zone(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+12125550100", None)
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, LA, AT, rep=rep)
    assert _zones(contact) == {LA}


def test_the_holding_rep_sets_over_an_earlier_setting(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185550100", "CA")
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, DEN, AT, actor="young")
    svc.set_zone(contact, LA, AT, rep=rep)
    assert _zones(contact) == {LA}


def test_the_holding_rep_sets_when_none_is_known(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18005550100", None)
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, LA, AT, rep=rep)
    assert _zones(contact) == {LA}
    assert svc.calling_hours(contact, AT).inside is True


def test_an_inactive_partner_who_holds_may_set(reps, owner_conn):
    rep = reps("inactive")
    contact = _contact(owner_conn, "+18185550100", "CA")
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, DEN, AT, rep=rep)
    assert _zones(contact) == {DEN}


def test_an_admin_sets_over_a_rep_s(reps, owner_conn):
    rep = reps()
    contact = _contact(owner_conn, "+18185550100", "CA")
    _hold(owner_conn, contact, rep)
    svc.set_zone(contact, DEN, AT, rep=rep)
    svc.set_zone(contact, LA, AT, actor="young")
    hours = svc.calling_hours(contact, AT)
    assert hours.zones == {LA}
    assert hours.set_by is not None
    assert (hours.set_by.actor, hours.set_by.rep) == ("young", None)


# --- the clock and missing contacts ---------------------------------------------------


def test_calling_hours_refuses_a_naive_time_and_a_missing_contact(clean_db, owner_conn):
    contact = _contact(owner_conn, "+18185550100", "CA")
    with pytest.raises(ValidationError) as err:
        svc.calling_hours(contact, datetime(2026, 1, 15, 12))
    assert err.value.code == "bad_time"
    with pytest.raises(ValidationError) as err:
        svc.calling_hours(uuid4(), AT)
    assert err.value.code == "no_contact"
