"""The integration tier's plumbing (CLAUDE.md § The test surface).

Read-only across every boundary and truncates nothing — no test here may
request `clean_db` or write through any connection. Each seam fixture resolves
its dependency from the environment: unconfigured or unreachable ⇒ skip with a
loud reason (fail under --integration-strict); reachable-but-wrong-shape ⇒ the
test itself fails. The terminal summary prints covered/skipped so a
silently-all-skipped run cannot read as green coverage.
"""

import os
import urllib.error
import urllib.request

import pytest

from seams.nmc_demos import NmcDemosClient

_PROBE_TIMEOUT_SECONDS = 3.0


def _skip_or_fail(config: pytest.Config, reason: str) -> None:
    if config.getoption("--integration-strict"):
        pytest.fail(f"--integration-strict: would have skipped — {reason}", pytrace=False)
    pytest.skip(reason)


@pytest.fixture(scope="session")
def nmc_demos(request: pytest.FixtureRequest) -> NmcDemosClient:
    url = os.environ.get("NMC_BOOKING_URL", "")
    key = os.environ.get("NMC_API_KEY", "")
    if not url or not key:
        _skip_or_fail(
            request.config,
            "NMC_BOOKING_URL / NMC_API_KEY not set in .env — "
            "point them at the local booking-system to cover this seam",
        )
    try:
        urllib.request.urlopen(url, timeout=_PROBE_TIMEOUT_SECONDS)
    except urllib.error.HTTPError:
        pass  # any HTTP response means the server is up; the test does the real GET
    except OSError as exc:
        _skip_or_fail(
            request.config,
            f"booking-system not reachable at {url} — start it and re-run ({exc})",
        )
    return NmcDemosClient(url, key)


def pytest_terminal_summary(terminalreporter) -> None:
    def ours(outcome: str) -> list:
        return [
            report
            for report in terminalreporter.stats.get(outcome, [])
            if report.nodeid.startswith("tests/integration/")
        ]

    passed, failed, skipped = ours("passed"), ours("failed"), ours("skipped")
    if not (passed or failed or skipped):
        return
    terminalreporter.write_sep("-", "integration seams")
    terminalreporter.write_line(
        f"covered: {len(passed)} / skipped: {len(skipped)} / failed: {len(failed)}"
    )
    for report in skipped:
        longrepr = report.longrepr
        reason = longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)
        terminalreporter.write_line(f"  skipped {report.nodeid}: {reason}")
