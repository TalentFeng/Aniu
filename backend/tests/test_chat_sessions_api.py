from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core.rate_limit import _limiter
from app.db import database as database_module
from app.db.database import session_scope
from app.db.models import ChatAttachment, ChatMessageRecord
from app.main import create_app
from app.schemas.aniu import ChatStreamRequest
from app.services.aniu_service import aniu_service
from app.services.chat_session_service import chat_session_service
from app.services.llm_service import llm_service
from app.services.scheduler_service import scheduler_service
from app.services.trading_calendar_service import trading_calendar_service


def create_test_client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(trading_calendar_service, "ensure_years", lambda years: None)
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None
    _limiter._buckets.clear()
    aniu_service._account_overview_cache = None
    aniu_service._account_overview_cache_expires_at = None
    app = create_app()
    return TestClient(app)


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/aniu/login", json={"password": "release-pass"})
    payload = response.json()
    return {"Authorization": f"Bearer {payload['token']}"}


def reset_db_state() -> None:
    database_module._engine = None
    database_module._session_local = None
    _limiter._buckets.clear()
    get_settings.cache_clear()


def test_chat_session_stream_builds_attachment_history_without_duplicate_user_message(
    monkeypatch, tmp_path
) -> None:
    captured: dict[str, object] = {}

    def fake_chat(*, messages, emit=None, **kwargs):
        captured["messages"] = messages
        captured["tool_context"] = kwargs.get("tool_context")
        if emit:
            emit("final_started")
            emit("final_delta", delta="Answer")
            emit("completed", message="Answer")
        return "Answer"

    monkeypatch.setattr(llm_service, "chat", fake_chat)

    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            settings = aniu_service.get_or_create_settings(db)
            settings.llm_base_url = "https://example.com/v1"
            settings.llm_api_key = "test-key"
            settings.llm_model = "test-model"
            settings.mx_api_key = "mx-test-key"

            session = chat_session_service.create_session(db, title="Session A")
            image = chat_session_service.save_attachment(
                db,
                filename="chart.png",
                mime_type="image/png",
                data=b"fake-image",
                session_id=session.id,
            )
            doc = chat_session_service.save_attachment(
                db,
                filename="report.pdf",
                mime_type="application/pdf",
                data=b"%PDF-1.7",
                session_id=session.id,
            )

        events = list(
            chat_session_service.stream_chat(
                ChatStreamRequest(
                    session_id=session.id,
                    content="Please analyse this setup",
                    attachment_ids=[image.id, doc.id],
                )
            )
        )

        assert any(event["type"] == "completed" for event in events)

        history = captured["messages"]
        assert isinstance(history, list)
        assert len(history) == 1
        user_message = history[0]
        assert user_message["role"] == "user"
        assert user_message["content"].count("Please analyse this setup") == 1
        assert "![chart.png](" in user_message["content"]
        assert "[用户上传了文件：report.pdf]" in user_message["content"]
        tool_context = captured["tool_context"]
        assert isinstance(tool_context, dict)
        assert tool_context["app_settings"].mx_api_key == "mx-test-key"

        with session_scope() as db:
            records = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session.id)
                .order_by(ChatMessageRecord.id.asc())
                .all()
            )

        assert len(records) == 2
        assert records[0].role == "user"
        assert records[1].role == "assistant"
        assert records[1].content == "Answer"

    reset_db_state()


def test_chat_session_stream_persists_failed_assistant_message(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(*, emit=None, **kwargs):
        del kwargs
        if emit:
            emit("final_started")
            emit("final_delta", delta="Partial answer")
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(llm_service, "chat", fake_chat)

    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            settings = aniu_service.get_or_create_settings(db)
            settings.llm_base_url = "https://example.com/v1"
            settings.llm_api_key = "test-key"
            settings.llm_model = "test-model"
            session = chat_session_service.create_session(db, title="Failed Session")

        events = list(
            chat_session_service.stream_chat(
                ChatStreamRequest(
                    session_id=session.id,
                    content="Please keep my message",
                    attachment_ids=[],
                )
            )
        )

        assert any(event["type"] == "failed" for event in events)

        with session_scope() as db:
            records = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session.id)
                .order_by(ChatMessageRecord.id.asc())
                .all()
            )

        assert len(records) == 2
        assert records[0].role == "user"
        assert records[0].content == "Please keep my message"
        assert records[1].role == "assistant"
        assert records[1].content == "Partial answer\n\n执行失败：model unavailable"

    reset_db_state()


