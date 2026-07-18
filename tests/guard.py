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


def unsafe_test_environment(owner_url: str, lob_key: str) -> str | None:
    """Return a human-readable reason to refuse, or None if this is a test environment.

    Two independent checks: the database must be disposable, and the Lob key must not
    be live. Either alone is disqualifying — they catch different mistakes (pointing
    the suite at the wrong DB vs. running it in a folder wired for real money).
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
    return None
