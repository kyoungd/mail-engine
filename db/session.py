"""Transaction-per-verb helper. The only write path opens a connection as the
owner role, runs one transaction, and commits — or rolls back on any exception."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


def _owner_url() -> str:
    url = os.environ.get("OWNER_DATABASE_URL")
    if not url:
        raise RuntimeError("OWNER_DATABASE_URL is not set")
    return url


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    with psycopg.connect(_owner_url()) as conn:
        with conn.transaction():
            yield conn