def test_chat_session_stream_persists_partial_message_when_client_disconnects(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(*, emit=None, cancel_event=None, **kwargs):
        del kwargs
        assert cancel_event is not None
        if emit:
            emit("final_started")
            emit("final_delta", delta="Partial answer")
        while not cancel_event.is_set():
            pass
        return "Partial answer"

    monkeypatch.setattr(llm_service, "chat", fake_chat)

    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            settings = aniu_service.get_or_create_settings(db)
            settings.llm_base_url = "https://example.com/v1"
            settings.llm_api_key = "test-key"
            settings.llm_model = "test-model"
            session = chat_session_service.create_session(db, title="Disconnect Session")

        stream = chat_session_service.stream_chat(
            ChatStreamRequest(
                session_id=session.id,
                content="Please keep partial output",
                attachment_ids=[],
            )
        )
        first_event = next(stream)
        second_event = next(stream)
        assert first_event["type"] == "final_started"
        assert second_event["type"] == "final_delta"
        stream.close()

        with session_scope() as db:
            records = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session.id)
                .order_by(ChatMessageRecord.id.asc())
                .all()
            )

        assert len(records) == 2
        assert records[1].role == "assistant"
        assert records[1].content == "Partial answer\n\n执行中断：客户端连接已断开。"

    reset_db_state()


def test_chat_session_stream_matches_tool_calls_by_tool_call_id(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(*, emit=None, **kwargs):
        del kwargs
        if emit:
            emit(
                "tool_call",
                tool_name="mx_query_market",
                tool_call_id="call-a",
                status="running",
                arguments={"query": "A"},
            )
            emit(
                "tool_call",
                tool_name="mx_query_market",
                tool_call_id="call-b",
                status="running",
                arguments={"query": "B"},
            )
            emit(
                "tool_call",
                tool_name="mx_query_market",
                tool_call_id="call-b",
                status="done",
                ok=True,
                summary="B done",
            )
            emit(
                "tool_call",
                tool_name="mx_query_market",
                tool_call_id="call-a",
                status="done",
                ok=True,
                summary="A done",
            )
            emit("completed", message="Done")
        return "Done"

    monkeypatch.setattr(llm_service, "chat", fake_chat)

    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            settings = aniu_service.get_or_create_settings(db)
            settings.llm_base_url = "https://example.com/v1"
            settings.llm_api_key = "test-key"
            settings.llm_model = "test-model"
            session = chat_session_service.create_session(db, title="Tool Call Session")

        list(
            chat_session_service.stream_chat(
                ChatStreamRequest(
                    session_id=session.id,
                    content="Track duplicate tool names",
                    attachment_ids=[],
                )
            )
        )

        with session_scope() as db:
            records = (
                db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.session_id == session.id)
                .order_by(ChatMessageRecord.id.asc())
                .all()
            )

        assistant_tool_calls = records[1].tool_calls
        assert isinstance(assistant_tool_calls, list)
        assert [item["tool_call_id"] for item in assistant_tool_calls] == ["call-a", "call-b"]
        assert [item["summary"] for item in assistant_tool_calls] == ["A done", "B done"]

    reset_db_state()


def test_chat_session_messages_endpoint_supports_pagination(
    monkeypatch, tmp_path
) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        headers = auth_headers(client)
        with session_scope() as db:
            session = chat_session_service.create_session(db, title="Paged Session")
            db.add_all(
                [
                    ChatMessageRecord(
                        session_id=session.id,
                        role="user" if index % 2 else "assistant",
                        content=f"message-{index}",
                    )
                    for index in range(1, 6)
                ]
            )

        response = client.get(
            f"/api/aniu/chat/sessions/{session.id}/messages?limit=2",
            headers=headers,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["session"]["message_count"] == 5
        assert [item["content"] for item in payload["messages"]] == [
            "message-4",
            "message-5",
        ]
        assert payload["has_more"] is True
        assert payload["next_before_id"] is not None

        older_response = client.get(
            (
                f"/api/aniu/chat/sessions/{session.id}/messages"
                f"?limit=2&before_id={payload['next_before_id']}"
            ),
            headers=headers,
        )

        assert older_response.status_code == 200
        older_payload = older_response.json()
        assert [item["content"] for item in older_payload["messages"]] == [
            "message-2",
            "message-3",
        ]
        assert older_payload["has_more"] is True
        assert older_payload["next_before_id"] is not None

    reset_db_state()


def test_upload_chat_attachment_stores_file_under_session_directory(
    monkeypatch, tmp_path
) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        headers = auth_headers(client)
        create_response = client.post(
            "/api/aniu/chat/sessions",
            headers=headers,
            json={"title": "Files"},
        )
        session_id = create_response.json()["id"]

        response = client.post(
            "/api/aniu/chat/uploads",
            headers=headers,
            files={"file": ("notes.md", b"# hello", "text/markdown")},
            data={"session_id": str(session_id)},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["filename"] == "notes.md"

        with session_scope() as db:
            attachment = db.get(ChatAttachment, payload["id"])
            assert attachment is not None
            assert Path(attachment.storage_path).is_file()
            assert Path(attachment.storage_path).parent.name == str(session_id)

    reset_db_state()


def test_upload_chat_attachment_rejects_unsupported_binary_file(
    monkeypatch, tmp_path
) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        headers = auth_headers(client)
        response = client.post(
            "/api/aniu/chat/uploads",
            headers=headers,
            files={"file": ("archive.bin", b"\x00\x01\x02", "application/octet-stream")},
        )

        assert response.status_code == 400
        assert "仅支持图片、PDF、文本和常见办公文档附件。" in response.json()["detail"]

    reset_db_state()
