"""Provider-agnostic payments interface.

The billing code only ever sees `PaymentProvider`. Switching from Square to another
hosted checkout (Stripe Checkout is the fallback) means writing one small subclass and
registering it; billing, the store and the web page don't change.

The provider is chosen with $AGLC_PAYMENTS (eg `square`, or `fake` for tests). When it is
unset, payments are off and the tool behaves exactly as it does locally: no paywall,
no quotas, no database.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal


class PaymentError(RuntimeError):
    """The payment provider failed or rejected a request."""


class WebhookSignatureError(ValueError):
    """A webhook's signature is missing or doesn't match; the request must be rejected."""


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    amount: int  # minor units (cents)
    currency: str

    @property
    def display(self) -> str:
        dollars = self.amount / 100
        symbol = "A$" if self.currency == "AUD" else f"{self.currency} "
        return f"{symbol}{dollars:g}" if dollars == int(dollars) else f"{symbol}{dollars:.2f}"


@dataclass(frozen=True)
class CheckoutSession:
    """A hosted checkout page the customer is redirected to."""

    checkout_id: str
    url: str
    provider_order_id: str  # the provider's id for what is being paid for (Square: the order id)


@dataclass(frozen=True)
class PaymentStatus:
    """What the provider says about a checkout when asked directly (see `retrieve`)."""

    paid: bool
    amount: int = 0
    currency: str = ""
    payment_id: str | None = None


@dataclass(frozen=True)
class WebhookEvent:
    """A verified webhook, reduced to what billing needs."""

    event_id: str
    type: str
    status: Literal["paid", "refunded", "ignored"]
    provider_order_id: str | None = None
    payment_id: str | None = None
    amount: int = 0
    currency: str = ""


@dataclass(frozen=True)
class Refund:
    refund_id: str
    status: str


class PaymentProvider(ABC):
    """A hosted checkout. Card details never reach this server."""

    #: registry name, eg "square"
    name: str = ""

    @abstractmethod
    def create_checkout(self, *, order_id: str, product: Product, redirect_url: str) -> CheckoutSession:
        """Create a hosted checkout for one `product`. `order_id` is our order id; providers
        store it as the reference on their side and use it for idempotency."""

    @abstractmethod
    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str], url: str) -> WebhookEvent:
        """Verify the signature of a webhook (raising `WebhookSignatureError`) and parse it.
        `body` is the raw request body, exactly as received; `url` is the notification URL."""

    @abstractmethod
    def retrieve(self, provider_order_id: str) -> PaymentStatus:
        """Ask the provider whether a checkout has been paid (for when the webhook is late)."""

    @abstractmethod
    def refund(self, *, payment_id: str, amount: int, currency: str, reason: str, idempotency_key: str) -> Refund:
        """Refund a payment in full."""

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}>"


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, Callable[..., PaymentProvider]] = {}
_INSTANCES: dict[str, PaymentProvider] = {}


def register_payment_provider(name: str) -> Callable[[type[PaymentProvider]], type[PaymentProvider]]:
    def deco(cls: type[PaymentProvider]) -> type[PaymentProvider]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def available_payment_providers() -> list[str]:
    _load_builtin_providers()
    return sorted(_REGISTRY)


def configured_payment_provider() -> str | None:
    """$AGLC_PAYMENTS, or None when payments are off."""
    return (os.environ.get("AGLC_PAYMENTS") or "").strip().lower() or None


def get_payment_provider(name: str | None = None, **options: Any) -> PaymentProvider:
    """The provider named `name` (default: $AGLC_PAYMENTS). One instance per name is kept, so
    clients and the fake provider's state are shared between requests."""
    _load_builtin_providers()
    name = name or configured_payment_provider()
    if not name:
        raise PaymentError("Payments are off (set AGLC_PAYMENTS)")
    if name not in _INSTANCES or options:
        try:
            factory = _REGISTRY[name]
        except KeyError:
            raise ValueError(
                f"Unknown payment provider {name!r}. Available: {', '.join(sorted(_REGISTRY))}"
            ) from None
        _INSTANCES[name] = factory(**options)
    return _INSTANCES[name]


def reset_payment_providers() -> None:
    """Forget provider instances (tests, or after changing settings)."""
    _INSTANCES.clear()


def _load_builtin_providers() -> None:
    # Imported lazily so that vendor SDKs are only required when used.
    from . import providers  # noqa: F401
