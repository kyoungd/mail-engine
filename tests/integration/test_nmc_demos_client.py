"""Integration pin: NmcDemosClient against a LIVE local booking-system.

The alignment this test makes executable was previously held by two docstrings
in two repos (seams/nmc_demos.py here; partner-demo.controller.ts there) and
nothing else. One read-only GET; asserts the wire CONTRACT, never the data —
an empty partner list passes (a quiet demo line is valid).

The two pins that matter to judgment/partner_report.py:
- salesRepId must be str-or-null — the report compares it AS A STRING, so a
  numeric drift would silently omit a partner's section forever.
- the four counts must be int()-parseable strings (the frozen BigInt-as-string
  convention) — that parse sits outside the report's try and would abort the
  report for EVERY partner if it drifted.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

CONTRACT_FIELDS = {
    "partnerNumber",
    "salesRepId",
    "calls",
    "uniqueProspects",
    "blockedCalls",
    "textsForwarded",
}
COUNT_FIELDS = ("calls", "uniqueProspects", "blockedCalls", "textsForwarded")


def test_summary_matches_the_seam_contract(nmc_demos):
    to = datetime.now(timezone.utc)
    partners = nmc_demos.summary(to - timedelta(days=45), to)

    assert isinstance(partners, list)
    for partner in partners:
        assert set(partner.keys()) == CONTRACT_FIELDS
        assert isinstance(partner["partnerNumber"], str)
        assert partner["salesRepId"] is None or isinstance(partner["salesRepId"], str)
        for field in COUNT_FIELDS:
            assert isinstance(partner[field], str)
            assert int(partner[field]) >= 0
