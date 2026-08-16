"""seams/nmc_admin.py — the main-site admin seam (console login gate + sales-rep
registration, approved 2026-08-16). Transport is injected — no network. Pins the
401-vs-403 distinction (bad password vs not-in-ADMIN_EMAILS), the id-as-string
wire shape, and that the console never renders the menu without an admin login
and never prints the JWT."""

import urllib.parse

import pytest

from jobs import console
from seams.nmc_admin import (
    NmcAdminClient,
    NmcAdminConfigError,
    NmcAuthError,
    NmcNotAdminError,
)


class FakeTransport:
    def __init__(self, routes):
        self.routes = routes
        self.last_body: dict | None = {}
        self.last_headers: dict = {}

    def __call__(self, method, url, body, headers):
        self.last_body = body
        self.last_headers = headers
        return self.routes[f"{method} {urllib.parse.urlsplit(url).path}"]


def test_login_returns_token():
    transport = FakeTransport({"POST /auth/customer/emailpass": (200, {"token": "jwt-abc"})})
    client = NmcAdminClient("http://x", "pk_1", transport=transport)
    assert client.login("a@b.com", "pw") == "jwt-abc"
    assert transport.last_body == {"email": "a@b.com", "password": "pw"}


def test_login_bad_credentials_is_distinct_and_loud():
    transport = FakeTransport({"POST /auth/customer/emailpass": (401, {})})
    with pytest.raises(NmcAuthError, match="credentials"):
        NmcAdminClient("http://x", "pk_1", transport=transport).login("a@b.com", "bad")


def test_admin_probe_sends_both_headers_and_accepts_200():
    transport = FakeTransport({"GET /store/nmc/admin/sales-reps": (200, {"reps": []})})
    NmcAdminClient("http://x", "pk_1", transport=transport).verify_admin("jwt-abc")
    assert transport.last_headers["Authorization"] == "Bearer jwt-abc"
    assert transport.last_headers["x-publishable-api-key"] == "pk_1"


def test_admin_probe_403_names_the_allowlist():
    transport = FakeTransport({"GET /store/nmc/admin/sales-reps": (403, {})})
    with pytest.raises(NmcNotAdminError, match="ADMIN_EMAILS"):
        NmcAdminClient("http://x", "pk_1", transport=transport).verify_admin("jwt-abc")


def test_create_sales_rep_returns_id_as_string():
    transport = FakeTransport(
        {"POST /store/nmc/admin/sales-reps": (200, {"rep": {"id": "47", "email": "p@x.com"}})}
    )
    rep_id = NmcAdminClient("http://x", "pk_1", transport=transport).create_sales_rep(
        "jwt-abc", email="p@x.com", name="New Partner"
    )
    assert rep_id == "47"
    assert transport.last_body == {"email": "p@x.com", "name": "New Partner"}


def test_missing_config_fails_loud_naming_the_var():
    with pytest.raises(NmcAdminConfigError, match="NMC_PUBLISHABLE_KEY"):
        NmcAdminClient("http://x", publishable_key=None)


def test_list_sales_reps_maps_roster_rows():
    transport = FakeTransport(
        {"GET /store/nmc/admin/sales-reps": (200, {"reps": [
            {"id": "47", "email": "kyoungd@yahoo.com", "name": "Yandex Kwon",
             "status": "active"}]})}
    )
    reps = NmcAdminClient("http://x", "pk_1", transport=transport).list_sales_reps("jwt-abc")
    assert reps == [{"id": "47", "email": "kyoungd@yahoo.com",
                     "name": "Yandex Kwon", "status": "active"}]
    assert transport.last_headers["Authorization"] == "Bearer jwt-abc"


# --- the console gate ---------------------------------------------------------


class _FakeAdminClient:
    def __init__(self, login_error=None, roster=()):
        self.login_error = login_error
        self.roster = list(roster)

    def login(self, email, password):
        if self.login_error:
            raise self.login_error
        return "jwt-abc"

    def verify_admin(self, token):
        return None

    def list_sales_reps(self, token):
        return self.roster


def _gate_io(monkeypatch, client, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _="": next(it))
    monkeypatch.setattr("getpass.getpass", lambda _="": "pw")
    monkeypatch.setattr(console, "_make_admin_client", lambda: client)
    # main() mutates these globals on login; monkeypatch restores them after.
    monkeypatch.setattr(console, "_admin_client", None)
    monkeypatch.setattr(console, "_admin_token", "")


def test_console_refuses_entry_on_bad_login(monkeypatch, capsys):
    client = _FakeAdminClient(login_error=NmcAuthError("credentials rejected (401)"))
    _gate_io(monkeypatch, client, "admin@x.com")
    assert console.main([]) != 0
    assert "partner status" not in capsys.readouterr().out  # menu never rendered


def test_console_shows_menu_after_admin_login(monkeypatch, capsys):
    _gate_io(monkeypatch, _FakeAdminClient(), "admin@x.com", "0")
    assert console.main([]) == 0
    out = capsys.readouterr().out
    assert "partner status" in out
    assert "jwt-abc" not in out  # the token is held, never printed


# --- the register step's rep-id prefill ---------------------------------------

_REP_47 = {"id": "47", "email": "kyoungd@yahoo.com", "name": "Yandex Kwon",
           "status": "active"}


def _register_io(monkeypatch, roster, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _="": next(it))
    monkeypatch.setattr(console, "_roster", lambda: [])  # no pick — new partner
    monkeypatch.setattr(console, "_admin_client", _FakeAdminClient(roster=roster))
    monkeypatch.setattr(console, "_admin_token", "jwt-abc")
    monkeypatch.setattr(console, "_created_rep_id", "")
    captured = []
    monkeypatch.setattr("jobs.partners_cli.main", lambda argv: captured.append(argv) or 0)
    return captured


def test_register_prefills_from_main_site_rep_id(monkeypatch):
    # id 47 -> name/email arrive from the roster (Enter accepts the defaults);
    # the operator types only hours; name and email were never typed
    captured = _register_io(
        monkeypatch, [_REP_47],
        "47",   # main-site sales-rep id
        "",     # partner name        (accept prefill)
        "",     # report email        (accept prefill)
        "10",   # weekly dial hours
        "",     # partner code
    )
    assert console._step_register() == 0
    assert captured == [[
        "set", "Yandex Kwon", "--hours", "10",
        "--channel", "email", "--channel-address", "kyoungd@yahoo.com",
        "--sales-rep-id", "47",
    ]]


def test_register_refuses_unknown_rep_id_loudly(monkeypatch, capsys):
    captured = _register_io(monkeypatch, [_REP_47], "99")
    assert console._step_register() != 0
    assert "99" in capsys.readouterr().out
    assert captured == []  # nothing saved


def test_register_refuses_inactive_rep(monkeypatch, capsys):
    inactive = dict(_REP_47, status="inactive")
    captured = _register_io(monkeypatch, [inactive], "47")
    assert console._step_register() != 0
    assert "inactive" in capsys.readouterr().out
    assert captured == []


def test_register_blank_id_keeps_the_manual_path(monkeypatch):
    captured = _register_io(
        monkeypatch, [_REP_47],
        "",            # blank rep id -> manual entry
        "Manual Guy",  # partner name
        "m@x.com",     # report email
        "10",          # weekly dial hours
        "",            # partner code
    )
    assert console._step_register() == 0
    assert captured == [[
        "set", "Manual Guy", "--hours", "10",
        "--channel", "email", "--channel-address", "m@x.com",
    ]]
