"""Phase 4b gate: dnc_subscriptions is holder-aware.

Coverage that did not exist before — the only thing exercising this CLI was the
deselected e2e journey, which is why migration 0013 broke `add` (its
`on conflict (area_code)` no longer matched any constraint once the holder joined
the primary key) and a full offline suite still reported green.

The house partner is NMC's own SAN, so an unqualified add/remove means "our
subscription" and every existing caller — dnc-daily.sh, the rehearsal, the e2e
journey — keeps its meaning.
"""

from uuid import UUID

import psycopg

from config.params import HOUSE_PARTNER_ID
from jobs.subscribe_area_codes import main

PARTNER_NAME = "Coverage Partner"


def _partner(conn) -> UUID:
    with conn.cursor() as cur:
        cur.execute(
            "insert into partners (name, status) values (%s, 'active') "
            "on conflict (name) do update set status = 'active' returning id",
            (PARTNER_NAME,),
        )
        row = cur.fetchone()
        assert row is not None
    conn.commit()
    return row[0]


def _rows(owner_url: str) -> list[tuple]:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select area_code, san_holder_id from dnc_subscriptions "
                "order by area_code, san_holder_id"
            )
            return cur.fetchall()


def test_add_records_the_code_against_the_house_san(clean_db, owner_url):
    assert main(["add", "818"]) == 0

    assert _rows(owner_url) == [("818", HOUSE_PARTNER_ID)]


def test_add_is_idempotent_per_holder(clean_db, owner_url):
    main(["add", "818"])

    assert main(["add", "818"]) == 0
    assert _rows(owner_url) == [("818", HOUSE_PARTNER_ID)]


def test_add_for_a_partner_records_a_second_row_for_the_same_code(
    clean_db, owner_conn, owner_url
):
    partner = _partner(owner_conn)
    main(["add", "818"])

    assert main(["add", "818", "--holder", PARTNER_NAME]) == 0

    assert sorted(_rows(owner_url)) == sorted(
        [("818", HOUSE_PARTNER_ID), ("818", partner)]
    )


def test_add_for_an_unknown_partner_refuses_loudly(clean_db, owner_url):
    assert main(["add", "818", "--holder", "Nobody"]) == 2

    assert _rows(owner_url) == []


def test_remove_drops_only_the_named_holders_coverage(clean_db, owner_conn, owner_url):
    partner = _partner(owner_conn)
    main(["add", "818"])
    main(["add", "818", "--holder", PARTNER_NAME])

    assert main(["remove", "818"]) == 0

    assert _rows(owner_url) == [("818", partner)]


def test_remove_names_the_holders_it_left_behind(clean_db, owner_conn, capsys):
    _partner(owner_conn)
    main(["add", "818"])
    main(["add", "818", "--holder", PARTNER_NAME])
    capsys.readouterr()

    main(["remove", "818"])

    out = capsys.readouterr()
    assert PARTNER_NAME in out.out + out.err
    assert "818" in out.out + out.err


def test_list_shows_the_holder_for_each_code(clean_db, owner_conn, capsys):
    _partner(owner_conn)
    main(["add", "818"])
    main(["add", "714", "--holder", PARTNER_NAME])
    capsys.readouterr()

    main(["list"])

    out = capsys.readouterr().out
    assert PARTNER_NAME in out
    assert "714" in out and "818" in out


def test_the_console_view_runs_and_names_the_holders(clean_db, owner_conn):
    """The console's own SQL, against a real database. test_console.py monkeypatches
    _subscription_view, so nothing there executes this query — and the first version
    of it raised on a DISTINCT aggregate that pytest reported as green."""
    from jobs.console import _subscription_view

    _partner(owner_conn)
    main(["add", "818"])
    main(["add", "818", "--holder", PARTNER_NAME])

    (row,) = _subscription_view()

    assert row[0] == "818"
    assert row[5] == f"{PARTNER_NAME}, NMC"
