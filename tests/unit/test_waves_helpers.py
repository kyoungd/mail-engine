"""Pure-helper unit tests for service/waves.py — no DB, no I/O."""

from service.waves import _state_hash


def test_state_hash_folds_in_creative_checksums():
    ids, split = ["a", "b"], {"v1": 1.0}
    # A creative change (same audience, same split) must move the hash — this is what
    # makes "approve exactly what you proofed" cover the creative, not just the audience.
    assert _state_hash(ids, split, {"v1": "chk-A"}) != _state_hash(ids, split, {"v1": "chk-B"})
    # ...and it is stable for identical inputs.
    assert _state_hash(ids, split, {"v1": "chk-A"}) == _state_hash(ids, split, {"v1": "chk-A"})
