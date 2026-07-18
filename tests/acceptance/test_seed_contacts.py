"""ensure_seed_contacts (PRD FR-4): the seed addresses are config, not a management UI.
An idempotent verb upserts founder addresses as is_seed contacts — re-running it (a
deploy, a cron) never duplicates them."""

import psycopg

from service.contacts import ensure_seed_contacts

SEEDS = [
    {"name": "Young HQ", "line1": "200 N Spring St", "city": "Los Angeles",
     "state": "CA", "zip": "90012"},
    {"name": "Partner HQ", "line1": "185 Berry St", "city": "San Francisco",
     "state": "CA", "zip": "94107"},
]


def _scalar(url, query, params=()):
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            assert row is not None
            return row[0]


def test_ensure_seed_contacts_creates_flagged_rows(clean_db, readonly_url):
    ensure_seed_contacts(SEEDS)
    assert _scalar(readonly_url, "select count(*) from contacts where is_seed") == 2
    assert _scalar(
        readonly_url,
        "select addr_line1 from contacts where business_name = 'Young HQ'",
    ) == "200 N Spring St"


def test_ensure_seed_contacts_is_idempotent(clean_db, readonly_url):
    ensure_seed_contacts(SEEDS)
    ensure_seed_contacts(SEEDS)  # re-run, no dupes
    assert _scalar(readonly_url, "select count(*) from contacts where is_seed") == 2
