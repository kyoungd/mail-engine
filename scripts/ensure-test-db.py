"""Create mailengine_test (template0) if it does not exist — the scratch DB the
test suites truncate, so `make test` never destroys the canonical dev ingest.

usage: ensure-test-db.py [-h]

Needs OWNER_DATABASE_URL in the environment (make targets source .env). The
database is created from template0 because this cluster's template1 carries a
collation-version mismatch. Idempotent; prints one line either way.
"""

import os
import sys
from urllib.parse import urlparse

import psycopg
from psycopg import sql

TEST_DB = "mailengine_test"


def main() -> int:
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__)
        return 0
    url = os.environ.get("OWNER_DATABASE_URL", "")
    if not url:
        print("ensure-test-db: OWNER_DATABASE_URL not set", file=sys.stderr)
        return 2
    owner = urlparse(url).username
    if not owner:
        print("ensure-test-db: OWNER_DATABASE_URL has no username", file=sys.stderr)
        return 2
    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute(
            "select 1 from pg_database where datname = %s", (TEST_DB,)
        ).fetchone()
        if exists:
            print(f"ensure-test-db: {TEST_DB} present")
        else:
            conn.execute(
                sql.SQL("create database {} template template0 owner {}").format(
                    sql.Identifier(TEST_DB), sql.Identifier(owner)
                )
            )
            print(f"ensure-test-db: created {TEST_DB} (template0, owner {owner})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
