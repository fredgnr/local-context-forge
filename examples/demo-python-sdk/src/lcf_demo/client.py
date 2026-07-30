"""A deterministic client used to demonstrate API documentation generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequestDescription:
    """A network-free description of a request."""

    method: str
    url: str
    timeout: float


@dataclass(frozen=True, slots=True)
class Client:
    """Client configuration shared by all request descriptions."""

    base_url: str
    timeout: float = 30.0

    @classmethod
    def create(cls, base_url: str, *, timeout: float = 30.0) -> Client:
        """Create a client.

        Args:
            base_url: Absolute service URL without a required trailing slash.
            timeout: Positive request timeout in seconds.

        Raises:
            ValueError: If ``base_url`` is empty or ``timeout`` is not positive.
        """

        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        return cls(base_url=normalized, timeout=float(timeout))

    def get(self, path: str) -> RequestDescription:
        """Describe a GET request without executing network I/O."""

        normalized_path = "/" + path.lstrip("/")
        return RequestDescription(
            method="GET",
            url=f"{self.base_url}{normalized_path}",
            timeout=self.timeout,
        )
