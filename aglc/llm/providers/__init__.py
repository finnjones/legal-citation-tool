"""Built-in providers."""

# Import provider modules so they register themselves via @register_provider decorator.
# Each module must be importable even when its SDK is not installed.
from . import anthropic_provider  # noqa: F401
from . import fake  # noqa: F401
from . import gemini_provider  # noqa: F401
from . import openai_provider  # noqa: F401
