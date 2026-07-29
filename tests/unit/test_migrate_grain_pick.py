"""§3's pick rule, isolated from the database.

One selection resolves both the tuple tie and the row-within-tuple choice, so these
cases are the specification: max-frequency address tuple → candidate set → lowest
`list_key`. `addr_line2` sits deliberately outside the tuple, and `email` coalesces over
the whole phone group rather than the candidate set.
"""

from jobs.migrate_grain import coalesce_email, derive_trades, pick_winner


def _row(list_key, line1="1 Main St", line2="", city="Lodi", state="CA", zip_="95242", email=None):
    return {
        "list_key": list_key,
        "addr_line1": line1,
        "addr_line2": line2,
        "addr_city": city,
        "addr_state": state,
        "addr_zip": zip_,
        "email": email,
    }


def test_most_frequent_address_wins_over_lower_list_key():
    """Frequency decides first — a lower list_key does NOT rescue a minority address."""
    rows = [
        _row("cslb-1", line1="1 Rare Rd"),
        _row("cslb-7", line1="9 Common Ave"),
        _row("cslb-8", line1="9 Common Ave"),
    ]
    assert pick_winner(rows)["list_key"] == "cslb-7"


def test_tuple_tie_breaks_on_lowest_list_key_across_all_tied_tuples():
    """The candidate set is every row bearing a MAXIMUM-frequency tuple — all tied
    tuples' rows together, not the first tuple encountered."""
    rows = [
        _row("cslb-5", line1="5 Fifth St"),
        _row("cslb-6", line1="5 Fifth St"),
        _row("cslb-2", line1="2 Second St"),
        _row("cslb-3", line1="2 Second St"),
    ]
    assert pick_winner(rows)["list_key"] == "cslb-2"


def test_addr_line2_is_outside_the_frequency_tuple():
    """Suite-only variants count as ONE address for frequency; the winner row's own
    addr_line2 rides along into the mailing address."""
    rows = [
        _row("cslb-1", line1="7 Tower Rd", line2="Ste 100"),
        _row("cslb-2", line1="7 Tower Rd", line2="Ste 200"),
        _row("cslb-3", line1="8 Other Rd"),
    ]
    winner = pick_winner(rows)
    assert winner["list_key"] == "cslb-1"
    assert winner["addr_line2"] == "Ste 100"


def test_single_row_group_picks_itself():
    assert pick_winner([_row("cslb-9")])["list_key"] == "cslb-9"


def test_email_prefers_the_winner():
    rows = [_row("cslb-1", email="win@x.com"), _row("cslb-2", email="other@x.com")]
    assert coalesce_email(rows, pick_winner(rows)) == "win@x.com"


def test_email_coalesces_over_the_whole_group_not_the_candidate_set():
    """Emails are too scarce to discard on an address-frequency technicality: a minority
    address's email is still the business's email."""
    rows = [
        _row("cslb-7", line1="9 Common Ave"),
        _row("cslb-8", line1="9 Common Ave"),
        _row("cslb-9", line1="1 Rare Rd", email="only@x.com"),
    ]
    winner = pick_winner(rows)
    assert winner["list_key"] == "cslb-7"
    assert coalesce_email(rows, winner) == "only@x.com"


def test_email_fallback_scans_by_ascending_list_key_not_row_order():
    """Winner carries no email, so the fallback runs — and it must order by list_key
    rather than by however the group came back from the database."""
    rows = [
        _row("cslb-5", line1="B St", email="late@x.com"),
        _row("cslb-2", line1="A St"),
        _row("cslb-4", line1="B St", email="early@x.com"),
        _row("cslb-3", line1="A St"),
    ]
    winner = pick_winner(rows)  # A St and B St tie at 2 → candidate set is all four
    assert winner["list_key"] == "cslb-2"
    assert winner["email"] is None
    assert coalesce_email(rows, winner) == "early@x.com"  # cslb-4 precedes cslb-5


def test_email_absent_everywhere_is_none():
    assert coalesce_email([_row("cslb-1")], _row("cslb-1")) is None


def test_derive_trades_is_the_sorted_distinct_union():
    assert derive_trades("C20|C36") == ["hvac", "plumber"]
    assert derive_trades("C36") == ["plumber"]
    assert derive_trades("C10, C36") == ["electrician", "plumber"]
    assert derive_trades("B|C-10") == ["electrician"]  # B maps to no NMC trade


def test_derive_trades_handles_absent_classes():
    """FBN rows carry none — the column exists for every source, the value is
    source-specific."""
    assert derive_trades(None) == []
    assert derive_trades("") == []
    assert derive_trades("B") == []
