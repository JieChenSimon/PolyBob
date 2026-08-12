"""Guard the single-source, locked uv environment contract."""

import ast
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[1]
IMPORT_NAMES = {
    "pydantic-settings": "pydantic_settings",
    "prometheus-client": "prometheus_client",
    "pyyaml": "yaml",
}


def test_uv_is_the_only_active_python_environment_source():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert (ROOT / "uv.lock").is_file()
    assert (ROOT / ".python-version").read_text().strip() == "3.11"
    assert not (ROOT / "environment.yml").exists()
    assert not list(ROOT.glob("requirements*.txt"))
    assert project["tool"]["uv"]["required-version"].startswith(">=0.11")
    assert "dev" in project["dependency-groups"]
    assert project["project"]["optional-dependencies"]["native"] == ["polybob-core"]
    assert project["tool"]["uv"]["sources"]["polybob-core"]["path"] == "rust/polybob-core"


def test_runtime_dependencies_and_packages_survive_the_migration():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert any(item.startswith("rich") for item in dependencies)
    assert any(item.startswith("requests") for item in dependencies)
    assert any(item.startswith("starlette") for item in dependencies)
    assert any(item.startswith("pytz") for item in dependencies)
    assert not any(item.startswith(("sqlalchemy", "redis", "python-dotenv")) for item in dependencies)
    assert "modules" in wheel["only-include"]
    assert "apps/dashboard/**" in wheel["exclude"]


def test_ci_and_container_install_from_the_lockfile():
    workflow = (ROOT / ".github/workflows/tests.yml").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "astral-sh/setup-uv@" in workflow
    assert "uv sync --locked" in workflow
    assert "pip install -e" not in workflow
    assert "uv sync --locked --no-dev --no-editable" in dockerfile
    assert "COPY pyproject.toml uv.lock ./" in dockerfile


def test_dashboard_akshare_uses_the_uv_environment():
    for script_name in ("start-all.sh", "start-dashboard.sh"):
        script = (ROOT / script_name).read_text()
        assert 'POLYBOB_AKSHARE_PYTHON' in script
        assert '.venv/bin/python' in script


def test_every_direct_runtime_dependency_has_usage_evidence():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    imported: set[str] = set()
    for directory in ("apps", "libs", "modules", "strategies", "scripts"):
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"import_module", "find_spec"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    imported.add(node.args[0].value.split(".")[0])

    # These are real dynamic uses that a Python AST cannot observe directly.
    dynamic_usage = {
        "akshare",  # spawned by the Next.js A-share order-book fallback
        "pytz",  # imported internally by DuckDB for timezone-aware results
    }
    missing = []
    for requirement in project["project"]["dependencies"]:
        package = re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0]
        module = IMPORT_NAMES.get(package, package.replace("-", "_"))
        if module not in imported and package not in dynamic_usage:
            missing.append(package)

    assert missing == []
