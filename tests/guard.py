"""Refuses to let the test suite run against a production environment.

conftest reads OWNER_DATABASE_URL from the .env of whichever folder pytest was
invoked in, and `clean_db` truncates all six tables against it. In the
mail-engine-production folder that resolves to mailengine_prod, which would destroy
the append-only event history every derived fact recomputes from (FR-7).

Fail-closed by construction: the allowlist names the databases we positively know are
disposable, and everything else — including an unrecognised name or an empty URL — is
treated as production. A wrong "unsafe" costs a line in .env; a wrong "safe" costs the
campaign's history.
"""

from urllib.parse import urlparse

TEST_DATABASES = frozenset({"mailengine_dev", "mailengine_test"})


def _database_name(url: str) -> str:
    return urlparse(url).path.lstrip("/")


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def unsafe_test_environment(
    owner_url: str, lob_key: str, medusa_ro_url: str = ""
) -> str | None:
    """Return a human-readable reason to refuse, or None if this is a test environment.

    Three independent checks: the database must be disposable, the Lob key must not
    be live, and the folder must not hold a REAL Medusa credential (A2: the local
    `medusa_nmc_ro` mirror is fine; anything remote is the production subscriber
    database, which no test run has any business holding — read-only or not).
    Each alone is disqualifying — they catch different mistakes.
    """
    name = _database_name(owner_url)
    if not name:
        return f"OWNER_DATABASE_URL is missing or has no database name (got {owner_url!r})"
    if name not in TEST_DATABASES:
        return (
            f"database {name!r} is not a recognised test database "
            f"({', '.join(sorted(TEST_DATABASES))}). The suite truncates every table — "
            f"refusing to run against what looks like production."
        )
    if lob_key.startswith("live_"):
        return (
            "LOB_API_KEY is a live key. That means this folder is wired for real mail "
            "and real money — refusing to run the test suite here."
        )
    if medusa_ro_url:
        host = urlparse(medusa_ro_url).hostname or ""
        if host not in _LOCAL_HOSTS:
            return (
                f"MEDUSA_READONLY_URL points at a remote host ({host!r}) — a real "
                "Medusa credential. The test suite never holds one; use the local "
                "medusa_nmc_ro mirror or unset it."
            )
    return None
