"""The address-verification seam (Lob US Address Verification). Anti-corruption
boundary: the vendor's payload shapes and error types never leak above this module.

Per the dependency rule (`direct-mail-ai-code-layout.md`), `seams` is imported only by
`jobs` and `service/execution` — `load_list` cannot call this, which is precisely why
verification is a job (`verify_addresses`) rather than part of ingest, and why
NCOA/CASS was never in `load_list`. Design: `ingest-contact-migration.md` §5.

The failure model is pinned by §5 and is the whole reason `AddressVerificationError`
exists as a distinct type:

  - a **verdict** is a result — including `undeliverable` and "no delivery point".
    The caller stamps `std_verified_at` and never calls again for that row. USPS data
    shifts; the snapshot is what keeps audience resolution reproducible.
  - an **error** (timeout, 5xx, rate limit) stamps nothing. The row stays
    `std_verified_at is null` and the NEXT job run retries it. No per-call retry loop,
    and no permanent consumption of the "once" by a transient failure.

A row that errors forever is visible as ever-unverified, and unverified rows are never
excluded from an audience (§6) — they are merely not yet deduplicable.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# The verdict enum, verbatim from the vendor (§5, verified 2026-07-27). Stored as-is in
# `deliverability`. §6 pins that only `undeliverable` excludes — the three
# `deliverable_*_unit` variants are deliverable-family, because CSLB data is spotty on
# unit numbers and dropping them would cost real reach for no deliverability gain.
DELIVERABLE = "deliverable"
DELIVERABLE_MISSING_UNIT = "deliverable_missing_unit"
DELIVERABLE_INCORRECT_UNIT = "deliverable_incorrect_unit"
DELIVERABLE_UNNECESSARY_UNIT = "deliverable_unnecessary_unit"
UNDELIVERABLE = "undeliverable"

VERDICTS = frozenset(
    {
        DELIVERABLE,
        DELIVERABLE_MISSING_UNIT,
        DELIVERABLE_INCORRECT_UNIT,
        DELIVERABLE_UNNECESSARY_UNIT,
        UNDELIVERABLE,
    }
)

#: The only verdict that removes a contact from an audience (§6).
EXCLUDING_VERDICTS = frozenset({UNDELIVERABLE})


class AddressVerificationError(Exception):
    """A vendor *error*, not a verdict: timeout, 5xx, rate limit, malformed response.

    The caller must stamp nothing and leave the row for the next run. Raising this for
    an undeliverable address would be a category error — that is a result.
    """


@dataclass(frozen=True, kw_only=True)
class VerificationResult:
    """One row's verification outcome, in our vocabulary rather than the vendor's."""

    deliverability: str  # one of VERDICTS, stored verbatim
    delivery_point: str  # USPS delivery-point barcode; "" = no delivery point (§5)
    std_addr_line1: str = ""
    std_addr_line2: str = ""
    std_addr_city: str = ""
    std_addr_state: str = ""
    std_addr_zip: str = ""  # ZIP+4

    @property
    def has_components(self) -> bool:
        """The §5 inherit step runs only over deliverable-with-components rows: any
        other outcome leaves the contact's raw picked address alone, because the raw
        address is the better fact when standardization failed."""
        return bool(self.std_addr_line1 and self.std_addr_city and self.std_addr_zip)


@runtime_checkable
class AddressVerifier(Protocol):
    """Verify one address. Raises `AddressVerificationError` on a vendor error; returns
    a `VerificationResult` for every verdict, including undeliverable."""

    def verify(self, address: dict[str, str]) -> VerificationResult: ...
