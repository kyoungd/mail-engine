"""The real `Sender` (Stage C1 — closes TD-10): SMTP email via the house Gmail
pattern (root PRD § Shared Credentials; `SMTP_*` env in mail-engine's `.env`).

`send(founder, message)` receives the recipient as an opaque partner-id key (the
digest and the report both pass `str(partners.id)`), so this seam needs a
recipient → channel map: the partner row's `channel` + `channel_address`. The
default resolver reads that row; tests inject their own. Design rule 3 is the
whole failure model: a null, unknown, or `sms` channel FAILS LOUDLY — a silent
skip is a partner nudge dropped on the floor, and no NMC arbitrary-send SMS API
exists (booking-system texts only inside Twilio conversations), so `sms` means
unbuilt integration, not a quiet fallback.

Subject convention: the FIRST LINE of the message is the subject; the rest is the
body. Both callers compose a headline first line already.
"""

import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any
from uuid import UUID


def _db_resolver(founder: str) -> tuple[str | None, str | None, str]:
    """The default recipient map: the partner row. Injectable for tests."""
    from db.session import transaction

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select channel, channel_address, name from partners where id = %s",
                (UUID(founder),),
            )
            row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"EmailSender: no partners row for recipient {founder!r}")
    return row[0], row[1], row[2]


class EmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str | None = None,
        resolve: Callable[[str], tuple[str | None, str | None, str]] | None = None,
        # duck-typed: anything context-managing with starttls/login/send_message
        transport: Callable[..., Any] = smtplib.SMTP,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr or user
        self._resolve = resolve or _db_resolver
        self._transport = transport

    def send(self, founder: str, message: str) -> None:
        channel, address, name = self._resolve(founder)
        if channel != "email" or not address:
            # Loud by design (S-7 / design rule 3): an unmapped partner is a silent
            # drop of exactly the nudges this seam exists to route.
            raise RuntimeError(
                f"EmailSender: partner {name!r} ({founder}) has channel="
                f"{channel!r}, address={address!r} — cannot deliver; 'sms' has no "
                "send path (no arbitrary-send NMC SMS API exists)"
            )

        subject, _, body = message.partition("\n")
        email = EmailMessage()
        email["From"] = self.from_addr
        email["To"] = address
        email["Subject"] = subject.strip()
        email.set_content(body.lstrip("\n"))

        with self._transport(self.host, self.port) as smtp:
            smtp.starttls()
            smtp.login(self.user, self.password)
            smtp.send_message(email)
