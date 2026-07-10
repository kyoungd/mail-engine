"""E.164 normalization — the one shared function the identity-resolution chain
depends on (data document §3). US-only, matching NMC's single-timezone model:
a 10-digit number becomes +1XXXXXXXXXX; anything else is not a phone we can key on."""

import re


def to_e164(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"
