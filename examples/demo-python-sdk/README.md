# LCF Demo SDK

This tiny repository is safe, deterministic input for Local Context Forge.

```python
from lcf_demo import Client

client = Client.create(
    base_url="https://api.example.test",
    timeout=5.0,
)
result = client.get("/status")
```

`Client.create` validates that `timeout` is positive. `Client.get` returns a
small request description instead of performing network I/O, so examples and
tests are deterministic.
