"""Ernest — a personal chief-of-staff agent (read-only core)."""

__version__ = "0.1.0"


class ErnestError(Exception):
    """Base class for Ernest's own errors."""


class ConfigError(ErnestError):
    """A required configuration value is missing or malformed."""
