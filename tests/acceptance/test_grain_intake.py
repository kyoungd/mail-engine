"""Phase 2 frozen acceptance tests — intake resolution (design §10 tests 1-5, 10).

Written from the design's acceptance criteria through PUBLIC VERBS ONLY. One deliberate,
pre-authorized exception is marked at its use: §10 test 4 asserts a DB constraint that no
public verb can violate by design (`load_list` attaches on a phone match and never inserts
a twin), so its fixture reaches for a raw insert to probe the unique index. That is a
fixture action, not a verb bypass, and it is the only one in this file.
"""

import csv

import psycopg
import pytest

from domain.errors import ValidationError
from service.contacts import ensure_seed_contacts, load_list, retire_seed
from service.queries import search_contacts
from service.waves import resolve_audience

FIELDS = [
    "list_key", "business_name", "contact_name", "trade", "trades", "license_class",
    "phone", "email", "addr_line1", "addr_line2", "addr_city", "addr_state",
    "addr_zip", "segment", "do_not_mail",
]

PHONE = "(818) 679-3565"
E164 = "+18186793565"


def _csv(path, rows) -> str:
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDS})
    return str(path)


def _row(list_key, **over):
    base = {
        "list_key": list_key,
        "business_name": f"Biz {list_key}",
        "trade": "plumber",
        "trades": "plumber",
        "phone": PHONE,
        "addr_line1": "1 Main St",
        "addr_city": "Van Nuys",
        "addr_state": "CA",
        "addr_zip": "91406",
    }
    base.update(over)
    return base


def _contacts_snapshot(conn):
    """Every contact field the pick rule decides, ids deliberately excluded."""
    with conn.cursor() as cur:
        cur.execute(
            "select business_name, contact_name, phone_e164, email, addr_line1, "
            "addr_line2, addr_city, addr_state, addr_zip, segment, source, do_not_mail "
            "from contacts order by business_name, phone_e164, addr_line1"
        )
        return cur.fetchall()


def _truncate(conn):
    with conn.cursor() as cur:
        cur.execute(
            "truncate activation, events, pieces, waves, variants, contacts, "
            "intake_cslb_ca, intake_fbn_ca, contact_merge_map restart identity cascade"
        )
    conn.commit()


