from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import bcrypt
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings, is_sqlite_database
from app.db.models import ModelPricing, User

_engine: Engine | None = None
_session_local: sessionmaker[Session] | None = None


def _build_engine() -> Engine:
    settings = get_settings()
    database_url = str(settings.database_url or "").strip()
    kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if is_sqlite_database(settings):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url in {
            "sqlite://",
            "sqlite+pysqlite://",
            "sqlite:///:memory:",
            "sqlite+pysqlite:///:memory:",
        }:
            kwargs["poolclass"] = StaticPool
    return create_engine(database_url, **kwargs)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_local() -> sessionmaker[Session]:
    global _session_local
    if _session_local is None:
        _session_local = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_local


def _alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", str(get_settings().database_url or ""))
    config.attributes["connection"] = get_engine().connect()
    return config


def init_db() -> None:
    config = _alembic_config()
    connection = config.attributes["connection"]
    try:
        command.upgrade(config, "head")
    finally:
        connection.close()
    with session_scope() as db:
        _seed_admin_user(db)
        _seed_model_pricing(db)


def _seed_admin_user(db: Session) -> None:
    settings = get_settings()
    raw_password = settings.admin_password or settings.app_login_password
    if not raw_password:
        return

    existing = db.scalar(
        select(User).where(User.username == settings.admin_username).limit(1)
    )
    if existing is None:
        existing = User(
            username=settings.admin_username,
            password_hash=_hash_password(raw_password),
            role="admin",
            credit_balance=0,
            is_active=True,
        )
        db.add(existing)
        db.flush()
        return

    if existing.role != "admin":
        existing.role = "admin"
    if not existing.is_active:
        existing.is_active = True
    if not _verify_password(raw_password, existing.password_hash):
        existing.password_hash = _hash_password(raw_password)
    db.add(existing)


def _seed_model_pricing(db: Session) -> None:
    settings = get_settings()
    existing = {
        item.model_name: item
        for item in db.scalars(select(ModelPricing)).all()
    }
    for model_name, credit_cost in settings.model_pricing.items():
        normalized_name = str(model_name).strip()
        if not normalized_name:
            continue
        item = existing.get(normalized_name)
        if item is None:
            db.add(
                ModelPricing(
                    model_name=normalized_name,
                    credit_cost=max(int(credit_cost), 0),
                    is_active=True,
                )
            )
            continue
        item.credit_cost = max(int(credit_cost), 0)
        item.is_active = True
        db.add(item)


def hash_password(password: str) -> str:
    return _hash_password(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _verify_password(password, password_hash)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def get_db() -> Generator[Session, None, None]:
    db = get_session_local()()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = get_session_local()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
