from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_metrics_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "project_metrics", ROOT / "scripts" / "project_metrics.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_metrics_report_covers_every_area_and_property() -> None:
    metrics = load_metrics_module()

    report = metrics.render(collect=False)

    assert report.startswith(metrics.START_MARKER)
    assert report.endswith(metrics.END_MARKER)
    for area in metrics.GROUPS:
        assert f"| {area} |" in report
    assert "| **Total** |" in report
    assert "| Test functions |" in report
    assert "| Runtime dependencies | 5, all pinned exactly |" in report
    assert "| Quality gates | 12 in `localPipeline.sh` |" in report
    assert "`activity_map/widgets.py`" in report


def test_measured_groups_count_files_and_definitions() -> None:
    metrics = load_metrics_module()

    application = metrics.measure("Application", ("activity_map",))

    assert application.files >= 15
    assert application.code_lines < application.lines
    assert application.functions > application.classes > 0
    assert application.test_functions == 0


def test_tests_group_reports_test_functions() -> None:
    metrics = load_metrics_module()

    tests = metrics.measure("Tests", ("tests",))

    assert tests.test_functions > 100


def test_readme_metrics_section_is_current() -> None:
    metrics = load_metrics_module()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert metrics.START_MARKER in readme
    assert metrics.END_MARKER in readme

    stored = readme.partition(metrics.START_MARKER)[2].partition(metrics.END_MARKER)[0]
    generated = metrics.render(collect=False)
    generated_body = generated.partition(metrics.START_MARKER)[2].partition(
        metrics.END_MARKER
    )[0]
    stored_rows = [line for line in stored.splitlines() if line.startswith("| Area")]
    generated_rows = [
        line for line in generated_body.splitlines() if line.startswith("| Area")
    ]

    assert stored_rows == generated_rows


def test_write_requires_the_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics = load_metrics_module()
    readme = tmp_path / "README.md"
    readme.write_text("no markers here\n", encoding="utf-8")
    monkeypatch.setattr(metrics, "ROOT", tmp_path)

    with pytest.raises(SystemExit):
        metrics.write_readme("section")

    readme.write_text(
        f"head\n{metrics.START_MARKER}old{metrics.END_MARKER}\ntail\n",
        encoding="utf-8",
    )
    section = f"{metrics.START_MARKER}new{metrics.END_MARKER}"

    assert metrics.write_readme(section) is True
    assert metrics.write_readme(section) is False
    assert "new" in readme.read_text(encoding="utf-8")
