"""Phase 0 gate: the read-only role provably cannot write. It connects with no
session read-only flag, so the failure comes from the role's own privileges."""

import psycopg
import pytest
from psycopg import errors


def test_readonly_can_select(readonly_url, clean_db):
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from contacts")
            row = cur.fetchone()
            assert row is not None
            assert row[0] == 0


def test_readonly_insert_is_denied(readonly_url, applied_migrations):
    with psycopg.connect(readonly_url) as conn:
        with conn.cursor() as cur:
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute("insert into contacts (trade) values ('plumber')")
