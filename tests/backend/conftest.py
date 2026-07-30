from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "mcp"))


def create_fixture_repository(root: Path) -> Path:
    repository = root / "sample-repository"
    repository.mkdir()
    (repository / "README.md").write_text(
        """\
# Sample Widgets

Install the package and call `build_widget("demo")`.

```python
from widgets import build_widget
widget = build_widget("demo")
```
""",
        encoding="utf-8",
    )
    (repository / "widgets.py").write_text(
        '''\
"""Small public widget API."""

from dataclasses import dataclass


@dataclass
class Widget:
    """A named widget returned by the factory."""

    name: str

    def render(self) -> str:
        """Render the widget as a stable string."""
        return f"widget:{self.name}"


def build_widget(name: str) -> Widget:
    """Build a Widget from a required name."""
    return Widget(name=name)
''',
        encoding="utf-8",
    )
    tests = repository / "tests"
    tests.mkdir()
    (tests / "test_widgets.py").write_text(
        """\
from widgets import build_widget


def test_build_widget():
    assert build_widget("demo").render() == "widget:demo"
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Fixture"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial fixture"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
    )
    return repository
