"""The PostHog feed client: HogQL query shape, auth, event mapping to the canonical
taxonomy, keyset pagination. Transport is injected — no network."""

from datetime import UTC, datetime

import seams.posthog as posthog_seam
from seams.posthog import PostHogFeed

SINCE = datetime(2026, 7, 5, 0, 0, 0, tzinfo=UTC)

ROWS = [
    ["uuid-1", "$pageview", "2026-07-06T10:00:00+00:00", "k7m2xq3vhp", None, None],
    ["uuid-2", "checkout_started", "2026-07-06T10:05:00+00:00", "k7m2xq3vhp", "pro", None],
    ["uuid-3", "landing_purchase_completed", "2026-07-06T10:09:00+00:00", "k7m2xq3vhp",
     "pro", 199.0],
]


def _feed(pages):
    calls = []

    def transport(url, body, headers):
        calls.append((url, body, headers))
        return {"results": pages.pop(0)}

    return PostHogFeed("phx_personal", "12345", transport=transport), calls


def test_query_hits_project_endpoint_with_bearer_key():
    feed, calls = _feed([ROWS])
    list(feed.pull_events(SINCE))
    (url, body, headers), = calls
    assert url == "https://us.posthog.com/api/projects/12345/query/"
    assert headers["Authorization"] == "Bearer phx_personal"
    assert b"HogQLQuery" in body
    assert b"mailer_code is not null" in body
    # the landing page's no-code sentinel must be excluded, or organic traffic
    # floods the orphan queue
    assert b"mailer_code != 'unknown'" in body
    assert b"2026-07-05" in body


def test_maps_posthog_events_to_canonical_taxonomy():
    feed, _ = _feed([ROWS])
    events = list(feed.pull_events(SINCE))

    assert [e.type for e in events] == ["page.visit", "page.cta_click", "signup.completed"]
    assert [e.external_id for e in events] == ["uuid-1", "uuid-2", "uuid-3"]
    assert all(e.source == "posthog" for e in events)
    assert all(e.payload["mailer_code"] == "k7m2xq3vhp" for e in events)
    assert events[0].payload == {"mailer_code": "k7m2xq3vhp"}  # no null tier/amount keys
    assert events[2].payload == {"mailer_code": "k7m2xq3vhp", "tier": "pro", "amount": 199.0}
    assert events[0].occurred_at == datetime(2026, 7, 6, 10, 0, tzinfo=UTC)


def test_keyset_pagination_advances_cursor_from_last_row(monkeypatch):
    monkeypatch.setattr(posthog_seam, "_PAGE_SIZE", 2)
    feed, calls = _feed([ROWS[:2], ROWS[2:]])
    events = list(feed.pull_events(SINCE))

    assert len(events) == 3
    assert len(calls) == 2  # second page short -> stop
    assert b"'2026-07-06T10:05:00+00:00', 'uuid-2'" in calls[1][1]  # cursor = page-1 tail
