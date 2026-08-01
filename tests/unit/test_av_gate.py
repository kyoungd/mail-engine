"""The AV gate (approved 2026-08-01): address verification is armed ONLY by the
dedicated LOB_AV_API_KEY — the print key must never arm it.

The hazard this closes: `LOB_API_KEY` (the print key) is set in BOTH .envs, so
before this gate a hand-run nightly would sweep every intake row — with the test
key in dev (permanent canned `undeliverable` on all 102k rows, every audience
emptied) or the live key in prod (~$5.1k of uncapped lookups). Verdicts are
never re-asked, so the dev outcome would be effectively irreversible."""

import pytest

from jobs.nightly_cli import _build_verifier
from seams.lob_address import LobAddressVerifier


def test_print_key_alone_does_not_arm_verification(monkeypatch):
    monkeypatch.setenv("LOB_API_KEY", "test_abc")        # print key present
    monkeypatch.delenv("LOB_AV_API_KEY", raising=False)  # AV gate closed
    assert _build_verifier() is None                     # nightly: sweep skipped
    with pytest.raises(ValueError):
        LobAddressVerifier.from_env()                    # manual CLI: refuses


def test_av_key_arms_verification(monkeypatch):
    monkeypatch.setenv("LOB_AV_API_KEY", "live_xyz")
    verifier = _build_verifier()
    assert isinstance(verifier, LobAddressVerifier)
    assert verifier.api_key == "live_xyz"
    assert LobAddressVerifier.from_env().api_key == "live_xyz"
