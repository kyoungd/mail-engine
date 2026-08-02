"""C1: the real Sender's mechanics — subject-from-first-line, recipient
resolution, loud channel failures, and the env-gated construction (dark when
SMTP env is absent, like every unconfigured seam)."""

import pytest

from jobs.nightly_cli import _build_sender
from seams.email_sender import EmailSender


class _Smtp:
    instances: list["_Smtp"] = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.calls: list[tuple] = []
        _Smtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message))


@pytest.fixture(autouse=True)
def _reset():
    _Smtp.instances = []


def _sender(resolve):
    return EmailSender(
        host="smtp.example.com", port=587, user="u@x.com", password="pw",
        resolve=resolve, transport=_Smtp,
    )


def test_first_line_becomes_the_subject_rest_the_body():
    sender = _sender(lambda f: ("email", "john@example.com", "John"))
    sender.send("some-id", "Your NeverMissCall partner report — 2026-08-01\n\nYour list\n...")

    (smtp,) = _Smtp.instances
    assert ("starttls",) in smtp.calls and ("login", "u@x.com", "pw") in smtp.calls
    message = next(c[1] for c in smtp.calls if c[0] == "send")
    assert message["Subject"] == "Your NeverMissCall partner report — 2026-08-01"
    assert message["To"] == "john@example.com"
    assert message.get_content().startswith("Your list")


@pytest.mark.parametrize("channel,address", [
    (None, None),
    ("sms", "+18185551234"),   # no arbitrary-send NMC SMS API exists
    ("email", None),
    ("carrier_pigeon", "x@y"),
])
def test_unmappable_channels_fail_loud_before_any_smtp(channel, address):
    sender = _sender(lambda f: (channel, address, "P"))
    with pytest.raises(RuntimeError):
        sender.send("some-id", "subject\nbody")
    assert _Smtp.instances == []  # never reached the wire


def test_build_sender_is_dark_without_smtp_env(monkeypatch):
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"):
        monkeypatch.delenv(var, raising=False)
    assert _build_sender() is None

    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USER", "young@nevermisscall.com")
    monkeypatch.setenv("SMTP_PASS", "app-password")
    sender = _build_sender()
    assert isinstance(sender, EmailSender)
    assert sender.port == 587  # STARTTLS default
    assert sender.from_addr == "young@nevermisscall.com"  # defaults to SMTP_USER
