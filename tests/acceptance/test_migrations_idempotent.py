"""Phase 0 gate: migration tooling is idempotent — applying twice to an empty
database is clean, and the six tables exist afterward."""

from yoyo import get_backend, read_migrations

EXPECTED_TABLES = {"contacts", "variants", "waves", "pieces", "events", "activation"}


def test_apply_twice_is_clean(owner_url, migrations_dir):
    backend = get_backend(owner_url)
    migrations = read_migrations(str(migrations_dir))

    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))

    # A third resolution has nothing left to apply — proof of idempotent tooling.
    assert list(backend.to_apply(migrations)) == []


def test_all_six_tables_exist(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}
    assert EXPECTED_TABLES <= tables
