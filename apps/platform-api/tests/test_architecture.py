import ast
from pathlib import Path

MODULES = {
    "source",
    "knowledge",
    "operations",
    "audit",
    "search",
    "relations",
    "graph",
    "governance",
    "journal_metrics",
    "scholars",
}
ROOT = Path(__file__).parents[1] / "src" / "smartlib_platform"


def test_domain_modules_do_not_import_each_other() -> None:
    violations: list[str] = []
    for module in MODULES:
        for path in (ROOT / module).glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                imported = ""
                if isinstance(node, ast.ImportFrom):
                    imported = node.module or ""
                elif isinstance(node, ast.Import):
                    imported = ",".join(alias.name for alias in node.names)
                for other in MODULES - {module}:
                    if f"smartlib_platform.{other}" in imported:
                        violations.append(f"{path.name}: {module} -> {other}")
    assert violations == []


def test_domain_modules_do_not_depend_on_entrypoints() -> None:
    for module in MODULES | {"foundation"}:
        contents = "\n".join(path.read_text() for path in (ROOT / module).glob("*.py"))
        assert "smartlib_platform.entrypoints" not in contents
