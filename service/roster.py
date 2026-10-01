"""The roster (docs/contact-engine/06a-the-api.md §4.1, §4.4): a rep on the website's
roster is one partner, keyed on `sales_rep_id`. The dialer makes a rep known and
deactivates one; every rep request resolves its `X-Rep` here."""

from uuid import UUID

import psycopg

from config.params import HOUSE_PARTNER_ID
from db.session import transaction
from domain.errors import ValidationError

_BIGINT = range(-(2**63), 2**63)


def _after_name_check(cur) -> None:
    """Called once per `make_known`, after the name is checked and before the write."""


def resolve_rep(sales_rep_id: int, allow_inactive: bool) -> UUID:
    if sales_rep_id not in _BIGINT:
        raise ValidationError("unknown_rep", "no such rep")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id, status from partners where sales_rep_id = %s for share",
                (sales_rep_id,),
            )
            row = cur.fetchone()
    if row is None or row[0] == HOUSE_PARTNER_ID:
        raise ValidationError("unknown_rep", "no such rep")
    if row[1] != "active" and not allow_inactive:
        raise ValidationError("rep_inactive", "the rep is inactive")
    return row[0]


def _check_name(cur, sales_rep_id: int, name: str) -> None:
    cur.execute("select id, sales_rep_id from partners where name = %s", (name,))
    holder = cur.fetchone()
    if holder is None or holder[1] == sales_rep_id:
        return
    if holder[0] == HOUSE_PARTNER_ID or holder[1] is not None:
        raise ValidationError("name_taken", "another partner has this name")
    cur.execute("select 1 from partners where sales_rep_id = %s", (sales_rep_id,))
    if cur.fetchone() is not None:
        raise ValidationError("name_taken", "another partner has this name")
    raise ValidationError(
        "link_first", "a partner has this name and no roster id: link it first"
    )


def make_known(sales_rep_id: int, name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("bad_request", "a rep has a name")
    if sales_rep_id not in _BIGINT:
        raise ValidationError("bad_request", "not a roster id")
    with transaction() as conn:
        with conn.cursor() as cur:
            _check_name(cur, sales_rep_id, name)
            _after_name_check(cur)
            try:
                with conn.transaction():
                    cur.execute(
                        "insert into partners (name, sales_rep_id) values (%s, %s) "
                        "on conflict (sales_rep_id) do nothing",
                        (name, sales_rep_id),
                    )
                    cur.execute(
                        "select id, status from partners where sales_rep_id = %s "
                        "for update",
                        (sales_rep_id,),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    if row[1] != "active":
                        raise ValidationError("rep_inactive", "the rep is inactive")
                    cur.execute("update partners set name = %s where id = %s",
                                (name, row[0]))
            except psycopg.errors.UniqueViolation:
                _check_name(cur, sales_rep_id, name)
                raise
    return "known"


def deactivate(sales_rep_id: int) -> str:
    if sales_rep_id not in _BIGINT:
        raise ValidationError("unknown_rep", "no such rep")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from partners where sales_rep_id = %s for update",
                (sales_rep_id,),
            )
            row = cur.fetchone()
            if row is None or row[0] == HOUSE_PARTNER_ID:
                raise ValidationError("unknown_rep", "no such rep")
            cur.execute("update partners set status = 'inactive' where id = %s", (row[0],))
    return "inactive"
