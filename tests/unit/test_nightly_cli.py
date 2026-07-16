"""The nightly runner: builds feeds from env and hands them to run_nightly.

FR-11 keeps the nightly job-first — it is deliberately never a web route — so this CLI
(cron's entry point) is the only way it runs. run_nightly itself is untouched: it already
takes a list of feeds.
"""

import pytest

from jobs import nightly_cli


@pytest.fixture()
def spy(monkeypatch):
    """Capture what run_nightly is handed, without running it."""
    captured = {}

    def fake_run_nightly(feeds, since, as_of=None, sender=None):
        captured["feeds"] = feeds
        captured["since"] = since

    monkeypatch.setattr(nightly_cli, "run_nightly", fake_run_nightly)
    for var in ("LOB_API_KEY", "POSTHOG_API_KEY", "POSTHOG_PROJECT_ID"):
        monkeypatch.delenv(var, raising=False)
    return captured


def test_builds_a_lob_status_feed_when_LOB_API_KEY_is_set(spy, monkeypatch, capsys):
    monkeypatch.setenv("LOB_API_KEY", "test_abc")
    assert nightly_cli.main([]) == 0
    assert [f.source for f in spy["feeds"]] == ["lob"]


def test_builds_a_posthog_feed_when_its_env_is_set(spy, monkeypatch):
    monkeypatch.setenv("LOB_API_KEY", "test_abc")
    monkeypatch.setenv("POSTHOG_API_KEY", "phx_1")
    monkeypatch.setenv("POSTHOG_PROJECT_ID", "12345")
    assert nightly_cli.main([]) == 0
    assert sorted(f.source for f in spy["feeds"]) == ["lob", "posthog"]


def test_an_unconfigured_feed_is_skipped_AND_reported(spy, monkeypatch, capsys):
    # PostHog keys are not collected yet, so this is every run today. A silent skip
    # would read as "we synced everything" when web response — currently the only
    # wired response channel — was never pulled.
    monkeypatch.setenv("LOB_API_KEY", "test_abc")
    assert nightly_cli.main([]) == 0
    assert [f.source for f in spy["feeds"]] == ["lob"]
    # one readouterr() — it drains the buffer, so calling it twice loses the second stream
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()
    assert "posthog" in output
    assert "skip" in output


def test_running_with_no_feeds_configured_fails_loudly(spy, monkeypatch):
    # run_nightly with an empty list would resolve_orphans -> recompute_state ->
    # digest.run and mail nudges computed over nothing new. nightly.py guards against
    # a feed ERROR; nothing guards against feed ABSENCE. Refuse instead.
    assert nightly_cli.main([]) != 0
    assert "feeds" not in spy


def test_since_defaults_to_a_30_day_lookback(spy, monkeypatch):
    # Overlap is free — ingestion dedupes on (source, external_id) — but a short window
    # loses scans permanently if the box was off for a few days.
    monkeypatch.setenv("LOB_API_KEY", "test_abc")
    nightly_cli.main([])
    age_days = (nightly_cli._now() - spy["since"]).days
    assert age_days == 30


def test_since_can_be_overridden(spy, monkeypatch):
    monkeypatch.setenv("LOB_API_KEY", "test_abc")
    nightly_cli.main(["--since", "2026-07-01"])
    assert spy["since"].date().isoformat() == "2026-07-01"


def test_help_exits_zero_and_shows_usage(capsys):
    with pytest.raises(SystemExit) as exit_info:
        nightly_cli.main(["--help"])
    assert exit_info.value.code == 0
    assert "usage" in capsys.readouterr().out.lower()
