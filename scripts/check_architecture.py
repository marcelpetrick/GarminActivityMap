from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("activity_map", "garmin_export")
FORBIDDEN_IMPORTS = {
    "activity_map.models": {"activity_map.app", "activity_map.widgets"},
    "activity_map.geo": {
        "activity_map.app",
        "activity_map.loader",
        "activity_map.render",
        "activity_map.tiles",
        "activity_map.widgets",
    },
    "activity_map.loader": {
        "activity_map.app",
        "activity_map.render",
        "activity_map.tiles",
        "activity_map.widgets",
    },
    "activity_map.render": {
        "activity_map.app",
        "activity_map.loader",
        "activity_map.tiles",
        "activity_map.widgets",
    },
}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def local_imports(path: Path) -> set[str]:
    module = module_name(path)
    package = module.split(".", 1)[0]
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name
                for alias in node.names
                if alias.name.split(".", 1)[0] in PACKAGES
            )
        elif isinstance(node, ast.ImportFrom):
            imported = resolve_import_from(package, module, node)
            if imported is not None and imported.split(".", 1)[0] in PACKAGES:
                imports.add(imported)
    return imports


def resolve_import_from(
    package: str,
    module: str,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module
    parts = module.split(".")[: -node.level]
    if not parts:
        parts = [package]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def python_modules() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for package in PACKAGES
            for path in (ROOT / package).glob("*.py")
            if path.name != "__main__.py"
        )
    )


def dependency_graph(paths: Iterable[Path]) -> dict[str, set[str]]:
    modules = {module_name(path) for path in paths}
    return {
        module_name(path): {
            dependency for dependency in local_imports(path) if dependency in modules
        }
        for path in paths
    }


def find_cycle(graph: dict[str, set[str]]) -> tuple[str, ...] | None:
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> tuple[str, ...] | None:
        if module in active:
            start = active.index(module)
            return tuple([*active[start:], module])
        if module in visited:
            return None
        active.append(module)
        for dependency in graph[module]:
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        active.pop()
        visited.add(module)
        return None

    for module in graph:
        cycle = visit(module)
        if cycle is not None:
            return cycle
    return None


def architecture_errors(graph: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
    for module, forbidden in FORBIDDEN_IMPORTS.items():
        for dependency in sorted(graph.get(module, set()) & forbidden):
            errors.append(f"{module} must not import {dependency}")
    for module, dependencies in graph.items():
        other_package = (
            "garmin_export" if module.startswith("activity_map") else "activity_map"
        )
        for dependency in sorted(dependencies):
            if dependency.startswith(other_package):
                errors.append(f"{module} must not import {dependency}")
    cycle = find_cycle(graph)
    if cycle is not None:
        errors.append(f"cyclic dependency: {' -> '.join(cycle)}")
    return errors


def main() -> int:
    graph = dependency_graph(python_modules())
    errors = architecture_errors(graph)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Architecture checks passed for {len(graph)} modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
