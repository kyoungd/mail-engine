"""§3's primary-pick rule — the one definition, shared by both writers.

`migrate_grain` applies it once over prod's full history; `load_list` applies it on every
ingest over the group within the file. §4's equivalence claim ("a fresh-DB ingest of one
file applies exactly the pick the migration applies to the same rows") is only true while
there is a single implementation, so it lives here — in `resolution`, which both `jobs`
and `service` may import — rather than in either caller.
"""

from collections import Counter
from typing import Any


def pick_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """§3, one selection resolving both the tuple tie and the row-within-tuple choice.

    Compute each row's `(addr_line1, addr_city, addr_state, addr_zip)` frequency within
    the group; the candidate set is every row bearing a tuple of MAXIMUM frequency (all
    tied tuples' rows together); the winner is the lowest `list_key` in that set.

    `addr_line2` is deliberately outside the tuple, so suite-only variants of one address
    count as the same address for frequency; the winner row's own `addr_line2` rides along
    into the mailing address.
    """
    freq = Counter(
        (r["addr_line1"], r["addr_city"], r["addr_state"], r["addr_zip"]) for r in rows
    )
    top = max(freq.values())
    candidates = [
        r
        for r in rows
        if freq[(r["addr_line1"], r["addr_city"], r["addr_state"], r["addr_zip"])] == top
    ]
    return min(candidates, key=lambda r: r["list_key"] or "")


def coalesce_email(rows: list[dict[str, Any]], winner: dict[str, Any]) -> str | None:
    """Winner's email if present, else the first non-null by ascending `list_key` over the
    WHOLE phone group — not just the max-frequency candidate set. Emails are too scarce to
    discard on an address-frequency technicality (§3)."""
    if winner.get("email"):
        return winner["email"]
    for row in sorted(rows, key=lambda r: r["list_key"] or ""):
        if row.get("email"):
            return row["email"]
    return None
