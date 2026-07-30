"""Basic LCF demo SDK usage."""

from lcf_demo import Client

client = Client.create("https://api.example.test", timeout=5)
print(client.get("/status"))
