"""The test suite must never run against production.

`clean_db` truncates all six tables against whatever OWNER_DATABASE_URL resolves to,
and conftest reads that from the .env of whichever folder pytest was invoked in. In
the mail-engine-production folder that is mailengine_prod — so `make test` there is a
production data-loss path. Events are append-only and every derived fact recomputes
from them (FR-7), so the loss is not repairable from within the system.

This pins the predicate that refuses. Fail-closed: anything we do not positively
recognise as a test environment is treated as production, because the cost of a wrong
"safe" is the event history and the cost of a wrong "unsafe" is a typo in .env.
"""

from tests.guard import unsafe_test_environment

DEV = "postgresql://me_user:pw@localhost:5432/mailengine_dev"
PROD = "postgresql://me_user:pw@localhost:5432/mailengine_prod"
# The guard keys only on the `live_`/`test_` prefix (never the body), so these fake
# stand-ins exercise it exactly like real keys — and no real secret lands in git.
TEST_KEY = "test_not_a_real_key_used_only_in_this_guard_test"
LIVE_KEY = "live_not_a_real_key_used_only_in_this_guard_test"


def test_dev_database_with_test_key_is_the_one_safe_combination():
    assert unsafe_test_environment(DEV, TEST_KEY) is None


def test_mailengine_test_is_also_allowed():
    assert unsafe_test_environment(DEV.replace("_dev", "_test"), TEST_KEY) is None


def test_production_database_refuses():
    problem = unsafe_test_environment(PROD, TEST_KEY)
    assert problem is not None
    assert "mailengine_prod" in problem  # name what was refused, so the human can act


def test_live_key_refuses_even_against_the_dev_database():
    # Independent check, not a belt-and-braces duplicate: a live key means someone
    # pointed a test run at real money regardless of which DB it would truncate.
    problem = unsafe_test_environment(DEV, LIVE_KEY)
    assert problem is not None
    assert "live" in problem.lower()


def test_unrecognised_database_refuses_rather_than_assuming_safe():
    problem = unsafe_test_environment(
        "postgresql://u:p@localhost:5432/mailengine_staging", TEST_KEY
    )
    assert problem is not None


def test_missing_database_url_refuses():
    assert unsafe_test_environment("", TEST_KEY) is not None


def test_missing_lob_key_is_safe_when_the_database_is_a_test_database():
    # An unset Lob key cannot spend money; it must not block the dev suite.
    assert unsafe_test_environment(DEV, "") is None


def test_url_with_query_params_and_trailing_slash_still_parses():
    assert unsafe_test_environment(DEV + "?sslmode=disable", TEST_KEY) is None
    assert unsafe_test_environment(PROD + "?sslmode=disable", TEST_KEY) is not None
