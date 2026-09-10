"""Phase 5a gate: issuing and revoking a partner's upload token.

The token ships inside a binary on a rep's laptop and is assumed to leak, so its
only capability is posting a snapshot for its own partner. Nothing keeps the
plaintext: it is printed once and stored as a SHA-256.

The interesting property is ORDER. Issue writes the database and then pushes — a
failed push leaves a token the Worker will not honour, which is inert. Revoke
pushes and THEN writes — reversed on purpose, so a half-failure leaves the token
dead at the edge rather than alive at the edge and revoked on paper.
"""

import hashlib

import psycopg
import pytest

from jobs import partners_cli
from seams.fakes import FakeTokenRegistry
from seams.token_registry import TokenRegistryError

PARTNER_NAME = "Token Partner"


@pytest.fixture(autouse=True)
def _no_leftover_partner(clean_db, owner_conn):
    """clean_db deliberately does NOT truncate partners — the house row is
    load-bearing — so conftest's rule is that a test creating one removes it.
    Without this, a token issued by an earlier test is still on the row and the
    "nothing was written" assertions read a stale hash."""
    _drop_partner(owner_conn)
    yield
    _drop_partner(owner_conn)


def _drop_partner(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("delete from partners where name = %s", (PARTNER_NAME,))
    conn.commit()


def _partner(conn, status: str = "active"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into partners (name, status) values (%s, %s) "
            "on conflict (name) do update set status = excluded.status returning id",
            (PARTNER_NAME, status),
        )
        row = cur.fetchone()
        assert row is not None
    conn.commit()
    return row[0]


def _token_row(owner_url: str) -> tuple:
    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select api_token_hash, api_token_issued_at, api_token_revoked_at "
                "from partners where name = %s",
                (PARTNER_NAME,),
            )
            row = cur.fetchone()
            assert row is not None
            return row


def _printed_token(capsys) -> str:
    out = capsys.readouterr().out
    token = next(w for w in out.split() if w.startswith("nmcdnc_"))
    return token


def _run(monkeypatch, registry, argv) -> int:
    monkeypatch.setattr(partners_cli, "_token_registry", lambda: registry)
    return partners_cli.main(argv)


def test_issue_prints_the_token_once_and_stores_only_its_hash(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    _partner(owner_conn)

    assert _run(monkeypatch, FakeTokenRegistry(), ["issue-token", PARTNER_NAME]) == 0

    token = _printed_token(capsys)
    stored_hash, issued_at, revoked_at = _token_row(owner_url)
    assert stored_hash == hashlib.sha256(token.encode()).hexdigest()
    assert issued_at is not None and revoked_at is None

    with psycopg.connect(owner_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from partners where name = %s and "
                "coalesce(san_number,'') || coalesce(api_token_hash,'') like %s",
                (PARTNER_NAME, f"%{token}%"),
            )
            leaked = cur.fetchone()
            assert leaked is not None and leaked[0] == 0  # the plaintext is nowhere


def test_issue_pushes_the_hash_to_the_registry(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    partner_id = _partner(owner_conn)
    registry = FakeTokenRegistry()

    _run(monkeypatch, registry, ["issue-token", PARTNER_NAME])

    token = _printed_token(capsys)
    assert registry.published == [
        (hashlib.sha256(token.encode()).hexdigest(), partner_id)
    ]


def test_reissue_revokes_the_old_hash_and_publishes_the_new(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    _partner(owner_conn)
    registry = FakeTokenRegistry()
    _run(monkeypatch, registry, ["issue-token", PARTNER_NAME])
    first = _printed_token(capsys)

    _run(monkeypatch, registry, ["issue-token", PARTNER_NAME])
    second = _printed_token(capsys)

    old_hash = hashlib.sha256(first.encode()).hexdigest()
    new_hash = hashlib.sha256(second.encode()).hexdigest()
    assert second != first
    assert old_hash in registry.revoked
    assert _token_row(owner_url)[0] == new_hash


def test_revoke_removes_it_at_the_edge_before_the_database(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    _partner(owner_conn)
    registry = FakeTokenRegistry()
    _run(monkeypatch, registry, ["issue-token", PARTNER_NAME])
    capsys.readouterr()

    assert _run(monkeypatch, registry, ["revoke-token", PARTNER_NAME]) == 0

    assert registry.calls[-1][0] == "revoke"
    stored_hash, _, revoked_at = _token_row(owner_url)
    assert stored_hash is None and revoked_at is not None


def test_revoke_refuses_when_the_registry_is_unreachable(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    _partner(owner_conn)
    working = FakeTokenRegistry()
    _run(monkeypatch, working, ["issue-token", PARTNER_NAME])
    token = _printed_token(capsys)

    broken = FakeTokenRegistry(fail=True)
    assert _run(monkeypatch, broken, ["revoke-token", PARTNER_NAME]) == 2

    # never report a revoke that did not happen
    assert _token_row(owner_url)[0] == hashlib.sha256(token.encode()).hexdigest()


def test_issue_refuses_for_an_unknown_or_inactive_partner(
    clean_db, owner_conn, owner_url, monkeypatch
):
    registry = FakeTokenRegistry()

    assert _run(monkeypatch, registry, ["issue-token", "Nobody"]) == 2
    _partner(owner_conn, status="inactive")
    assert _run(monkeypatch, registry, ["issue-token", PARTNER_NAME]) == 2

    assert registry.published == []
    assert _token_row(owner_url)[0] is None


def test_issue_with_no_push_stores_locally_and_warns(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    """The pre-Worker escape hatch: the edge does not exist yet."""
    _partner(owner_conn)
    registry = FakeTokenRegistry()

    assert _run(monkeypatch, registry, ["issue-token", PARTNER_NAME, "--no-push"]) == 0

    captured = capsys.readouterr()
    assert registry.published == []
    assert "not pushed" in (captured.out + captured.err).lower()
    assert _token_row(owner_url)[0] is not None


def test_the_registry_must_be_configured_for_a_real_revoke(clean_db, owner_conn):
    """`_token_registry()` refuses rather than defaulting to a no-op when
    SNAPSHOT_INBOX_URL is unset — an unconfigured revoke must not look like one
    that worked."""
    _partner(owner_conn)
    with pytest.raises(TokenRegistryError):
        partners_cli._token_registry()


def test_a_failed_push_still_shows_the_token(
    clean_db, owner_conn, owner_url, monkeypatch, capsys
):
    """A failed push must not swallow the token. The hash is already written, so a
    token nobody ever saw locks the partner out with no recovery — and in the
    rotation case the previous token has already been killed at the edge."""
    _partner(owner_conn)

    assert _run(
        monkeypatch, FakeTokenRegistry(fail=True), ["issue-token", PARTNER_NAME]
    ) == 2

    captured = capsys.readouterr()
    token = next(w for w in captured.out.split() if w.startswith("nmcdnc_"))
    assert _token_row(owner_url)[0] == hashlib.sha256(token.encode()).hexdigest()
    assert "not published" in (captured.out + captured.err).lower()
