"""Fixture helpers for the business-grain schema.

Before the grain swap a test that needed a targetable contact wrote
`insert into contacts (trade) values ('plumber')`. Trade now lives on the intake rows —
as an array, because one business can hold several licence classes — so making a
contact the audience rule can find means writing a contact AND its primary intake row.

That is mechanical plumbing, which is exactly why it belongs in one place: design §10
test 11 lets fixture helpers follow the schema, while assertions and scenario semantics
change by zero characters. Centralizing it here keeps the per-test edit to the call.
"""

from typing import Any
from uuid import UUID, uuid4

_CONTACT_DEFAULTS: dict[str, Any] = {"source": "cslb"}


def new_contact(
    cur,
    *,
    trade: str | None = "plumber",
    trades: list[str] | None = None,
    list_key: str | None = None,
    intake: bool = True,
    **fields: Any,
) -> UUID:
    """Insert a contact and (unless `intake=False`) its primary intake row.

    `trades` defaults to `[trade]`, which is what makes the row match a `trade:[...]`
    audience. Pass `intake=False` for a contact that deliberately has no intake rows —
    a seed, or a contact under test for the no-intake-row paths.
    """
    values: dict[str, Any] = {**_CONTACT_DEFAULTS, **fields}
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))
    returning = "" if "id" in values else " returning id"
    cur.execute(
        f"insert into contacts ({', '.join(columns)}) values ({placeholders}){returning}",  # noqa: S608
        list(values.values()),
    )
    if "id" in values:
        contact_id = values["id"]
    else:
        row = cur.fetchone()
        assert row is not None
        contact_id = row[0]

    if intake:
        add_intake_row(
            cur,
            contact_id,
            trade=trade,
            trades=trades if trades is not None else ([trade] if trade else []),
            list_key=list_key,
            is_primary=True,
        )
    return contact_id


def add_intake_row(
    cur,
    contact_id: UUID,
    *,
    table: str = "intake_cslb_ca",
    trade: str | None = "plumber",
    trades: list[str] | None = None,
    list_key: str | None = None,
    is_primary: bool = False,
    **fields: Any,
) -> None:
    """Attach an intake row to an existing contact. Non-primary rows are how a test
    builds a multi-licence business — they match the trade filter but never dedupe or
    exclude, both of which key on the primary row."""
    values: dict[str, Any] = {
        "contact_id": contact_id,
        "list_key": list_key or f"cslb-{uuid4().hex[:12]}",
        "trade": trade,
        "trades": trades if trades is not None else ([trade] if trade else []),
        "is_primary": is_primary,
        **fields,
    }
    columns = list(values)
    placeholders = ", ".join(["%s"] * len(columns))
    cur.execute(
        f"insert into {table} ({', '.join(columns)}) values ({placeholders})",  # noqa: S608
        list(values.values()),
    )
