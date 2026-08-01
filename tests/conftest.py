"""Shared fixtures. Loads .env, exposes the two connection URLs and the
migrations directory, and provides a session-scoped fixture that applies
migrations so acceptance tests run against a live, migrated database.

Guarded: this file reads the .env of whichever folder pytest was invoked in, and
`clean_db` truncates every table against it. `pytest_configure` refuses to start the
session unless that resolves to a disposable test database — see tests/guard.py."""

import os
from pathlib import Path

import psycopg
import pytest
from yoyo import get_backend, read_migrations

from jobs.migrate_grain import ensure_swapped
from tests.guard import unsafe_test_environment

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "db" / "migrations"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(PROJECT_ROOT / ".env")


def pytest_configure(config: pytest.Config) -> None:
    """Halt the whole session — not skip, not warn — if this is not a test environment."""
    problem = unsafe_test_environment(
        os.environ.get("OWNER_DATABASE_URL", ""), os.environ.get("LOB_API_KEY", "")
    )
    if problem:
        pytest.exit(
            f"REFUSING TO RUN THE TEST SUITE: {problem}\n"
            f"  invoked in: {PROJECT_ROOT}\n"
            f"  Run tests from the mail-engine (test) folder instead.",
            returncode=3,
        )


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} not set — copy .env.example to .env and `make up`")
    return value


@pytest.fixture(scope="session")
def owner_url() -> str:
    return _require("OWNER_DATABASE_URL")


@pytest.fixture(scope="session")
def readonly_url() -> str:
    return _require("READONLY_DATABASE_URL")


@pytest.fixture(scope="session")
def migrations_dir() -> Path:
    return MIGRATIONS_DIR


@pytest.fixture(scope="session")
def applied_migrations(owner_url: str):
    """Apply all migrations once for the session, then the grain swap; yields
    (backend, migrations).

    From Phase 2 on the suite runs against the POST-swap schema (implementation plan,
    ground rule 4): migrations 0001-0008 leave `contacts.list_key` in place, and the
    swap that drops it lives in `migrate_grain`, not a migration file. `ensure_swapped`
    applies it here because the test DB is empty — the same guard halts loudly on a
    populated one rather than auto-merging it."""
    backend = get_backend(owner_url)
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    ensure_swapped(owner_url)
    return backend, migrations


@pytest.fixture()
def owner_conn(owner_url: str, applied_migrations):
    with psycopg.connect(owner_url) as conn:
        yield conn


@pytest.fixture()
def clean_db(owner_url: str, applied_migrations):
    """Truncate every table before a DB test so tests don't leak into each other.
    Function-scoped and opt-in — pure unit tests neither request nor pay for it.

    The intake tables belong here as much as the original six: without them intake rows
    leak between tests and the resolve-then-insert cases pass or fail on execution
    order — a flake that reads as a resolution bug."""
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate activation, events, pieces, waves, variants, contacts, "
                "intake_cslb_ca, intake_fbn_ca, contact_merge_map, "
                "assignment_batches, feed_watermarks, "
                "suppression_tombstones, dnc_subscriptions "
                "restart identity cascade"
            )
            # partners is deliberately NOT truncated: the migration-seeded house and
            # John rows are load-bearing (owner_id default, recipient resolution).
            # Tests that create extra partners delete them in-test.
        conn.commit()
    yield
