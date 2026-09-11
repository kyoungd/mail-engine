"""`issue-token NAME --ini FILE` writes a rep's dnc-uploader.ini (2026-09-11).

One universal uploader build serves every rep; what is per-rep — the upload token —
travels in the ini instead of being compiled in. NMC fills the [nmc] token; the rep
fills their own FTC login, which never reaches NMC.
"""

import configparser

import psycopg
import pytest

from clients.dnc_uploader import load_config
from jobs import partners_cli
from seams.fakes import FakeTokenRegistry

PARTNER_NAME = "Token Partner"


# harness copied from test_partner_tokens.py (frozen; not imported from a test module)


@pytest.fixture(autouse=True)
def _no_leftover_partner(clean_db, owner_conn):
    """clean_db deliberately does NOT truncate partners, so a test creating one
    removes it."""
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
    return next(w for w in out.split() if w.startswith("nmcdnc_"))


def _run(monkeypatch, registry, argv) -> int:
    monkeypatch.setattr(partners_cli, "_token_registry", lambda: registry)
    return partners_cli.main(argv)


def test_issue_token_can_write_the_reps_ini(
    clean_db, owner_conn, monkeypatch, capsys, tmp_path
):
    _partner(owner_conn)
    ini = tmp_path / "dnc-uploader.ini"

    argv = ["issue-token", PARTNER_NAME, "--ini", str(ini)]
    assert _run(monkeypatch, FakeTokenRegistry(), argv) == 0

    token = _printed_token(capsys)  # still shown once, exactly as before
    parsed = configparser.ConfigParser()
    parsed.read(ini)
    assert parsed.get("nmc", "token") == token
    assert (parsed.get("ftc", "org_id"), parsed.get("ftc", "password")) == ("", "")
    assert ini.stat().st_mode & 0o777 == 0o600  # it carries a token

    parsed["ftc"]["org_id"], parsed["ftc"]["password"] = "10337886-60999", "secret"
    with open(ini, "w") as handle:
        parsed.write(handle)
    assert load_config(ini).token == token  # the client accepts what we wrote


def test_issue_token_never_overwrites_an_existing_ini(
    clean_db, owner_conn, owner_url, monkeypatch, tmp_path
):
    """An existing file may already hold someone's FTC login. Refuse BEFORE a token
    is issued — a refusal after would have rotated the rep's working token away."""
    _partner(owner_conn)
    ini = tmp_path / "dnc-uploader.ini"
    ini.write_text("[ftc]\norg_id = 1\npassword = keep-me\n")

    argv = ["issue-token", PARTNER_NAME, "--ini", str(ini)]
    assert _run(monkeypatch, FakeTokenRegistry(), argv) == 2

    assert "keep-me" in ini.read_text()
    assert _token_row(owner_url)[0] is None  # no token issued
