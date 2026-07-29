"""Phase 2 frozen acceptance tests — the ground-rule-4 re-run guard.

`ensure_swapped` runs unattended from `make migrate` and the test-DB setup, so its three
branches are pinned:

    post-swap                -> clean no-op
    pre-swap, WITH data      -> loud halt; never auto-merge a populated database
    pre-swap, EMPTY (fresh)  -> apply the swap; merging over zero rows IS the ceremony

The middle branch is the one that matters in anger: prod is never empty, so the guard
stops there rather than masking the real preflight.

These need a database at a schema the session fixture has already moved past, so each
test gets a genuine scratch database rather than a simulation of one.
"""

from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from yoyo import get_backend, read_migrations

from jobs.migrate_grain import PreflightHalt, ensure_swapped, swap_applied
from tests.conftest import MIGRATIONS_DIR


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


@pytest.fixture()
def scratch_url(owner_url: str):
    """A fresh database migrated to 0001-0008 — i.e. PRE-swap, which is the state the
    session's own test database no longer has."""
    name = f"me_scratch_{uuid4().hex[:10]}"
    with psycopg.connect(owner_url, autocommit=True) as admin:
        # template0, not the default template1: this cluster's template1 carries a
        # collation-version mismatch that makes it unusable as a template, and refreshing
        # it is a cluster-wide admin action no test should be taking.
        admin.execute(
            sql.SQL("create database {} template template0").format(sql.Identifier(name))
        )
    url = _with_database(owner_url, name)
    try:
        backend = get_backend(url)
        migrations = read_migrations(str(MIGRATIONS_DIR))
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        yield url
    finally:
        with psycopg.connect(owner_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("drop database if exists {} with (force)").format(
                    sql.Identifier(name)
                )
            )


def _swapped(url: str) -> bool:
    with psycopg.connect(url) as conn:
        return swap_applied(conn)


def test_an_empty_pre_swap_database_gets_the_swap_applied(scratch_url):
    assert _swapped(scratch_url) is False

    result = ensure_swapped(scratch_url)

    assert result == "swap applied to empty database"
    assert _swapped(scratch_url) is True


def test_a_populated_pre_swap_database_halts_loudly(scratch_url):
    """The guard must never merge someone's data as a side effect of `make migrate`."""
    with psycopg.connect(scratch_url) as conn:
        with conn.cursor() as cur:
            cur.execute("insert into contacts (list_key, trade) values ('cslb-1', 'plumber')")
        conn.commit()

    with pytest.raises(PreflightHalt):
        ensure_swapped(scratch_url)

    assert _swapped(scratch_url) is False  # nothing was changed on the way out


def test_a_post_swap_database_is_a_clean_no_op(scratch_url):
    ensure_swapped(scratch_url)

    assert ensure_swapped(scratch_url) == "already migrated"
    assert _swapped(scratch_url) is True


def test_the_swap_creates_the_phone_unique_index_and_drops_the_old_columns(scratch_url):
    ensure_swapped(scratch_url)

    with psycopg.connect(scratch_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from information_schema.columns where table_name = 'contacts' "
                "and column_name in ('list_key', 'trade', 'license_class')"
            )
            assert cur.fetchone() == (0,)
            cur.execute(
                "select count(*) from pg_indexes where indexname = 'contacts_phone_unique'"
            )
            assert cur.fetchone() == (1,)
            cur.execute(
                "select count(*) from pg_constraint where conname = 'pieces_contact_id_wave_id_key'"
            )
            assert cur.fetchone() == (0,)
