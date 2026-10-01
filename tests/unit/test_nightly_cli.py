"""The nightly runner: hands run_nightly the customer feed when it is set up.

The mail feeds, the address check, the digest, and the partner reports are gone
(contact-engine part 0, steps 3 and 4); the nightly runs with no mail setting present.
"""

import pytest

from jobs import nightly_cli

_REMOVED_SETTINGS = (
    "LOB_API_KEY", "LOB_AV_API_KEY", "POSTHOG_API_KEY", "POSTHOG_PROJECT_ID",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM",
    "NMC_BOOKING_URL", "NMC_API_KEY",
)


@pytest.fixture()
def spy(monkeypatch):
    """Capture what run_nightly is handed, without running it."""
    captured = {}

    def fake_run_nightly(dnc_registry=None, close_feed=None):
        captured["dnc_registry"] = dnc_registry
        captured["close_feed"] = close_feed

    monkeypatch.setattr(nightly_cli, "run_nightly", fake_run_nightly)
    monkeypatch.setattr(nightly_cli, "record_daily_run", lambda at: None)
    for var in _REMOVED_SETTINGS + ("MEDUSA_DATABASE_URL", "MEDUSA_READONLY_URL"):
        monkeypatch.delenv(var, raising=False)
    return captured


def test_runs_with_no_customer_feed_configured(spy, capsys):
    assert nightly_cli.main([]) == 0
    assert spy == {"dnc_registry": None, "close_feed": None}
    assert "nightly complete" in capsys.readouterr().out


def test_hands_over_the_customer_feed_when_it_is_set_up(spy, monkeypatch):
    monkeypatch.setenv("MEDUSA_READONLY_URL", "postgresql://ro@localhost/medusa_nmc")
    assert nightly_cli.main([]) == 0
    assert spy["close_feed"] is not None


def test_dry_run_reports_the_customer_feed_and_runs_nothing(spy, monkeypatch, capsys):
    assert nightly_cli.main(["--dry-run"]) == 0
    assert "customer feed: not configured" in capsys.readouterr().out

    monkeypatch.setenv("MEDUSA_READONLY_URL", "postgresql://ro@localhost/medusa_nmc")
    assert nightly_cli.main(["--dry-run"]) == 0
    assert "customer feed: configured" in capsys.readouterr().out
    assert spy == {}


def test_help_exits_zero_and_shows_usage(capsys):
    with pytest.raises(SystemExit) as exit_info:
        nightly_cli.main(["--help"])
    assert exit_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_the_nightly_runs_to_its_end_with_no_mail_setting_present(
    clean_db, monkeypatch, capsys
):
    for var in _REMOVED_SETTINGS + ("MEDUSA_DATABASE_URL", "MEDUSA_READONLY_URL"):
        monkeypatch.delenv(var, raising=False)
    assert nightly_cli.main([]) == 0
    assert "nightly complete" in capsys.readouterr().out
