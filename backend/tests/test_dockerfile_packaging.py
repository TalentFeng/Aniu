from pathlib import Path
import re


def test_runtime_image_copies_builtin_skills_directory() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(
        r"^COPY\s+backend/skills\s+\./skills\s*$",
        dockerfile,
        re.MULTILINE,
    ), "Docker runtime image must include backend/skills so built-in skills are available after deployment."


def test_runtime_image_copies_alembic_migrations() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(
        r"^COPY\s+backend/alembic\.ini\s+\./alembic\.ini\s*$",
        dockerfile,
        re.MULTILINE,
    ), "Docker runtime image must include alembic.ini so startup migrations can load configuration."
    assert re.search(
        r"^COPY\s+backend/alembic\s+\./alembic\s*$",
        dockerfile,
        re.MULTILINE,
    ), "Docker runtime image must include backend/alembic so startup migrations can find revisions."
