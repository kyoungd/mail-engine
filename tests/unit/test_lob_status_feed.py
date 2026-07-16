"""The Lob status feed: postcard tracking events -> canonical events (FR-5's delivery
half, polled instead of pushed). Transport is injected — no network.

Polling, not webhooks: production runs locally, so Lob cannot reach it inbound; the only
consumer of these events is the nightly judgment job, so real-time buys nothing; and a
poll is robust to downtime where a missed webhook is gone forever. See decisions.md.

⚠️ The `name` strings below are Lob's, verified against their OpenAPI spec
(shared/resources/tracking_events/models/tracking_event_normal.yml) — they are NOT the
webhook's event ids. The webhook keys on `postcard.processed_for_delivery`; a tracking
event keys on `Processed for Delivery`. Same fact, different string.
"""

from datetime import UTC, datetime

from domain.enums import EventSource
from seams.lob_status import LobStatusFeed

SINCE = datetime(2026, 7, 5, 0, 0, 0, tzinfo=UTC)


def _postcard(pid, code, events):
    return {
        "id": pid,
        "metadata": {"mailer_code": code} if code else {},
        "tracking_events": events,
    }


def _te(eid, name, time):
    return {
        "id": eid,
        "object": "tracking_event",
        "type": "normal",
        "name": name,
        "time": time,
        "location": "92069",
    }


def _feed(pages):
    calls = []

    def transport(url, headers):
        calls.append((url, headers))
        page = pages.pop(0)
        return page

    return LobStatusFeed("test_key", transport=transport), calls


def _page(postcards, next_url=None):
    return {"object": "list", "data": postcards, "next_url": next_url, "count": len(postcards)}


def test_processed_for_delivery_becomes_piece_delivered():
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [_te("evnt_1", "Processed for Delivery", "2026-07-06T10:00:00Z")],
                    )
                ]
            )
        ]
    )
    (event,) = list(feed.pull_events(SINCE))
    assert event.source == EventSource.LOB
    assert event.type == "piece.delivered"
    assert event.payload["mailer_code"] == "abc123"


def test_returned_to_sender_becomes_piece_returned():
    # the signal FR-10's returned-mail rule needs; without it a dead address is invisible
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [_te("evnt_9", "Returned to Sender", "2026-07-06T10:00:00Z")],
                    )
                ]
            )
        ]
    )
    (event,) = list(feed.pull_events(SINCE))
    assert event.type == "piece.returned"


def test_unmapped_tracking_events_are_ignored():
    # Lob emits eight names; the closed taxonomy (FR-5) takes two.
    ignored = [
        "Mailed",
        "In Transit",
        "In Local Area",
        "Delivered",
        "Re-Routed",
        "International Exit",
    ]
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [
                            _te(f"evnt_{i}", n, "2026-07-06T10:00:00Z")
                            for i, n in enumerate(ignored)
                        ],
                    )
                ]
            )
        ]
    )
    assert list(feed.pull_events(SINCE)) == []


def test_external_id_is_the_tracking_event_id_not_the_postcard_id():
    # One postcard earns BOTH events over its life. Keying on psc_ would collide and
    # ingestion's (source, external_id) dedupe would silently swallow the second.
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [
                            _te("evnt_delivered", "Processed for Delivery", "2026-07-06T10:00:00Z"),
                            _te("evnt_returned", "Returned to Sender", "2026-07-09T10:00:00Z"),
                        ],
                    )
                ]
            )
        ]
    )
    events = list(feed.pull_events(SINCE))
    assert [e.external_id for e in events] == ["evnt_delivered", "evnt_returned"]


def test_events_before_since_are_not_yielded():
    # Filters on the tracking event's `time` (when USPS scanned), NOT the postcard's
    # date_created — a two-week-old piece can still earn a scan today, so filtering by
    # postcard age would go blind on most of the mail.
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [
                            _te("evnt_old", "Processed for Delivery", "2026-07-01T10:00:00Z"),
                            _te("evnt_new", "Returned to Sender", "2026-07-06T10:00:00Z"),
                        ],
                    )
                ]
            )
        ]
    )
    events = list(feed.pull_events(SINCE))
    assert [e.external_id for e in events] == ["evnt_new"]


def test_repolling_yields_the_same_external_ids():
    # replay-safety (SR-4): overlapping pulls are free because the evnt_ id is stable.
    page = _page(
        [
            _postcard(
                "psc_1", "abc123", [_te("evnt_1", "Processed for Delivery", "2026-07-06T10:00:00Z")]
            )
        ]
    )
    feed_a, _ = _feed([page])
    feed_b, _ = _feed([dict(page)])
    assert [e.external_id for e in feed_a.pull_events(SINCE)] == [
        e.external_id for e in feed_b.pull_events(SINCE)
    ]


def test_pagination_follows_next_url_until_exhausted():
    feed, calls = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_1",
                        "abc123",
                        [_te("evnt_1", "Processed for Delivery", "2026-07-06T10:00:00Z")],
                    )
                ],
                next_url="https://api.lob.com/v1/postcards?limit=100&after=CURSOR",
            ),
            _page(
                [
                    _postcard(
                        "psc_2",
                        "def456",
                        [_te("evnt_2", "Returned to Sender", "2026-07-07T10:00:00Z")],
                    )
                ]
            ),
        ]
    )
    events = list(feed.pull_events(SINCE))
    assert [e.external_id for e in events] == ["evnt_1", "evnt_2"]
    assert len(calls) == 2
    assert "after=CURSOR" in calls[1][0]


def test_postcards_without_a_mailer_code_are_skipped():
    # Dashboard-created / foreign postcards are not ours. Yielding them would flood the
    # orphan queue with pieces this system never mailed (the PostHog 'unknown' precedent).
    feed, _ = _feed(
        [
            _page(
                [
                    _postcard(
                        "psc_foreign",
                        None,
                        [_te("evnt_1", "Processed for Delivery", "2026-07-06T10:00:00Z")],
                    )
                ]
            )
        ]
    )
    assert list(feed.pull_events(SINCE)) == []
