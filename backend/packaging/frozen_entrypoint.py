"""Audited PyInstaller entry point for the desktop Python sidecar."""

from app.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
