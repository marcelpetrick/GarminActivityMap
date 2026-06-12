import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_DIR = ROOT / "documents"
OUTPUT_DIR = ROOT / "build" / "docs"
ARCHITECTURE_DOC = DOCUMENTS_DIR / "architecture.md"
README = ROOT / "README.md"

REQUIRED_ARCHITECTURE_SECTIONS = (
    "## Level 1: System Context",
    "## Level 2: Container View",
    "## Level 3: Component View",
    "## Level 4: Code View",
    "## Runtime Data Flow",
    "## Operational Constraints",
)


def _read(path: Path) -> str:
    if not path.exists():
        msg = f"Required documentation file is missing: {path.relative_to(ROOT)}"
        raise SystemExit(msg)
    return path.read_text(encoding="utf-8")


def _validate_architecture() -> None:
    content = _read(ARCHITECTURE_DOC)
    missing_sections = [
        section for section in REQUIRED_ARCHITECTURE_SECTIONS if section not in content
    ]
    if missing_sections:
        formatted = ", ".join(missing_sections)
        raise SystemExit(f"Architecture documentation misses sections: {formatted}")
    if content.count("```mermaid") < 3:
        raise SystemExit("Architecture documentation must include C4-style diagrams")


def _copy_markdown_documents() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in sorted([README, *DOCUMENTS_DIR.glob("*.md")]):
        target = OUTPUT_DIR / source.name
        shutil.copyfile(source, target)
        copied.append(target)
    return copied


def _write_index(copied: list[Path]) -> None:
    links = "\n".join(f"- [{path.stem}]({path.name})" for path in copied)
    index = f"# Documentation Bundle\n\n{links}\n"
    (OUTPUT_DIR / "index.md").write_text(index, encoding="utf-8")


def main() -> int:
    _validate_architecture()
    copied = _copy_markdown_documents()
    _write_index(copied)
    print(f"Built documentation in {OUTPUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
