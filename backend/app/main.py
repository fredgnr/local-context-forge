"""Legacy ASGI module.

Docker and source-mode uvicorn continue to import ``app.main:app``. Desktop
sidecars import the factory directly so they do not construct this global
legacy service first.
"""

from .factory import create_app

app = create_app()

__all__ = ["app", "create_app"]