def _count(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
        assert row is not None
        return row[0]


# --- §10 test 1: merge determinism ---------------------------------------------


def test_same_csv_into_two_fresh_databases_yields_identical_contacts(
    clean_db, tmp_path, owner_conn
):
    """Ids aside, field for field. Deliberately NOT load-twice-into-one-DB: `list_key`
    dedupe would make that comparison pass without ever exercising the pick rule, so the
    database is truncated between the two loads and each starts genuinely fresh."""
    path = _csv(
        tmp_path / "det.csv",
        [
            _row("cslb-3", addr_line1="9 Elm St", email="c@x.com"),
            _row("cslb-1", addr_line1="1 Main St"),
            _row("cslb-2", addr_line1="1 Main St", email="b@x.com"),
            _row("cslb-4", phone="", addr_line1="4 Oak Ave"),
        ],
    )

    load_list(path)
    first = _contacts_snapshot(owner_conn)

    _truncate(owner_conn)

    load_list(path)
    second = _contacts_snapshot(owner_conn)

    assert first == second
    assert len(first) == 2  # one phone group + one no-phone row


# --- §10 test 2: resolve-then-insert -------------------------------------------


def test_rows_sharing_a_phone_become_one_contact_with_every_intake_row(
    clean_db, tmp_path, owner_conn
):
    path = _csv(
        tmp_path / "group.csv",
        [_row("cslb-1"), _row("cslb-2"), _row("cslb-3")],
    )
    report = load_list(path)

    assert report.loaded == 3
    assert _count(owner_conn, "select count(*) from intake_cslb_ca") == 3
    assert _count(owner_conn, "select count(*) from contacts") == 1
    assert _count(owner_conn, "select count(*) from intake_cslb_ca where is_primary") == 1


def test_most_frequent_address_wins_the_pick(clean_db, tmp_path, owner_conn):
    path = _csv(
        tmp_path / "freq.csv",
        [
            _row("cslb-1", addr_line1="1 Rare St"),
            _row("cslb-2", addr_line1="2 Common Ave"),
            _row("cslb-3", addr_line1="2 Common Ave"),
        ],
    )
    load_list(path)

    with owner_conn.cursor() as cur:
        cur.execute("select addr_line1 from contacts")
        assert cur.fetchone() == ("2 Common Ave",)
        cur.execute("select list_key from intake_cslb_ca where is_primary")
        assert cur.fetchone() == ("cslb-2",)  # lowest list_key within the winning tuple


def test_tuple_tie_breaks_on_lowest_list_key_across_the_whole_candidate_set(
    clean_db, tmp_path, owner_conn
):
    """Two addresses tie at two rows each: the candidate set is ALL FOUR rows, and the
    winner is the lowest list_key among them — not the lowest within one tied tuple."""
    path = _csv(
        tmp_path / "tie.csv",
        [
            _row("cslb-4", addr_line1="B St"),
            _row("cslb-5", addr_line1="B St"),
            _row("cslb-6", addr_line1="A St"),
            _row("cslb-7", addr_line1="A St"),
        ],
    )
    load_list(path)

    with owner_conn.cursor() as cur:
        cur.execute("select list_key from intake_cslb_ca where is_primary")
        assert cur.fetchone() == ("cslb-4",)
        cur.execute("select addr_line1 from contacts")
        assert cur.fetchone() == ("B St",)


def test_email_coalesces_over_the_whole_group_not_just_the_candidate_set(
    clean_db, tmp_path, owner_conn
):
    """The winner has no email; the only address that does sits outside the winning
    tuple. Emails are too scarce to discard on an address-frequency technicality."""
    path = _csv(
        tmp_path / "email.csv",
        [
            _row("cslb-1", addr_line1="Common St"),
            _row("cslb-2", addr_line1="Common St"),
            _row("cslb-3", addr_line1="Rare St", email="only@x.com"),
        ],
    )
    load_list(path)

    with owner_conn.cursor() as cur:
        cur.execute("select email from contacts")
        assert cur.fetchone() == ("only@x.com",)


def test_untargetable_row_gets_no_intake_row_and_is_counted_invalid(
    clean_db, tmp_path, owner_conn
):
    path = _csv(
        tmp_path / "invalid.csv",
        [_row("cslb-1"), _row("cslb-2", trade="", trades="", segment="")],
    )
    report = load_list(path)

    assert (report.loaded, report.invalid) == (1, 1)
    assert _count(owner_conn, "select count(*) from intake_cslb_ca") == 1
    assert (
        _count(owner_conn, "select count(*) from intake_cslb_ca where list_key = 'cslb-2'")
        == 0
    )


def test_unrecognized_source_raises_before_any_row_is_read(clean_db, tmp_path, owner_conn):
    path = _csv(tmp_path / "typo.csv", [_row("cslb-1")])

    with pytest.raises(ValidationError):
        load_list(path, source="cslb-typo")

    assert _count(owner_conn, "select count(*) from contacts") == 0
    assert _count(owner_conn, "select count(*) from intake_cslb_ca") == 0


def test_re_ingesting_the_same_file_adds_nothing(clean_db, tmp_path, owner_conn):
    path = _csv(tmp_path / "again.csv", [_row("cslb-1"), _row("cslb-2")])
    load_list(path)

    second = load_list(path)

    assert (second.loaded, second.deduped) == (0, 2)
    assert _count(owner_conn, "select count(*) from intake_cslb_ca") == 2
    assert _count(owner_conn, "select count(*) from contacts") == 1


# --- §10 test 3: attach without re-pick ----------------------------------------


def test_a_later_file_attaches_on_phone_without_re_picking_contact_fields(
    clean_db, tmp_path, owner_conn
):
    load_list(_csv(tmp_path / "first.csv", [_row("cslb-1", business_name="Original")]))
    before = _contacts_snapshot(owner_conn)

    load_list(
        _csv(
            tmp_path / "second.csv",
            [
                _row("cslb-2", business_name="Newer", addr_line1="Different St"),
                _row("cslb-3", business_name="Newer", addr_line1="Different St"),
            ],
        )
    )

    assert _contacts_snapshot(owner_conn) == before  # pick runs once, at creation
    assert _count(owner_conn, "select count(*) from contacts") == 1
    assert _count(owner_conn, "select count(*) from intake_cslb_ca") == 3
    # The partial unique index would reject a second primary; the attach adds none.
    assert _count(owner_conn, "select count(*) from intake_cslb_ca where is_primary") == 1


def test_do_not_mail_or_merges_onto_the_existing_contact_on_attach(
    clean_db, tmp_path, owner_conn
):
    """Suppression is absorbing — the one contact field an attach is allowed to write."""
    load_list(_csv(tmp_path / "clean.csv", [_row("cslb-1")]))
    assert _count(owner_conn, "select count(*) from contacts where do_not_mail") == 0

    load_list(_csv(tmp_path / "dnm.csv", [_row("cslb-2", do_not_mail="true")]))

    assert _count(owner_conn, "select count(*) from contacts where do_not_mail") == 1


# --- §10 test 4: phone uniqueness ----------------------------------------------


def test_a_second_phone_bearing_contact_cannot_take_a_used_phone(clean_db, tmp_path, owner_conn):
    """PRE-AUTHORIZED FIXTURE EXCEPTION (ground rule 3): no public verb can violate this
    — `load_list` attaches on a phone match rather than inserting a twin — so the raw
    insert here probes the index directly. It is a fixture action, not a verb bypass."""
    load_list(_csv(tmp_path / "one.csv", [_row("cslb-1")]))

    with pytest.raises(psycopg.errors.UniqueViolation):
        with owner_conn.cursor() as cur:
            cur.execute("insert into contacts (phone_e164) values (%s)", (E164,))
    owner_conn.rollback()


def test_null_phones_do_not_collide(clean_db, owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute("insert into contacts (segment) values ('a')")
        cur.execute("insert into contacts (segment) values ('b')")
    owner_conn.commit()

    assert _count(owner_conn, "select count(*) from contacts where phone_e164 is null") == 2


def test_seeds_are_exempt_from_phone_uniqueness(clean_db, tmp_path, owner_conn):
    load_list(_csv(tmp_path / "one.csv", [_row("cslb-1")]))

    with owner_conn.cursor() as cur:
        cur.execute(
            "insert into contacts (seed_key, is_seed, phone_e164) values ('seed-a', true, %s)",
            (E164,),
        )
    owner_conn.commit()

    assert _count(owner_conn, "select count(*) from contacts where phone_e164 = %s", (E164,)) == 2


# --- FBN: one contact per filing (design §3, pinned outside §10's numbering) -----


def test_fbn_rows_never_phone_merge_and_keep_the_phone_off_the_contact(
    clean_db, tmp_path, owner_conn
):
    """Pinned for the day an FBN filing carries a phone: the phone stays on the intake
    row, the contact is created with a null phone, so identity never merges filings."""
    path = _csv(
        tmp_path / "fbn.csv",
        [
            _row("fbn-ca-1", trade="", trades="", segment="fbn-ca-2026"),
            _row("fbn-ca-2", trade="", trades="", segment="fbn-ca-2026"),
        ],
    )
    report = load_list(path, source="fbn-ca-2026")

    assert report.loaded == 2
    assert _count(owner_conn, "select count(*) from contacts") == 2  # per filing, not merged
    assert _count(owner_conn, "select count(*) from contacts where phone_e164 is null") == 2
    assert _count(owner_conn, "select count(*) from intake_fbn_ca where phone_e164 = %s", (E164,)) == 2
    assert _count(owner_conn, "select count(*) from intake_fbn_ca where is_primary") == 2


# --- §10 test 5: trade via exists ----------------------------------------------


def test_a_multi_class_business_matches_both_trade_audiences_once_each(
    clean_db, tmp_path, owner_conn
):
    path = _csv(
        tmp_path / "multi.csv",
        [_row("cslb-1", trade="hvac", trades="hvac|plumber", license_class="C20|C36")],
    )
    load_list(path)

    with owner_conn.cursor() as cur:
        hvac = resolve_audience(cur, {"trade": ["hvac"]}).ids
        plumber = resolve_audience(cur, {"trade": ["plumber"]}).ids
        both = resolve_audience(cur, {"trade": ["hvac", "plumber"]}).ids

    assert len(hvac) == 1
    assert len(plumber) == 1
    assert hvac == plumber
    assert len(both) == 1  # once each, never twice in one audience


def test_the_summary_shows_every_trade_pipe_delimited(clean_db, tmp_path):
    load_list(
        _csv(
            tmp_path / "multi.csv",
            [_row("cslb-1", business_name="Multi Co", trades="hvac|plumber")],
        )
    )

    found = [c for c in search_contacts("Multi Co") if c.business_name == "Multi Co"]
    assert len(found) == 1
    assert found[0].trade == "hvac|plumber"


# --- §10 test 10: seed retirement ----------------------------------------------


def _seed(name="Founder One"):
    return ensure_seed_contacts(
        [{"name": name, "line1": "200 N Spring St", "city": "Los Angeles",
          "state": "CA", "zip": "90012"}]
    )


def test_retire_seed_clears_the_flag_and_suppresses_atomically(clean_db, owner_conn):
    _seed()
    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where is_seed")
        row = cur.fetchone()
        assert row is not None
        seed_id = row[0]

    retire_seed(seed_id)

    with owner_conn.cursor() as cur:
        cur.execute("select is_seed, do_not_mail from contacts where id = %s", (seed_id,))
        assert cur.fetchone() == (False, True)


def test_a_retired_seed_is_in_no_audience_and_rides_no_wave(clean_db, owner_conn):
    """Including a rule-less full-list wave — clearing `is_seed` alone would stop the
    per-wave seed append while leaving the row eligible for exactly that."""
    _seed()
    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where is_seed")
        row = cur.fetchone()
        assert row is not None
        seed_id = row[0]

    retire_seed(seed_id)

    with owner_conn.cursor() as cur:
        assert seed_id not in resolve_audience(cur, {}).ids
        assert seed_id not in resolve_audience(cur, {"trade": ["plumber"]}).ids


def test_ensure_seed_contacts_without_the_config_entry_does_not_revive_a_retired_seed(
    clean_db, owner_conn
):
    _seed("Founder One")
    with owner_conn.cursor() as cur:
        cur.execute("select id from contacts where is_seed")
        row = cur.fetchone()
        assert row is not None
        seed_id = row[0]
    retire_seed(seed_id)

    _seed("Founder Two")  # a different config, the retired entry gone from it

    with owner_conn.cursor() as cur:
        cur.execute("select is_seed, do_not_mail from contacts where id = %s", (seed_id,))
        assert cur.fetchone() == (False, True)
