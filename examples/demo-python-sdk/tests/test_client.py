from __future__ import annotations

import pytest
from lcf_demo import Client


def test_create_and_describe_get() -> None:
    client = Client.create("https://api.example.test/", timeout=5)

    request = client.get("status")

    assert request.method == "GET"
    assert request.url == "https://api.example.test/status"
    assert request.timeout == 5.0


@pytest.mark.parametrize("timeout", [0, -1])
def test_timeout_must_be_positive(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be positive"):
        Client.create("https://api.example.test", timeout=timeout)
