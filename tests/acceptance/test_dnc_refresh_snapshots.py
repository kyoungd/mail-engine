"""Phase 4 gate: the scrub resolves a snapshot PER AREA CODE and names it in the
audit trail.

`dnc_refresh(registry)` — the single-registry primitive the frozen S-9 suite pins —
is untouched. `dnc_refresh_all()` is the hybrid path: NMC's own SAN and any partner
SANs cover an overlapping set of codes, so which file judged a number is no longer
implied by the date alone.
"""

import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID


from config.params import HOUSE_PARTNER_ID
from jobs.dnc_pull import pull_snapshots
from jobs.dnc_refresh import dnc_refresh_all
from seams.fakes import FakeSnapshotInbox
from tests.factories import new_contact

NOW = datetime(2026, 9, 9, 17, 0, tzinfo=UTC)


def _partner(conn, name: str) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            "insert into partners (name, status) values (%s, 'active') "
            "on conflict (name) do update set status = 'active' returning id",
            (name,),
        )
        row = cur.fetchone()
        assert row is not None
    conn.commit()
    return row[0]


def _subscribe(conn, area_code: str, holder: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "insert into dnc_subscriptions (area_code, san_holder_id, subscribed_at) "
            "values (%s, %s, now()) on conflict do nothing",
            (area_code, holder),
        )
    conn.commit()


def _zip_bytes(name: str, lines: list[str], tmp_path: Path) -> bytes:
    path = tmp_path / f"staging-{name}"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(name.removesuffix(".zip"), "".join(f"{line}\n" for line in lines))
    data = path.read_bytes()
    path.unlink()
    return data


def _land(tmp_path, lists_root, *, holder: UUID, area_code: str, listed: list[str],
          version="2026-9-9", guid="aaa", uploaded_at=NOW):
    """Put one accepted snapshot on disk and in the ledger, the way dnc_pull does."""
    name = f"{version}_{area_code}_{guid}.txt.zip"
    inbox = FakeSnapshotInbox()
    inbox.add(
        key=f"dnc/{holder}/{name}",
        partner_id=holder,
        body=_zip_bytes(name, [f"{area_code},{n[3:]}" for n in listed], tmp_path),
        uploaded_at=uploaded_at,
        claimed_fetched_at=uploaded_at,
    )
    return pull_snapshots(inbox, lists_root=lists_root)


def _events(conn, contact_id: UUID) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "select external_id, payload from events where contact_id = %s "
            "and type = 'contact.dnc_checked' order by id",
            (contact_id,),
        )
        return cur.fetchall()


def _age_check(conn, contact_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "update contacts set dnc_checked_at = now() - interval '60 days' "
            "where id = %s",
            (contact_id,),
        )
    conn.commit()


def test_scrubs_each_code_against_its_own_snapshot(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    partner = _partner(owner_conn, "Snapshot Partner A")
    with owner_conn.cursor() as cur:
        listed = new_contact(cur, phone_e164="+18185550009")
        clear = new_contact(cur, phone_e164="+17145550022")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _subscribe(owner_conn, "714", partner)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818",
          listed=["8185550009"])
    _land(tmp_path, lists_root, holder=partner, area_code="714", listed=[], guid="bbb")

    report = dnc_refresh_all(lists_root=lists_root)

    assert (report.checked, report.hits) == (2, 1)
    with owner_conn.cursor() as cur:
        cur.execute("select dnc_registry from contacts where id = %s", (listed,))
        assert cur.fetchone()[0] is True
        cur.execute("select dnc_registry from contacts where id = %s", (clear,))
        assert cur.fetchone()[0] is False


