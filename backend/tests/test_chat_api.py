from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.core import rate_limit as rate_limit_module
from app.db import database as database_module
from app.db.database import session_scope
from app.db.models import StrategyRun
from app.main import create_app
from app.skills import skill_registry
from app.services.event_bus import event_bus
from app.services.llm_service import llm_service
from app.services.scheduler_service import scheduler_service
from app.services.trading_calendar_service import trading_calendar_service


def create_test_client(monkeypatch, tmp_path) -> TestClient:
    from app.services.aniu_service import aniu_service

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(trading_calendar_service, "ensure_years", lambda years: None)
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None
    rate_limit_module._limiter.reset()
    aniu_service._account_overview_cache = None
    aniu_service._account_overview_cache_expires_at = None
    app = create_app()
    return TestClient(app)


def _auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/aniu/login",
        json={"password": "release-pass"},
    )
    payload = response.json()
    return {"Authorization": f"Bearer {payload['token']}"}


def test_login_endpoint_accepts_configured_credentials(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/aniu/login",
            json={"password": "release-pass"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["token"]
    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_login_endpoint_rejects_invalid_credentials(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        response = client.post(
            "/api/aniu/login",
            json={"password": "wrong-password"},
        )

    assert response.status_code == 401
    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_authenticate_login_uses_compare_digest(monkeypatch, tmp_path) -> None:
    from app.services import aniu_service as aniu_service_module

    captured: dict[str, str] = {}

    def fake_compare_digest(left: str, right: str) -> bool:
        captured["left"] = left
        captured["right"] = right
        return True

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(aniu_service_module.secrets, "compare_digest", fake_compare_digest)
    get_settings.cache_clear()

    payload = aniu_service_module.aniu_service.authenticate_login("release-pass")

    assert payload["authenticated"] is True
    assert captured == {
        "left": "release-pass",
        "right": "release-pass",
    }

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_login_rate_limit_ignores_spoofed_forwarded_for_by_default(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(trading_calendar_service, "ensure_years", lambda years: None)
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None
    rate_limit_module._limiter.reset()
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        for index in range(10):
            response = client.post(
                "/api/aniu/login",
                json={"password": "wrong-password"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
            assert response.status_code == 401

        blocked = client.post(
            "/api/aniu/login",
            json={"password": "wrong-password"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )

    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "请求过于频繁，请稍后再试。"

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_login_rate_limit_can_trust_forwarded_for_when_enabled(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "true")

    with create_test_client(monkeypatch, tmp_path) as client:
        responses = [
            client.post(
                "/api/aniu/login",
                json={"password": "wrong-password"},
                headers={"X-Forwarded-For": f"198.51.100.{index}"},
            )
            for index in range(11)
        ]

    assert all(response.status_code == 401 for response in responses)

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_run_stream_endpoint_is_rate_limited(monkeypatch, tmp_path) -> None:
    from app.services.aniu_service import aniu_service

    monkeypatch.setattr(aniu_service, "start_run_async", lambda **kwargs: 42)

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(trading_calendar_service, "ensure_years", lambda years: None)
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None
    rate_limit_module._limiter.reset()
    app = create_app()

    with TestClient(app, raise_server_exceptions=False) as client:
        headers = _auth_headers(client)

        for _ in range(5):
            response = client.post("/api/aniu/run-stream", headers=headers)
            assert response.status_code == 200
            assert response.json()["run_id"] == 42

        blocked = client.post("/api/aniu/run-stream", headers=headers)

    assert blocked.status_code == 429

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_app_startup_requires_current_year_trading_calendar(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_LOGIN_PASSWORD", "release-pass")
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(
        trading_calendar_service,
        "ensure_years",
        lambda years: (_ for _ in ()).throw(RuntimeError("calendar unavailable"))
        if years == [2026]
        else None,
    )
    monkeypatch.setattr(scheduler_service, "start", lambda: None)
    monkeypatch.setattr(scheduler_service, "stop", lambda: None)
    monkeypatch.setattr("app.main.date", type("FakeDate", (), {"today": staticmethod(lambda: type("Today", (), {"year": 2026})())}))
    get_settings.cache_clear()
    database_module._engine = None
    database_module._session_local = None

    app = create_app()

    with pytest.raises(RuntimeError, match="calendar unavailable"):
        with TestClient(app):
            pass

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_endpoint_returns_assistant_message(monkeypatch, tmp_path) -> None:
    from app.services.aniu_service import aniu_service

    monkeypatch.setattr(
        aniu_service,
        "chat",
        lambda payload: {
            "message": {
                "role": "assistant",
                "content": "测试回复",
            },
            "context": {
                "system_prompt_included": True,
                "tool_access_account_summary": True,
                "tool_access_positions": True,
                "tool_access_orders": True,
                "tool_access_runs": True,
            },
        },
    )

    with create_test_client(monkeypatch, tmp_path) as client:
        headers = _auth_headers(client)
        response = client.post(
            "/api/aniu/chat",
            json={
                "messages": [
                    {"role": "user", "content": "你好"},
                ],
            },
            headers=headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["role"] == "assistant"
    assert payload["message"]["content"] == "测试回复"

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_endpoint_rejects_empty_messages(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        headers = _auth_headers(client)
        response = client.post(
            "/api/aniu/chat",
            json={
                "messages": [],
            },
            headers=headers,
        )

    assert response.status_code == 422
    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_tools_available_for_chat_run_type(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path):
        tool_names = {
            spec["function"]["name"] for spec in skill_registry.build_tools(run_type="chat")
        }

    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "edit_file" in tool_names
    assert "list_dir" in tool_names
    assert "glob" in tool_names
    assert "grep" in tool_names
    assert "exec" in tool_names
    assert "web_search" in tool_names
    assert "web_fetch" in tool_names
    assert "http_get" in tool_names
    assert "http_post" in tool_names
    assert "file_read" not in tool_names
    assert "file_write" not in tool_names
    assert "file_list" not in tool_names
    assert "bash_exec" not in tool_names
    assert "chat_get_account_summary" in tool_names
    assert "chat_get_positions" in tool_names
    assert "chat_get_orders" in tool_names
    assert "chat_list_runs" in tool_names
    assert "chat_get_run_detail" in tool_names
    assert "mx_query_market" in tool_names
    assert "mx_search_news" in tool_names
    assert "mx_screen_stocks" in tool_names
    assert "mx_get_positions" in tool_names
    assert "mx_get_balance" in tool_names
    assert "mx_get_orders" in tool_names
    assert "mx_get_self_selects" in tool_names
    assert "mx_manage_self_select" in tool_names
    assert "mx_moni_trade" in tool_names
    assert "mx_moni_cancel" in tool_names

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_runtime_read_file_can_access_builtin_skill_docs(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path):
        target = Path(__file__).resolve().parents[1] / "skills" / "builtin_utils" / "SKILL.md"
        result = skill_registry.execute_tool(
            tool_name="read_file",
            arguments={"path": str(target), "offset": 1, "limit": 20},
            context={"run_type": "chat"},
        )

    assert result["ok"] is True
    assert "通用技能运行时" in result["result"]["content"]

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_removed_runtime_aliases_are_no_longer_available(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path):
        result = skill_registry.execute_tool(
            tool_name="file_read",
            arguments={"path": "skills/builtin_utils/SKILL.md"},
            context={"run_type": "chat"},
        )

    assert result["ok"] is False
    assert "未知工具调用" in result["error"]

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_system_prompt_always_appends_confirmation_rule(monkeypatch) -> None:
    monkeypatch.setattr(
        skill_registry,
        "build_prompt_supplement",
        lambda *, run_type=None: "技能补充提示" if run_type == "chat" else "",
    )

    chat_prompt = llm_service._augment_system_prompt(
        "用户自定义系统提示词",
        run_type="chat",
    )
    analysis_prompt = llm_service._augment_system_prompt(
        "用户自定义系统提示词",
        run_type="analysis",
    )

    assert "用户自定义系统提示词" in chat_prompt
    assert "技能补充提示" in chat_prompt
    assert "必须先明确说明拟执行操作、影响范围和潜在风险" in chat_prompt
    assert "得到用户明确确认后才能调用工具或执行操作" in chat_prompt
    assert "必须先明确说明拟执行操作、影响范围和潜在风险" not in analysis_prompt


def test_mx_core_tools_can_execute_in_chat_without_prebuilt_client(
    monkeypatch, tmp_path
) -> None:
    from skills.mx_core import handler as mx_core_handler

    captured: dict[str, object] = {}

    class DummyMXClient:
        def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

        def __enter__(self):
            captured["entered"] = True
            return self

        def __exit__(self, *args: object) -> None:
            captured["exited"] = True

    def fake_execute_tool(*, client, app_settings, tool_name, arguments):
        captured["client"] = client
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        captured["task_prompt"] = getattr(app_settings, "task_prompt", None)
        return {
            "ok": True,
            "tool_name": tool_name,
            "summary": "ok",
            "result": {"connected": True},
        }

    monkeypatch.setattr(mx_core_handler, "MXClient", DummyMXClient)
    monkeypatch.setattr(mx_core_handler.mx_skill_service, "execute_tool", fake_execute_tool)

    with create_test_client(monkeypatch, tmp_path):
        result = skill_registry.execute_tool(
            tool_name="mx_get_balance",
            arguments={},
            context={
                "run_type": "chat",
                "app_settings": SimpleNamespace(mx_api_key="mx-chat-key", task_prompt=""),
            },
        )

    assert result["ok"] is True
    assert captured["api_key"] == "mx-chat-key"
    assert captured["tool_name"] == "mx_get_balance"
    assert captured["entered"] is True
    assert captured["exited"] is True

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_context_tools_read_account_and_runs(monkeypatch, tmp_path) -> None:
    from app.services.aniu_service import aniu_service

    monkeypatch.setattr(
        aniu_service,
        "get_account_overview",
        lambda **kwargs: {
            "open_date": "2026-01-01",
            "daily_profit_trade_date": "2026-04-18",
            "operating_days": 30,
            "initial_capital": 200000.0,
            "total_assets": 212345.67,
            "total_market_value": 156789.0,
            "cash_balance": 55556.67,
            "total_position_ratio": 73.8,
            "holding_profit": 12345.67,
            "total_return_ratio": 6.17,
            "nav": 1.0617,
            "daily_profit": 1234.5,
            "daily_return_ratio": 0.58,
            "positions": [
                {
                    "name": "东方财富",
                    "symbol": "300059.SZ",
                    "volume": 1000,
                    "available_volume": 800,
                    "profit_text": "+1234.00",
                },
                {
                    "name": "贵州茅台",
                    "symbol": "600519.SH",
                    "volume": 100,
                    "available_volume": 100,
                    "profit_text": "+5678.00",
                },
            ],
            "orders": [
                {
                    "order_id": "A001",
                    "name": "东方财富",
                    "symbol": "300059.SZ",
                    "side_text": "买入",
                    "status_text": "已报",
                }
            ],
            "trade_summaries": [],
            "errors": [],
        },
    )

    with create_test_client(monkeypatch, tmp_path):
        account_result = skill_registry.execute_tool(
            tool_name="chat_get_account_summary",
            arguments={},
            context={"run_type": "chat"},
        )
        positions_result = skill_registry.execute_tool(
            tool_name="chat_get_positions",
            arguments={"limit": 1},
            context={"run_type": "chat"},
        )
        orders_result = skill_registry.execute_tool(
            tool_name="chat_get_orders",
            arguments={"limit": 1},
            context={"run_type": "chat"},
        )

    assert account_result["ok"] is True
    assert account_result["result"]["account"]["total_assets"] == 212345.67
    assert positions_result["ok"] is True
    assert positions_result["result"]["total"] == 2
    assert len(positions_result["result"]["items"]) == 1
    assert orders_result["ok"] is True
    assert orders_result["result"]["items"][0]["order_id"] == "A001"

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_chat_context_tools_list_and_read_run_detail(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path):
        with session_scope() as db:
            db.add(
                StrategyRun(
                    trigger_source="manual",
                    run_type="analysis",
                    schedule_name="盘前分析",
                    status="completed",
                    analysis_summary="早盘看多，建议关注券商。",
                    final_answer="最终结论：维持偏多判断，优先观察券商与AI方向。",
                    decision_payload={
                        "tool_calls": [
                            {"name": "mx_query_market"},
                        ]
                    },
                    llm_response_payload={
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 34,
                            "total_tokens": 46,
                        }
                    },
                )
            )
            db.flush()
            run_id = db.query(StrategyRun.id).order_by(StrategyRun.id.desc()).first()[0]

        list_result = skill_registry.execute_tool(
            tool_name="chat_list_runs",
            arguments={"limit": 5},
            context={"run_type": "chat"},
        )
        detail_result = skill_registry.execute_tool(
            tool_name="chat_get_run_detail",
            arguments={"run_id": run_id},
            context={"run_type": "chat"},
        )

    assert list_result["ok"] is True
    assert list_result["result"]["items"][0]["id"] == run_id
    assert list_result["result"]["items"][0]["content_preview"] == "早盘看多，建议关注券商。"
    assert detail_result["ok"] is True
    assert detail_result["result"]["id"] == run_id
    assert detail_result["result"]["final_answer"] == "最终结论：维持偏多判断，优先观察券商与AI方向。"
    assert detail_result["result"]["api_call_count"] == 1

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_runs_endpoint_returns_lightweight_summary(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        with session_scope() as db:
            db.add(
                StrategyRun(
                    trigger_source="manual",
                    run_type="analysis",
                    schedule_name="盘前分析",
                    status="completed",
                    analysis_summary="摘要",
                    final_answer="详细输出",
                    decision_payload={
                        "tool_calls": [
                            {"name": "mx_query_market"},
                            {"name": "mx_moni_trade"},
                        ]
                    },
                    executed_actions=[{"action": "BUY", "symbol": "300059"}],
                    llm_response_payload={
                        "usage": {
                            "prompt_tokens": 11,
                            "completion_tokens": 22,
                            "total_tokens": 33,
                        }
                    },
                )
            )

        headers = _auth_headers(client)
        response = client.get("/api/aniu/runs?limit=20", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    run = payload[0]
    assert run["analysis_summary"] == "摘要"
    assert run["api_call_count"] == 1
    assert run["executed_trade_count"] == 1
    assert run["input_tokens"] == 11
    assert run["output_tokens"] == 22
    assert run["total_tokens"] == 33
    assert "final_answer" not in run
    assert "decision_payload" not in run
    assert "executed_actions" not in run

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_runs_endpoint_filters_by_date(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        with session_scope() as db:
            db.add_all(
                [
                    StrategyRun(
                        trigger_source="manual",
                        run_type="analysis",
                        status="completed",
                        analysis_summary="today",
                        started_at=datetime(2026, 4, 14, 8, 30, 0),
                    ),
                    StrategyRun(
                        trigger_source="manual",
                        run_type="analysis",
                        status="completed",
                        analysis_summary="yesterday",
                        started_at=datetime(2026, 4, 13, 8, 30, 0),
                    ),
                ]
            )

        headers = _auth_headers(client)
        response = client.get("/api/aniu/runs?date=2026-04-14&limit=20", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["analysis_summary"] == "today"

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_runs_feed_returns_pagination_metadata(monkeypatch, tmp_path) -> None:
    with create_test_client(monkeypatch, tmp_path) as client:
        with session_scope() as db:
            db.add_all(
                [
                    StrategyRun(
                        trigger_source="manual",
                        run_type="analysis",
                        status="completed",
                        analysis_summary=f"run-{index}",
                        started_at=datetime(2026, 4, 14, 8, index, 0),
                    )
                    for index in range(3)
                ]
            )

        headers = _auth_headers(client)
        response = client.get("/api/aniu/runs-feed?limit=2", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["has_more"] is True
    assert payload["next_before_id"] is not None

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_run_events_endpoint_emits_failed_event_when_event_bus_stream_errors(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        event_bus,
        "stream",
        lambda run_id: (_ for _ in ()).throw(RuntimeError(f"stream boom: {run_id}")),
    )

    with create_test_client(monkeypatch, tmp_path) as client:
        headers = _auth_headers(client)
        response = client.get("/api/aniu/runs/123/events", headers=headers)

    assert response.status_code == 200
    assert "event: failed" in response.text
    assert "stream boom: 123" in response.text

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_runtime_overview_endpoint_returns_aggregated_stats(monkeypatch, tmp_path) -> None:
    shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    with create_test_client(monkeypatch, tmp_path) as client:
        with session_scope() as db:
            db.add_all(
                [
                    StrategyRun(
                        trigger_source="manual",
                        run_type="analysis",
                        status="completed",
                        analysis_summary="today-1",
                        decision_payload={
                            "tool_calls": [
                                {"name": "mx_query_market"},
                                {"name": "mx_search_news"},
                                {"name": "mx_moni_trade"},
                            ]
                        },
                        executed_actions=[{"action": "BUY", "symbol": "300059"}],
                        llm_response_payload={
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 20,
                                "total_tokens": 30,
                            }
                        },
                        started_at=shanghai_now.replace(tzinfo=None),
                        finished_at=shanghai_now.replace(tzinfo=None),
                    ),
                    StrategyRun(
                        trigger_source="manual",
                        run_type="analysis",
                        status="failed",
                        analysis_summary="today-2",
                        decision_payload={
                            "tool_calls": [
                                {"name": "mx_get_balance"},
                            ]
                        },
                        llm_response_payload={
                            "usage": {
                                "prompt_tokens": 5,
                                "completion_tokens": 6,
                                "total_tokens": 11,
                            }
                        },
                        started_at=shanghai_now.replace(tzinfo=None),
                        finished_at=shanghai_now.replace(tzinfo=None),
                    ),
                ]
            )

        headers = _auth_headers(client)
        response = client.get("/api/aniu/runtime-overview", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["today"]["analysis_count"] == 2
    assert payload["today"]["api_calls"] == 3
    assert payload["today"]["trades"] == 1
    assert payload["today"]["success_rate"] == 50.0

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_account_endpoint_excludes_raw_payloads_by_default(monkeypatch, tmp_path) -> None:
    from app.services.aniu_service import aniu_service

    monkeypatch.setattr(
        aniu_service,
        "get_account_overview",
        lambda **kwargs: {
            "open_date": None,
            "daily_profit_trade_date": None,
            "operating_days": None,
            "initial_capital": None,
            "total_assets": None,
            "total_market_value": None,
            "cash_balance": None,
            "total_position_ratio": None,
            "holding_profit": None,
            "total_return_ratio": None,
            "nav": None,
            "daily_profit": None,
            "daily_return_ratio": None,
            "positions": [],
            "orders": [],
            "trade_summaries": [],
            "errors": [],
        },
    )

    with create_test_client(monkeypatch, tmp_path) as client:
        headers = _auth_headers(client)
        response = client.get("/api/aniu/account", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert "raw_balance" not in payload
    assert "raw_positions" not in payload
    assert "raw_orders" not in payload

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()


def test_account_debug_endpoint_includes_raw_payloads(monkeypatch, tmp_path) -> None:
    from app.services.aniu_service import aniu_service

    monkeypatch.setattr(
        aniu_service,
        "get_account_overview",
        lambda **kwargs: {
            "open_date": None,
            "daily_profit_trade_date": None,
            "operating_days": None,
            "initial_capital": None,
            "total_assets": None,
            "total_market_value": None,
            "cash_balance": None,
            "total_position_ratio": None,
            "holding_profit": None,
            "total_return_ratio": None,
            "nav": None,
            "daily_profit": None,
            "daily_return_ratio": None,
            "positions": [],
            "orders": [],
            "trade_summaries": [],
            "raw_balance": {"a": 1},
            "raw_positions": {"b": 2},
            "raw_orders": {"c": 3},
            "errors": [],
        },
    )

    with create_test_client(monkeypatch, tmp_path) as client:
        headers = _auth_headers(client)
        response = client.get("/api/aniu/account/debug", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_balance"] == {"a": 1}
    assert payload["raw_positions"] == {"b": 2}
    assert payload["raw_orders"] == {"c": 3}

    database_module._engine = None
    database_module._session_local = None
    get_settings.cache_clear()
