from __future__ import annotations

import json
import secrets
import shutil
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SKILL_WORKSPACE_DIRNAME = "skill_workspace"
_JWT_SECRET_FILENAME = "jwt_secret.txt"
_DEFAULT_DATABASE_URL = "postgresql+psycopg://aniu:aniu@localhost:5432/aniu"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        enable_decoding=False,
        extra="ignore",
    )

    app_name: str = "Aniu"
    api_prefix: str = "/api/aniu"
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    sqlite_db_path: Path | None = Field(default=None, alias="SQLITE_DB_PATH")
    runtime_data_dir: Path = Field(default=Path("./data"), alias="RUNTIME_DATA_DIR")

    mx_apikey: str | None = Field(default=None, alias="MX_APIKEY")
    mx_api_url: str = Field(
        default="https://mkapi2.dfcfs.com/finskillshub", alias="MX_API_URL"
    )

    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    account_overview_cache_ttl_seconds: int = Field(
        default=30, alias="ACCOUNT_OVERVIEW_CACHE_TTL_SECONDS"
    )

    scheduler_poll_seconds: int = Field(default=15, alias="SCHEDULER_POLL_SECONDS")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str | None = Field(default=None, alias="ADMIN_PASSWORD")
    app_login_password: str | None = Field(default=None, alias="APP_LOGIN_PASSWORD")
    model_pricing: dict[str, int] = Field(
        default_factory=lambda: {"gpt-4o-mini": 1, "gpt-4o": 5},
        alias="MODEL_PRICING",
    )
    jwt_secret: str | None = Field(default=None, alias="JWT_SECRET")
    jwt_expire_hours: int = Field(default=24, alias="JWT_EXPIRE_HOURS")
    trust_x_forwarded_for: bool = Field(
        default=False,
        alias="TRUST_X_FORWARDED_FOR",
    )
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: ["*"], alias="CORS_ALLOW_ORIGINS"
    )

    @field_validator(
        "database_url",
        "mx_apikey",
        "openai_base_url",
        "openai_api_key",
        "admin_password",
        "app_login_password",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> str | None:
        """Normalize empty / whitespace-only env vars to None."""
        if isinstance(value, str) and not value.strip():
            return None
        return value  # type: ignore[return-value]

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def normalize_jwt_secret(cls, value: object) -> str | None:
        if not value or (isinstance(value, str) and not value.strip()):
            return None
        return str(value).strip()

    @field_validator("model_pricing", mode="before")
    @classmethod
    def parse_model_pricing(cls, value: object) -> dict[str, int]:
        if isinstance(value, dict):
            return {
                str(key).strip(): int(amount)
                for key, amount in value.items()
                if str(key).strip()
            }
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {"gpt-4o-mini": 1, "gpt-4o": 5}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                items: dict[str, int] = {}
                for chunk in raw.split(","):
                    if "=" not in chunk:
                        continue
                    name, amount = chunk.split("=", 1)
                    model_name = name.strip()
                    if not model_name:
                        continue
                    items[model_name] = int(amount.strip())
                return items or {"gpt-4o-mini": 1, "gpt-4o": 5}
            if isinstance(parsed, dict):
                return {
                    str(key).strip(): int(amount)
                    for key, amount in parsed.items()
                    if str(key).strip()
                }
        return {"gpt-4o-mini": 1, "gpt-4o": 5}

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item) for item in value]
        return ["*"]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    cwd = Path.cwd().resolve()
    if not settings.runtime_data_dir.is_absolute():
        if cwd.name == "backend" and settings.runtime_data_dir == Path("./data"):
            settings.runtime_data_dir = (cwd.parent / "data").resolve()
        else:
            settings.runtime_data_dir = (cwd / settings.runtime_data_dir).resolve()
    else:
        settings.runtime_data_dir = settings.runtime_data_dir.resolve()
    settings.runtime_data_dir.mkdir(parents=True, exist_ok=True)

    if settings.sqlite_db_path is not None and not settings.sqlite_db_path.is_absolute():
        settings.sqlite_db_path = (Path.cwd() / settings.sqlite_db_path).resolve()
    elif settings.sqlite_db_path is not None:
        settings.sqlite_db_path = settings.sqlite_db_path.resolve()

    if not settings.database_url:
        if settings.sqlite_db_path is not None:
            settings.database_url = f"sqlite+pysqlite:///{settings.sqlite_db_path.as_posix()}"
        else:
            settings.database_url = _DEFAULT_DATABASE_URL

    _merge_legacy_skill_workspace(settings)
    if not settings.jwt_secret:
        settings.jwt_secret = _load_or_create_jwt_secret(
            get_persistent_jwt_secret_file(settings)
        )
    return settings


def get_runtime_data_dir(settings: Settings | None = None) -> Path:
    return (settings or get_settings()).runtime_data_dir.resolve()


def get_skill_workspace_root(
    settings: Settings | None = None,
    user_id: int | None = None,
) -> Path:
    current = settings or get_settings()
    if user_id is None and current.sqlite_db_path is not None:
        root = current.sqlite_db_path.parent / _SKILL_WORKSPACE_DIRNAME
    else:
        root = get_runtime_data_dir(current) / _SKILL_WORKSPACE_DIRNAME
    if user_id is not None:
        root = root / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def get_skill_workspace_skills_dir(
    settings: Settings | None = None,
    user_id: int | None = None,
) -> Path:
    path = get_skill_workspace_root(settings, user_id=user_id) / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def get_uploads_root(
    settings: Settings | None = None,
    user_id: int | None = None,
) -> Path:
    path = get_runtime_data_dir(settings) / "uploads"
    if user_id is not None:
        path = path / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def get_persistent_jwt_secret_file(settings: Settings | None = None) -> Path:
    return get_runtime_data_dir(settings) / _JWT_SECRET_FILENAME


def _legacy_skill_workspace_root(settings: Settings) -> Path | None:
    if settings.sqlite_db_path is not None:
        return settings.sqlite_db_path.parent / _SKILL_WORKSPACE_DIRNAME

    cwd = Path.cwd().resolve()
    if cwd.name == "backend":
        return cwd / "data" / _SKILL_WORKSPACE_DIRNAME
    return None


def _merge_legacy_skill_workspace(settings: Settings) -> None:
    legacy_root = _legacy_skill_workspace_root(settings)
    if legacy_root is None or not legacy_root.exists():
        return
    target_root = get_skill_workspace_root(settings)
    if legacy_root.resolve() == target_root.resolve():
        return

    target_root.mkdir(parents=True, exist_ok=True)
    for child in legacy_root.iterdir():
        destination = target_root / child.name
        if destination.exists():
            continue
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def is_sqlite_database(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    parsed = urlparse(str(current.database_url or ""))
    return parsed.scheme.startswith("sqlite")


def _load_or_create_jwt_secret(secret_file: Path) -> str:
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    if secret_file.is_file():
        existing = secret_file.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    secret = secrets.token_urlsafe(32)
    secret_file.write_text(secret, encoding="utf-8")
    return secret
