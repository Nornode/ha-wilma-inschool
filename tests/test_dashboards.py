"""Tests for the shipped Lovelace dashboards."""
from pathlib import Path

import jinja2
import pytest
import yaml

DASHBOARD_DIR = Path(__file__).parent.parent / "dashboards"
DASHBOARDS = sorted(DASHBOARD_DIR.glob("*.yaml"))


def _markdown_contents(node):
    """Yield every markdown card template found in a dashboard config."""
    if isinstance(node, dict):
        if node.get("type") == "markdown" and isinstance(node.get("content"), str):
            yield node["content"]
        for value in node.values():
            yield from _markdown_contents(value)
    elif isinstance(node, list):
        for value in node:
            yield from _markdown_contents(value)


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_dashboard_yaml_is_valid(path: Path):
    """Each dashboard parses and defines views."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert "views" in config
    assert config["views"]


@pytest.mark.parametrize("path", DASHBOARDS, ids=lambda p: p.name)
def test_dashboard_templates_compile(path: Path):
    """Markdown card templates are valid Jinja."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    env = jinja2.Environment()

    contents = list(_markdown_contents(config))
    assert contents

    for content in contents:
        env.parse(content)
