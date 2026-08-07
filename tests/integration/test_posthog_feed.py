"""Integration pin: PostHogFeed against the REAL PostHog project.

The nightly's web-response inflow was verified only against an injected
transport (tests/unit/test_posthog.py pins the mapping); nothing proved the
real endpoint accepts our auth and our HogQL, or that live rows survive the
mapping. This is that proof, per the tier contract: assert auth accepted,
query valid, and whatever returns maps to valid canonical Events — NEVER
specific event content, which ages out and would rot the test into a flaky.

An HTTP error from PostHog (bad key, rejected HogQL, moved endpoint) is
deliberately a test FAILURE, not a skip — configured-but-rejected is drift.
Zero events is a pass: a quiet landing page is valid.
"""

from datetime import UTC, datetime, timedelta
from itertools import islice

import pytest

from domain.enums import EventSource
from domain.taxonomy import is_valid_type

pytestmark = pytest.mark.integration

CANONICAL_TYPES = {"page.visit", "page.cta_click", "signup.completed"}
_PAGE_CAP = 1000  # one keyset page — bounds runtime without weakening assertions


def test_pull_events_matches_the_seam_contract(posthog_feed):
    since = datetime.now(UTC) - timedelta(days=45)
    events = list(islice(posthog_feed.pull_events(since), _PAGE_CAP))

    for event in events:
        assert event.source == EventSource.POSTHOG
        assert event.type in CANONICAL_TYPES and is_valid_type(event.type)
        assert event.external_id and isinstance(event.external_id, str)
        assert event.occurred_at.tzinfo is not None
        assert event.occurred_at >= since
        code = event.payload["mailer_code"]
        assert code and code != "unknown"
