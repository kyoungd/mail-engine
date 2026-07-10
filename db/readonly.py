"""Read-only role connection — the analysis bypass. Writes are impossible at the
role level; the session read-only flag is defense in depth."""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg


def _readonly_url() -> str:
    url = os.environ.get("READONLY_DATABASE_URL")
    if not url:
        raise RuntimeError("READONLY_DATABASE_URL is not set")
    return url


@contextmanager
def readonly_connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(_readonly_url()) as conn:
        conn.read_only = True
        yield conn
