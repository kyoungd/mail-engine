"""The DNC gate measures the LIST's age, not the check's.

16 CFR 310.4(b)(3)(iv): a registry version "obtained from the Commission no more
than thirty-one (31) days prior to the date any call is made". Under Architecture B
the scrub judges each code against its newest accepted snapshot — of any age — and
stamps dnc_checked_at = now(); assignment, export and the age alert all read that
stamp. A code whose uploads stopped kept exporting on an ever-older list, and
nothing fired. The verdict's list is contacts.dnc_snapshot_id -> version_date,
the FTC's own file date.
"""

import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from config.params import DEFAULT_PARAMS, DNC_FRESHNESS_DAYS, HOUSE_PARTNER_ID
from jobs.dnc_pull import pull_snapshots
from jobs.dnc_refresh import dnc_refresh_all
from judgment.rules.dnc_version_alert import RULE as dnc_version_alert
from seams.fakes import FakeSnapshotInbox
from service.assignment import assign_batch
from tests.factories import new_contact

AS_OF = date(2026, 9, 9)


def _utc_today() -> date:
    return datetime.now(UTC).date()


def _mk_partner(cur) -> UUID:
    cur.execute(
        "insert into partners (name, status) values (%s, 'active') returning id",
        (f"ListAge-{uuid4().hex[:8]}",),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _rm_partner(owner_conn, partner_id: UUID) -> None:
    with owner_conn.cursor() as cur:
        cur.execute(
            "update contacts set owner_id = %s, assignment_batch_id = null "
            "where owner_id = %s",
            (HOUSE_PARTNER_ID, partner_id),
        )
        cur.execute("delete from assignment_batches where partner_id = %s", (partner_id,))
        cur.execute("delete from partners where id = %s", (partner_id,))
    owner_conn.commit()


def _assign(owner_conn, contact_id: UUID):
    with owner_conn.cursor() as cur:
        partner = _mk_partner(cur)
    owner_conn.commit()
    try:
        return assign_batch(
            partner, f"list-age-{uuid4().hex[:8]}", "test", contact_ids=[contact_id]
        )
    finally:
        _rm_partner(owner_conn, partner)


def _subscribe(cur, area_code: str) -> None:
    cur.execute(
        "insert into dnc_subscriptions (area_code, subscribed_at) values (%s, now()) "
        "on conflict do nothing",
        (area_code,),
    )


def _snapshot_row(cur, area_code: str, list_date: date, *, status: str = "accepted") -> UUID:
    """A ledger row with no file behind it — for readers that consult only the ledger."""
    cur.execute(
        "insert into dnc_snapshots (area_code, san_holder_id, version_date, file_guid, "
        "sha256, object_key, uploaded_at, status, reject_reason) "
        "values (%s, %s, %s, %s, %s, %s, now(), %s, %s) returning id",
        (area_code, HOUSE_PARTNER_ID, list_date, uuid4().hex, uuid4().hex,
         f"dnc/test/{uuid4().hex}", status,
         None if status == "accepted" else "short_file"),
    )
    row = cur.fetchone()
    assert row is not None
    return row[0]


def _zip_bytes(name: str, lines: list[str], tmp_path: Path) -> bytes:
    path = tmp_path / f"staging-{name}"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name.removesuffix(".zip"), "".join(f"{line}\n" for line in lines))
    data = path.read_bytes()
    path.unlink()
    return data


def _land(owner_conn, tmp_path, lists_root, *, area_code: str, list_date: date) -> None:
    """One snapshot through the REAL pull, dated `list_date` and uploaded that same day:
    record_snapshot refuses a file that reaches us days after its own date, so an old
    list is one that arrived fresh and has aged since."""
    name = (f"{list_date.year}-{list_date.month}-{list_date.day}"
            f"_{area_code}_{uuid4().hex}.txt.zip")
    key = f"dnc/{HOUSE_PARTNER_ID}/{name}"
    uploaded_at = datetime.combine(list_date, time(15), tzinfo=UTC)
    inbox = FakeSnapshotInbox()
    inbox.add(key=key, partner_id=HOUSE_PARTNER_ID,
              body=_zip_bytes(name, [f"{area_code},5550100"], tmp_path),
              uploaded_at=uploaded_at, claimed_fetched_at=uploaded_at)
    pull_snapshots(inbox, lists_root=lists_root)
    with owner_conn.cursor() as cur:
        cur.execute("select status from dnc_snapshots where object_key = %s", (key,))
        assert cur.fetchone() == ("accepted",)


