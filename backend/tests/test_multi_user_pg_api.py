from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core import rate_limit as rate_limit_module
from app.db import database as database_module
from app.db.database import session_scope
from app.db.models import AppSettings, ChatAttachment, ChatSession, CreditTransaction
from app.main import create_app
from app.services.aniu_service import aniu_service
from app.services.chat_session_service import chat_session_service
from app.services.scheduler_service import scheduler_service
from app.services.trading_calendar_service import trading_calendar_service


def create_test_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "multi-user.db"))
    monkeypatch.setenv("RUNTIME_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(trading_calendar_service, "ensure_years", lambda years: None)
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None
    rate_limit_module._limiter.reset()
    aniu_service._account_overview_cache = None
    aniu_service._account_overview_cache_expires_at = None
    return TestClient(create_app())


def auth_headers(
    client: TestClient,
    *,
    username: str = "admin",
    password: str = "release-pass",
) -> dict[str, str]:
    response = client.post(
        "/api/aniu/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    payload = response.json()
    return {"Authorization": f"Bearer {payload['token']}"}


def reset_state() -> None:
    database_module._engine = None
    database_module._session_local = None
    rate_limit_module._limiter.reset()
    get_settings.cache_clear()


def test_admin_can_create_user_and_user_data_is_isolated(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        admin_headers = auth_headers(client)
        create_response = client.post(
            "/api/aniu/admin/users",
            headers=admin_headers,
            json={
                "username": "alice",
                "password": "secret-pass",
                "role": "user",
                "credit_balance": 3,
            },
        )
        assert create_response.status_code == 200
        alice_id = create_response.json()["id"]

        alice_headers = auth_headers(
            client,
            username="alice",
            password="secret-pass",
        )
        settings_response = client.get("/api/aniu/settings", headers=alice_headers)
        assert settings_response.status_code == 200
        assert settings_response.json()["user_id"] == alice_id

        with session_scope() as db:
            admin_settings = aniu_service.get_or_create_settings(db, 1)
            alice_settings = aniu_service.get_or_create_settings(db, alice_id)
            admin_session = chat_session_service.create_session(
                db,
                user=1,
                title="admin session",
            )
            alice_session = chat_session_service.create_session(
                db,
                user=alice_id,
                title="alice session",
            )

        assert admin_settings.id != alice_settings.id

        admin_sessions = client.get("/api/aniu/chat/sessions", headers=admin_headers)
        alice_sessions = client.get("/api/aniu/chat/sessions", headers=alice_headers)
        assert admin_sessions.status_code == 200
        assert alice_sessions.status_code == 200
        assert [item["id"] for item in admin_sessions.json()] == [admin_session.id]
        assert [item["id"] for item in alice_sessions.json()] == [alice_session.id]

    reset_state()


def test_credit_shortage_rejects_chat_without_writing_transaction(
    monkeypatch,
    tmp_path,
) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        admin_headers = auth_headers(client)
        client.post(
            "/api/aniu/admin/users",
            headers=admin_headers,
            json={
                "username": "bob",
                "password": "secret-pass",
                "role": "user",
                "credit_balance": 0,
            },
        )
        bob_headers = auth_headers(client, username="bob", password="secret-pass")

        with session_scope() as db:
            bob_settings = db.query(AppSettings).filter_by(user_id=2).one_or_none()
            if bob_settings is None:
                bob_settings = aniu_service.get_or_create_settings(db, 2)
            bob_settings.llm_base_url = "https://example.com/v1"
            bob_settings.llm_api_key = "test-key"
            bob_settings.llm_model = "gpt-4o-mini"

        response = client.post(
            "/api/aniu/chat",
            headers=bob_headers,
            json={"content": "hello"},
        )
        assert response.status_code == 402
        assert response.json()["detail"] == "credit 余额不足。"

        with session_scope() as db:
            count = db.query(CreditTransaction).filter_by(user_id=2).count()
            assert count == 0

    reset_state()


def test_chat_uploads_are_stored_under_user_directory(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            session = ChatSession(user_id=1, title="uploads", kind="user")
            db.add(session)
            db.flush()
            attachment = chat_session_service.save_attachment(
                db,
                user=1,
                filename="notes.md",
                mime_type="text/markdown",
                data=b"hello",
                session_id=session.id,
            )
            db.flush()
            attachment_id = attachment.id

        with session_scope() as db:
            stored = db.get(ChatAttachment, attachment_id)
            assert stored is not None
            assert f"/uploads/1/{session.id}/" in stored.storage_path
            assert Path(stored.storage_path).is_file()

    reset_state()
