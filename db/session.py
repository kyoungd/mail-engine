"""Transaction-per-verb helper. The only write path opens a connection as the
owner role, runs one transaction, and commits — or rolls back on any exception.

Inside an API request (docs/contact-engine/06a-the-api.md §4.3) the request's own
connection is ambient: every `transaction()` uses it as a savepoint, so the act and
its request memory commit together."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg

_ambient: ContextVar[psycopg.Connection | None] = ContextVar("ambient", default=None)


def _owner_url() -> str:
    url = os.environ.get("OWNER_DATABASE_URL")
    if not url:
        raise RuntimeError("OWNER_DATABASE_URL is not set")
    return url


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    conn = _ambient.get()
    if conn is not None:
        with conn.transaction():
            yield conn
        return
    with psycopg.connect(_owner_url()) as conn:
        with conn.transaction():
            yield conn


@contextmanager
def request_connection(*, read_only: bool = False) -> Iterator[psycopg.Connection]:
    """One connection and one transaction for a whole request, ambient to every
    `transaction()` inside it; a read is REPEATABLE READ, READ ONLY."""
    with psycopg.connect(_owner_url()) as conn:
        if read_only:
            conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            conn.read_only = True
        token = _ambient.set(conn)
        try:
            with conn.transaction():
                yield conn
        finally:
            _ambient.reset(token)
