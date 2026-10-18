"""Built-in payment providers."""

# Import provider modules so they register themselves via @register_payment_provider.
# Each module must be importable even when its SDK is not installed.
from . import fake  # noqa: F401
from . import square_provider  # noqa: F401
from . import stripe_provider  # noqa: F401