# -- the gate ---------------------------------------------------------------------


def test_a_fresh_check_against_an_old_list_is_not_assignable(clean_db, owner_conn, tmp_path):
    """The reproduction, through the real pull -> scrub -> assign path."""
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _land(owner_conn, tmp_path, lists_root, area_code="818",
          list_date=_utc_today() - timedelta(days=DNC_FRESHNESS_DAYS + 9))

    scrub = dnc_refresh_all(lists_root=lists_root)
    assert (scrub.checked, scrub.hits) == (1, 0)

    report = _assign(owner_conn, contact_id)
    assert report.assigned == []
    assert report.shortfall == {"dnc_stale": [contact_id]}


def test_the_same_path_with_a_fresh_list_assigns(clean_db, owner_conn, tmp_path):
    """The control: the reproduction refuses because of the list's age, not the path."""
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _land(owner_conn, tmp_path, lists_root, area_code="818", list_date=_utc_today())

    dnc_refresh_all(lists_root=lists_root)

    assert _assign(owner_conn, contact_id).assigned == [contact_id]


@pytest.mark.parametrize("pgtz", ["Pacific/Kiritimati", "Pacific/Pago_Pago"])
@pytest.mark.parametrize(
    ("age", "assignable"), [(DNC_FRESHNESS_DAYS, True), (DNC_FRESHNESS_DAYS + 1, False)]
)
def test_the_wall_is_31_days_on_the_utc_date_whatever_the_session_zone(
    clean_db, owner_conn, monkeypatch, pgtz, age, assignable
):
    """"No more than 31 days": a 31-day-old list passes, 32 does not, counted on the
    UTC date — ahead of every US zone, so any error is strict. UTC+14 and UTC-11 are
    never both on the UTC date, so a session-local `current_date` fails one of these
    cases at any hour of the day."""
    monkeypatch.setenv("PGTZ", pgtz)
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        contact_id = new_contact(
            cur, phone_e164="+18185550009", dnc_checked_at=datetime.now(UTC),
            dnc_snapshot_id=_snapshot_row(cur, "818", _utc_today() - timedelta(days=age)),
        )
    owner_conn.commit()

    report = _assign(owner_conn, contact_id)

    if assignable:
        assert report.assigned == [contact_id]
    else:
        assert report.assigned == [] and report.shortfall == {"dnc_stale": [contact_id]}


# -- the alert --------------------------------------------------------------------


def _evaluate(readonly_url):
    with psycopg.connect(readonly_url) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            return dnc_version_alert.evaluate(cur, DEFAULT_PARAMS, AS_OF)


def _checked(cur, phone: str, days_ago: int) -> None:
    new_contact(cur, phone_e164=phone, dnc_checked_at=datetime.combine(
        AS_OF - timedelta(days=days_ago), time(12), tzinfo=UTC))


def test_alert_fires_when_the_newest_list_is_old_though_checks_are_fresh(
    clean_db, owner_conn, readonly_url
):
    """Uploads stopped, scrub still running — the case a check-age alert cannot see."""
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        _checked(cur, "+18185550009", days_ago=1)
        _snapshot_row(cur, "818", AS_OF - timedelta(days=25))
    owner_conn.commit()

    hits = _evaluate(readonly_url)

    assert len(hits) == 1
    assert hits[0].facts["stale"] == [{"area_code": "818", "age_days": 25}]


def test_only_the_newest_accepted_list_counts(clean_db, owner_conn, readonly_url):
    """A superseded old list is no alarm; a fresh REJECTED file must not make an old
    accepted one look current."""
    with owner_conn.cursor() as cur:
        _subscribe(cur, "818")
        _subscribe(cur, "714")
        _checked(cur, "+18185550009", days_ago=1)
        _checked(cur, "+17145550009", days_ago=1)
        _snapshot_row(cur, "818", AS_OF - timedelta(days=25))
        _snapshot_row(cur, "818", AS_OF - timedelta(days=2))
        _snapshot_row(cur, "714", AS_OF - timedelta(days=25))
        _snapshot_row(cur, "714", AS_OF - timedelta(days=1), status="rejected")
    owner_conn.commit()

    hits = _evaluate(readonly_url)

    assert len(hits) == 1
    assert hits[0].facts["stale"] == [{"area_code": "714", "age_days": 25}]
