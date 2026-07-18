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
    """Apply all migrations once for the session; yields (backend, migrations)."""
    backend = get_backend(owner_url)
    migrations = read_migrations(str(MIGRATIONS_DIR))
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))
    return backend, migrations


@pytest.fixture()
def owner_conn(owner_url: str, applied_migrations):
    with psycopg.connect(owner_url) as conn:
        yield conn


@pytest.fixture()
def clean_db(owner_url: str, applied_migrations):
    """Truncate all six tables before a DB test so tests don't leak into each other.
    Function-scoped and opt-in — pure unit tests neither request nor pay for it."""
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "truncate activation, events, pieces, waves, variants, contacts "
                "restart identity cascade"
            )
        conn.commit()
    yield
