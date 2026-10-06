from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def load_build_docs_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_docs", ROOT / "scripts" / "build_docs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rewrite_links_flattens_links_to_bundled_documents(tmp_path: Path) -> None:
    build_docs = load_build_docs_module()
    readme = tmp_path / "README.md"
    guide = tmp_path / "documents" / "guide.md"
    bundled = {readme.resolve(), guide.resolve()}

    readme_text = build_docs.rewrite_links(
        "See [guide](documents/guide.md#setup) and [plan](plan.md).",
        readme,
        bundled,
    )
    guide_text = build_docs.rewrite_links(
        "Back to [README](../README.md), or [site](https://example.invalid/a.md).",
        guide,
        bundled,
    )

    assert readme_text == "See [guide](guide.md#setup) and [plan](plan.md)."
    assert guide_text == (
        "Back to [README](README.md), or [site](https://example.invalid/a.md)."
    )
