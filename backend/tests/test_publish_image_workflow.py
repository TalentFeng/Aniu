from pathlib import Path


def test_publish_workflow_builds_multi_arch_images() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow = (
        repo_root / ".github" / "workflows" / "publish-image.yml"
    ).read_text(encoding="utf-8")

    assert "docker/setup-qemu-action@v3" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
