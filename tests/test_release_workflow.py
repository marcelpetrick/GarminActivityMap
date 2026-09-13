from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_completion_is_detected_by_release_not_tag() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    detection = workflow.index("gh release view")
    tag_step = workflow.index("Create or verify the annotated tag")
    publication = workflow.index("gh release create")

    assert detection < tag_step < publication
    assert "Tag %s already exists; bump VERSION" not in workflow


def test_existing_tag_is_verified_and_reused_for_recovery() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "refs/tags/${TAG}^{}" in workflow
    assert '"${REMOTE_TAG_COMMIT}" != "${GITHUB_SHA}"' in workflow
    assert "Reusing existing tag" in workflow
