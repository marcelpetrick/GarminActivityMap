from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_MARKER = "<!-- project-metrics:start -->"
END_MARKER = "<!-- project-metrics:end -->"
GROUPS = {
    "Application (activity_map)": ("activity_map",),
    "Exporter (garmin_export)": ("garmin_export",),
    "Tests": ("tests",),
    "Benchmarks": ("benchmarks",),
    "Tooling scripts": ("scripts",),
}


@dataclass(frozen=True)
class GroupMetrics:
    name: str
    files: int
    lines: int
    code_lines: int
    classes: int
    functions: int
    test_functions: int


def python_files(directory: Path) -> tuple[Path, ...]:
    return tuple(sorted(path for path in directory.rglob("*.py")))


def measure(name: str, directories: Iterable[str]) -> GroupMetrics:
    files = tuple(
        path for directory in directories for path in python_files(ROOT / directory)
    )
    lines = code_lines = classes = functions = tests = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines += len(text.splitlines())
        code_lines += sum(
            1
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes += 1
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                functions += 1
                if node.name.startswith("test_"):
                    tests += 1
    return GroupMetrics(name, len(files), lines, code_lines, classes, functions, tests)


def collected_test_cases() -> int | None:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"},
            timeout=300,
        )
    except OSError, subprocess.SubprocessError:
        return None
    for line in reversed(result.stdout.splitlines()):
        if "test" in line and "collected" in line:
            for word in line.split():
                if word.isdigit():
                    return int(word)
    return None


def dependency_counts() -> tuple[int, int]:
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = len(manifest["project"]["dependencies"])
    dev = len(manifest["project"]["optional-dependencies"]["dev"])
    return runtime, dev


def pipeline_gate_count() -> int:
    script = (ROOT / "localPipeline.sh").read_text(encoding="utf-8")
    return sum(1 for line in script.splitlines() if line.startswith("run_step "))


def largest_modules(limit: int = 5) -> tuple[tuple[str, int], ...]:
    sizes = [
        (
            str(path.relative_to(ROOT)),
            len(path.read_text(encoding="utf-8").splitlines()),
        )
        for directory in ("activity_map", "garmin_export")
        for path in python_files(ROOT / directory)
    ]
    sizes.sort(key=lambda item: item[1], reverse=True)
    return tuple(sizes[:limit])


def render(collect: bool) -> str:
    groups = [measure(name, directories) for name, directories in GROUPS.items()]
    runtime, dev = dependency_counts()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    total_lines = sum(group.lines for group in groups)
    total_files = sum(group.files for group in groups)
    test_functions = sum(group.test_functions for group in groups)
    cases = collected_test_cases() if collect else None

    lines = [
        START_MARKER,
        "",
        f"Measured for version `{version}` with `python scripts/project_metrics.py`.",
        "",
        "| Area | Files | Lines | Code lines | Classes | Functions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in groups:
        lines.append(
            f"| {group.name} | {group.files} | {group.lines:,} | "
            f"{group.code_lines:,} | {group.classes} | {group.functions} |"
        )
    lines.append(
        f"| **Total** | **{total_files}** | **{total_lines:,}** | "
        f"**{sum(group.code_lines for group in groups):,}** | "
        f"**{sum(group.classes for group in groups)}** | "
        f"**{sum(group.functions for group in groups)}** |"
    )
    lines.extend(
        [
            "",
            "| Property | Value |",
            "|---|---|",
            f"| Test functions | {test_functions} |",
        ]
    )
    if cases is not None:
        lines.append(f"| Test cases collected by pytest | {cases} |")
    lines.extend(
        [
            "| Coverage threshold | 95% enforced by the pipeline |",
            f"| Quality gates | {pipeline_gate_count()} in `localPipeline.sh` |",
            f"| Runtime dependencies | {runtime}, all pinned exactly |",
            f"| Development dependencies | {dev}, all pinned exactly |",
            "| Complexity ceiling | no function above radon grade C |",
            "| Python | 3.14 |",
            "| License | GPL-3.0-or-later |",
            "",
            "Largest modules:",
            "",
            "| Module | Lines |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| `{name}` | {count:,} |" for name, count in largest_modules())
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def write_readme(section: str) -> bool:
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    if START_MARKER not in text or END_MARKER not in text:
        raise SystemExit("README.md is missing the project-metrics markers")
    head, _, rest = text.partition(START_MARKER)
    _, _, tail = rest.partition(END_MARKER)
    updated = f"{head}{section}{tail}"
    if updated == text:
        return False
    readme.write_text(updated, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report the size and shape of this project."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Update the metrics section in README.md instead of printing it.",
    )
    parser.add_argument(
        "--no-collect",
        action="store_true",
        help="Skip the pytest collection count, which needs an importable Qt.",
    )
    args = parser.parse_args(argv)

    section = render(collect=not args.no_collect)
    if args.write:
        changed = write_readme(section)
        print("README.md updated" if changed else "README.md already current")
        return 0
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
