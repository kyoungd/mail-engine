"""A2 (project plan): the third connection helper. Reads MEDUSA_READONLY_URL,
never reuses db/session or db/readonly; unset env → reports unavailable without
throwing (the close feed simply stays off). The close feed and the nightly CLI
resolve their connection through it — one env var, one place."""

import pytest

from db.medusa import medusa_readonly_url
from seams.nmc_closes import NmcCloseFeed

LOCAL = "postgresql://medusa_nmc_ro:pw@localhost:5432/medusa_nmc"


def test_unset_env_reports_unavailable_without_throwing(monkeypatch):
    monkeypatch.delenv("MEDUSA_READONLY_URL", raising=False)
    assert medusa_readonly_url() is None  # no throw — unavailable is a state


def test_set_env_reports_the_url(monkeypatch):
    monkeypatch.setenv("MEDUSA_READONLY_URL", LOCAL)
    assert medusa_readonly_url() == LOCAL


def test_close_feed_from_env_uses_the_readonly_var(monkeypatch):
    monkeypatch.setenv("MEDUSA_READONLY_URL", LOCAL)
    feed = NmcCloseFeed.from_env()
    assert feed._url == LOCAL  # noqa: SLF001 — pinning the wiring, not the API


def test_close_feed_from_env_refuses_when_unset(monkeypatch):
    monkeypatch.delenv("MEDUSA_READONLY_URL", raising=False)
    monkeypatch.setenv("MEDUSA_DATABASE_URL", LOCAL)  # the WRONG var must not arm it
    with pytest.raises(ValueError):
        NmcCloseFeed.from_env()