def test_the_check_event_names_the_snapshot(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818", listed=[])

    dnc_refresh_all(lists_root=lists_root)

    with owner_conn.cursor() as cur:
        cur.execute("select id from dnc_snapshots where status = 'accepted'")
        snapshot_id = cur.fetchone()[0]
        cur.execute("select dnc_snapshot_id from contacts where id = %s", (contact_id,))
        assert cur.fetchone()[0] == snapshot_id

    (external_id, payload), = _events(owner_conn, contact_id)
    assert external_id == f"dnc:{contact_id}:snap:{snapshot_id}"
    assert payload["snapshot_id"] == str(snapshot_id)
    assert payload["san_holder"] == str(HOUSE_PARTNER_ID)
    assert payload["registry_version"] == "2026-09-09"


def test_same_dated_snapshots_from_two_holders_each_record_their_own_check(
    clean_db, owner_conn, tmp_path
):
    """The silent-collision regression. A date-keyed external_id made the second
    holder's check vanish into ON CONFLICT DO NOTHING while the verdict still
    landed — a number carrying a result with no evidence behind it."""
    lists_root = tmp_path / "lists"
    partner = _partner(owner_conn, "Snapshot Partner B")
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818", listed=[])
    dnc_refresh_all(lists_root=lists_root)

    _age_check(owner_conn, contact_id)
    _land(tmp_path, lists_root, holder=partner, area_code="818", listed=[], guid="bbb")
    dnc_refresh_all(lists_root=lists_root)

    events = _events(owner_conn, contact_id)
    assert len(events) == 2
    assert events[0][0] != events[1][0]
    assert events[0][1]["snapshot_id"] != events[1][1]["snapshot_id"]


def test_uses_the_newest_accepted_snapshot_for_a_code(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    # Both files are the same size: a near-empty successor would trip the
    # line-count floor and be REJECTED, which is a different behaviour.
    others = [f"81855501{n:02d}" for n in range(9)]
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818",
          listed=["8185550009", *others], version="2026-9-8", guid="old",
          uploaded_at=NOW - timedelta(days=1))
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818",
          listed=[*others, "8185550111"], version="2026-9-9", guid="new")

    dnc_refresh_all(lists_root=lists_root)

    with owner_conn.cursor() as cur:
        cur.execute("select dnc_registry from contacts where id = %s", (contact_id,))
        assert cur.fetchone()[0] is False  # the NEWER file delists the number


def test_a_rejected_snapshot_is_never_selected(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    inbox = FakeSnapshotInbox()
    inbox.add(key=f"dnc/{HOUSE_PARTNER_ID}/garbage.zip", partner_id=HOUSE_PARTNER_ID,
              body=_zip_bytes("garbage.zip", ["818,5550009"], tmp_path),
              uploaded_at=NOW, claimed_fetched_at=NOW)
    pull_snapshots(inbox, lists_root=lists_root)

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 0
    assert ("818", "no_snapshot") in report.skips


def test_checks_written_is_stamped_on_the_snapshot_used(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        new_contact(cur, phone_e164="+18185550009")
        new_contact(cur, phone_e164="+18185550010")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818", listed=[])

    dnc_refresh_all(lists_root=lists_root)

    with owner_conn.cursor() as cur:
        cur.execute("select checks_written from dnc_snapshots where status = 'accepted'")
        assert cur.fetchone()[0] == 2


def test_a_code_whose_working_copy_is_missing_is_skipped(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818", listed=[])
    for zip_file in lists_root.rglob("*.zip"):
        zip_file.unlink()

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 0
    assert ("818", "working_copy_missing") in report.skips
    with owner_conn.cursor() as cur:
        cur.execute("select dnc_checked_at from contacts where id = %s", (contact_id,))
        assert cur.fetchone()[0] is None  # never scrubbed against nothing


def test_a_code_with_no_accepted_snapshot_is_skipped(clean_db, owner_conn, tmp_path):
    lists_root = tmp_path / "lists"
    with owner_conn.cursor() as cur:
        new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 0
    assert ("818", "no_snapshot") in report.skips


def test_a_code_covered_by_two_holders_is_scrubbed_once_per_run(
    clean_db, owner_conn, tmp_path
):
    """The composite PK returns 818 twice; a naive read would scrub it twice."""
    lists_root = tmp_path / "lists"
    partner = _partner(owner_conn, "Snapshot Partner C")
    with owner_conn.cursor() as cur:
        contact_id = new_contact(cur, phone_e164="+18185550009")
    owner_conn.commit()
    _subscribe(owner_conn, "818", HOUSE_PARTNER_ID)
    _subscribe(owner_conn, "818", partner)
    _land(tmp_path, lists_root, holder=HOUSE_PARTNER_ID, area_code="818", listed=[])

    report = dnc_refresh_all(lists_root=lists_root)

    assert report.checked == 1
    assert len(_events(owner_conn, contact_id)) == 1
