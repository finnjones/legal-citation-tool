"""Sending email: off unless configured. Used once per credit pack, to email its code.

    RESEND_API_KEY + AGLC_EMAIL_FROM   send through Resend's HTTP API (https://resend.com)
    AGLC_EMAIL=fake                    keep messages in memory (tests and local demos)

With neither, `get_sender()` is None and nothing is sent: the success page is then the only
place a pack's code is shown, and it says so. Sending is best effort: a failure is logged
(without the address or the message) and never fails a payment.

Nothing here stores an address. The code is only in the message itself; we keep a hash of it.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass

log = logging.getLogger("aglc")

RESEND_URL = "https://api.resend.com/emails"
TIMEOUT = 10  # seconds


class EmailError(RuntimeError):
    """The email couldn't be sent."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str


class EmailSender(ABC):
    @abstractmethod
    def send(self, message: Message) -> None:
        """Send `message`; raise EmailError if it can't be."""


class ResendSender(EmailSender):
    """Resend's POST /emails, with the standard library (no extra dependency)."""

    def __init__(self, api_key: str, sender: str) -> None:
        self.api_key, self.sender = api_key, sender

    def send(self, message: Message) -> None:
        body = json.dumps({"from": self.sender, "to": [message.to], "subject": message.subject,
                           "text": message.text}).encode()
        request = urllib.request.Request(RESEND_URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
            "User-Agent": "aforecite",
        })
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if response.status >= 300:
                    raise EmailError(f"Resend answered {response.status}")
        except urllib.error.HTTPError as e:
            raise EmailError(f"Resend answered {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise EmailError(f"couldn't reach Resend: {type(e).__name__}") from None


class FakeSender(EmailSender):
    """Keeps what would have been sent, in `sent` (AGLC_EMAIL=fake)."""

    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.fail = False

    def send(self, message: Message) -> None:
        if self.fail:
            raise EmailError("fake email failure")
        self.sent.append(message)


_fake: FakeSender | None = None


def get_sender() -> EmailSender | None:
    """The configured sender, or None when email is off."""
    global _fake
    if (os.environ.get("AGLC_EMAIL") or "").strip().lower() == "fake":
        _fake = _fake or FakeSender()
        return _fake
    key, sender = (os.environ.get("RESEND_API_KEY") or "").strip(), (os.environ.get("AGLC_EMAIL_FROM") or "").strip()
    if key and sender:
        return ResendSender(key, sender)
    return None


def enabled() -> bool:
    return get_sender() is not None


def reset() -> None:
    """Forget the fake sender's messages (tests)."""
    global _fake
    _fake = None


def send_quietly(message: Message) -> bool:
    """Send if email is on; True if it was sent. Never raises, never logs the address."""
    sender = get_sender()
    if sender is None or not message.to or "@" not in message.to:
        return False
    try:
        sender.send(message)
    except EmailError as e:
        log.warning("couldn't send an email: %s", e)
        return False
    except Exception:  # noqa: BLE001 - email is never worth failing a payment over
        log.exception("couldn't send an email")
        return False
    return True
