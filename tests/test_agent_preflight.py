import shutil
import subprocess
from pathlib import Path


def initialize_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    script_dir = repository / "scripts"
    script_dir.mkdir()
    source = Path(__file__).parents[1] / "scripts" / "agentPreflight.sh"
    script = script_dir / "agentPreflight.sh"
    shutil.copyfile(source, script)
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test: checkpoint"],
        cwd=repository,
        check=True,
    )
    return repository


def test_agent_preflight_accepts_clean_checkpoint(tmp_path: Path) -> None:
    repository = initialize_repository(tmp_path)

    result = subprocess.run(
        ["bash", "scripts/agentPreflight.sh"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Repository checkpoint ready" in result.stdout


def test_agent_preflight_rejects_uncommitted_changes(tmp_path: Path) -> None:
    repository = initialize_repository(tmp_path)
    (repository / "change.txt").write_text("uncommitted\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/agentPreflight.sh"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "commit or intentionally remove current changes" in result.stderr
