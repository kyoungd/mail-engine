"""Phase 1 gate: migration 0008 adds the intake split ADDITIVELY. The new tables,
columns and indexes exist, and the full migration set still applies twice cleanly.

Schema-existence only, deliberately. The behavioural DDL assertions — one-primary-
per-contact, phone uniqueness — need rows in the intake tables, and no public verb
writes them until Phase 2's load_list. Ground rule 3 authorises exactly ONE raw-SQL
fixture exception (design §10 test 4); spending a second here would be an escalation,
so those assertions land in Phase 2 where a verb can drive them.
"""

import pytest
from yoyo import get_backend, read_migrations

INTAKE_TABLES = ("intake_cslb_ca", "intake_fbn_ca")
NEW_TABLES = {*INTAKE_TABLES, "contact_merge_map"}

# design §2.1 — both intake tables share the canonical-CSV core plus the
# standardization columns written only by the verify_addresses job (§5).
INTAKE_COLUMNS = {
    "id",
    "list_key",
    "contact_id",
    "business_name",
    "contact_name",
    "trade",
    "trades",
    "license_class",
    "phone_e164",
    "email",
    "addr_line1",
    "addr_line2",
    "addr_city",
    "addr_state",
    "addr_zip",
    "segment",
    "do_not_mail",
    "is_primary",
    "std_addr_line1",
    "std_addr_line2",
    "std_addr_city",
    "std_addr_state",
    "std_addr_zip",
    "delivery_point",
    "deliverability",
    "std_verified_at",
    "ingested_at",
}


def _columns(conn, table: str) -> dict[str, tuple[str, str, str | None]]:
    with conn.cursor() as cur:
        cur.execute(
            "select column_name, udt_name, is_nullable, column_default "
            "from information_schema.columns "
            "where table_schema = 'public' and table_name = %s",
            (table,),
        )
        return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}


def _indexdefs(conn, table: str) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "select indexname, indexdef from pg_indexes "
            "where schemaname = 'public' and tablename = %s",
            (table,),
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def test_apply_twice_is_clean(owner_url, migrations_dir):
    """0008 is idempotent — the test_migrations_idempotent pattern, now spanning it."""
    backend = get_backend(owner_url)
    migrations = read_migrations(str(migrations_dir))
    for _ in range(2):
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
    assert list(backend.to_apply(migrations)) == []


def test_new_tables_exist(owner_conn):
    with owner_conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables "
            "where table_schema = 'public'"
        )
        tables = {r[0] for r in cur.fetchall()}
    assert NEW_TABLES <= tables


@pytest.mark.parametrize("table", INTAKE_TABLES)
def test_intake_columns_match_design(owner_conn, table):
    assert set(_columns(owner_conn, table)) == INTAKE_COLUMNS


@pytest.mark.parametrize("table", INTAKE_TABLES)
def test_trades_is_a_not_null_text_array(owner_conn, table):
    udt, nullable, default = _columns(owner_conn, table)["trades"]
    assert udt == "_text"  # text[]
    assert nullable == "NO"
    assert default is not None and "{}" in default


@pytest.mark.parametrize("table", INTAKE_TABLES)
def test_one_primary_per_contact_index_exists(owner_conn, table):
    """§2.1 DB-enforces §3's exactly-one-primary-per-contact. Existence only here —
    proving enforcement needs rows, and no verb writes intake rows until Phase 2."""
    defs = _indexdefs(owner_conn, table)
    primary = [d for d in defs.values() if "is_primary" in d]
    assert primary, f"no partial index on is_primary for {table}"
    assert any("UNIQUE" in d and "contact_id" in d for d in primary)


@pytest.mark.parametrize("table", INTAKE_TABLES)
def test_lookup_indexes_exist(owner_conn, table):
    defs = " ".join(_indexdefs(owner_conn, table).values())
    assert "(contact_id)" in defs
    assert "(phone_e164)" in defs
    assert "(delivery_point)" in defs


@pytest.mark.parametrize("table", INTAKE_TABLES)
def test_list_key_is_unique(owner_conn, table):
    """Immutability (§2.1) rests on `on conflict (list_key) do nothing`."""
    defs = _indexdefs(owner_conn, table)
    assert any("UNIQUE" in d and "list_key" in d for d in defs.values())


def test_contacts_seed_key_is_unique(owner_conn):
    assert "seed_key" in _columns(owner_conn, "contacts")
    defs = _indexdefs(owner_conn, "contacts")
    assert any("UNIQUE" in d and "seed_key" in d for d in defs.values())


def test_pieces_contact_wave_index_exists(owner_conn):
    """Plain index, not the unique constraint — that one goes in Phase 2's swap."""
    defs = " ".join(_indexdefs(owner_conn, "pieces").values())
    assert "contact_id" in defs and "wave_id" in defs


def test_contact_merge_map_shape(owner_conn):
    cols = _columns(owner_conn, "contact_merge_map")
    assert set(cols) == {"old_contact_id", "new_contact_id", "merged_at"}


def test_swap_dropped_the_pre_swap_columns(owner_conn):
    """Phase 2 crossed the boundary this test used to pin the near side of.

    In Phase 1 it asserted the opposite — that `list_key`/`trade`/`license_class` were
    still present — because that phase's claim was "additive only, the swap is Phase 2's
    boundary, not this one". Phase 2 IS that boundary, so the assertion inverts by
    design rather than by loosening: the columns are gone, `migrate_grain`'s in-script
    swap having dropped them, and every reader now goes through the intake rows."""
    cols = set(_columns(owner_conn, "contacts"))
    assert not ({"list_key", "trade", "license_class"} & cols)
    assert "seed_key" in cols
