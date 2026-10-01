"""The sale (docs/contact-engine/05c-sale-and-90-days.md §4.1, §4.2).

A contact is sold when it has a Signed up not undone, or the website's sale: stage
`won`, a `signup.completed` on it, or an unmatched one carrying its phone. The seller is
recorded, never inferred: the rep of the latest Signed up not undone, else the
`web_seller` the nightly wrote once.
"""

from uuid import UUID

from psycopg import sql

from config.params import HOUSE_PARTNER_ID
from service.custody import set_owner
from service.dnc import BLOCKED_SQL

# The website's sale, written over the alias `c` of a contacts row.
WEBSITE_SOLD_SQL = sql.SQL(
    "(c.stage_snapshot = 'won' or exists (select 1 from events e "
    "  where e.type = 'signup.completed' and (e.contact_id = c.id or (e.contact_id is null "
    "  and (e.payload->>'phone_e164' = c.phone_e164 "
    "       or dnc_normalize(e.payload->>'phone') = c.phone_e164)))))"
)
SOLD_SQL = sql.SQL(
    "({website} or exists (select 1 from calls k where k.contact_id = c.id "
    "  and k.outcome = 'signed_up' and k.undone_at is null))"
).format(website=WEBSITE_SOLD_SQL)


def seller(cur, contact_id: UUID) -> UUID | None:
    cur.execute(
        "select rep_id from calls where contact_id = %s and outcome = 'signed_up' "
        "and undone_at is null order by outcome_at desc, id desc limit 1",
        (contact_id,),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0]
    cur.execute("select web_seller from contact_state where contact_id = %s", (contact_id,))
    row = cur.fetchone()
    return row[0] if row else None


def _taken_back(cur, rep: UUID, contact_id: UUID) -> bool:
    """The latest custody event naming `rep`, by event id, takes the contact from them
    (answer 7)."""
    cur.execute(
        "select type, payload->>'previous_owner_id' from events where contact_id = %s "
        "and type in ('contact.assigned', 'contact.assignment_expired', "
        "'contact.reclaimed') and (payload->>'new_owner_id' = %s "
        "or payload->>'previous_owner_id' = %s) order by id desc limit 1",
        (contact_id, str(rep), str(rep)),
    )
    row = cur.fetchone()
    return row is not None and row[0] == "contact.reclaimed" and row[1] == str(rep)


def hold_for_signer(cur, rep: UUID, rep_active: bool, contact_id: UUID) -> None:
    """§4.2: after a Signed up, under the contact's lock — the contact goes to its
    signer with no batch, or, when it may not, leaves any other rep for the house."""
    cur.execute(
        sql.SQL(
            "select c.owner_id, c.assignment_batch_id, {blocked}, c.dnc_registry "
            "from contacts c where c.id = %s"
        ).format(blocked=BLOCKED_SQL),
        (contact_id,),
    )
    row = cur.fetchone()
    assert row is not None
    owner, pointer, blocked, listed = row
    if owner == rep and pointer is None:
        return
    if rep_active and not blocked and not listed and not _taken_back(cur, rep, contact_id):
        set_owner(cur, contact_id, rep, event_type="contact.assigned", reason="sold",
                  actor=str(rep))
    elif owner not in (rep, HOUSE_PARTNER_ID):
        set_owner(cur, contact_id, HOUSE_PARTNER_ID, event_type="contact.reclaimed",
                  reason="sold", actor="system")
