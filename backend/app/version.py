"""Canonical backend product and protocol versions.

The Python distribution uses its PEP 440 spelling in ``pyproject.toml`` while
runtime API surfaces use the product spelling.
"""

APP_VERSION = "0.3.0-alpha.1"
PYTHON_DISTRIBUTION_VERSION = "0.3.0a1"

DESKTOP_PROTOCOL_MAJOR = "1"
DESKTOP_PROTOCOL_MINOR = "0"
DESKTOP_PROTOCOL_VERSION = (
    f"{DESKTOP_PROTOCOL_MAJOR}.{DESKTOP_PROTOCOL_MINOR}"
)

