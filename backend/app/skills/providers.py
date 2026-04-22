"""Provider assembly helpers for skill execution contexts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.database import session_scope


def build_skill_context(
    *,
    run_type: str | None,
    app_settings: Any = None,
    client: Any = None,
    base_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.aniu_service import aniu_service

    context = dict(base_context or {})
    normalized_run_type = str(run_type or context.get("run_type") or "analysis").strip() or "analysis"
    context["run_type"] = normalized_run_type

    if app_settings is not None:
        context["app_settings"] = app_settings
    if client is not None:
        context["client"] = client

    context.setdefault(
        "chat_context_ports",
        {
            "get_account_overview": aniu_service.get_account_overview,
            "list_runs_page": aniu_service.list_runs_page,
            "get_run": aniu_service.get_run,
            "session_scope_factory": session_scope,
        },
    )

    app_settings_value = context.get("app_settings")
    mx_api_key = getattr(app_settings_value, "mx_api_key", None)
    mx_api_url = getattr(app_settings_value, "mx_api_url", None)
    context.setdefault(
        "mx_client_config",
        {
            "api_key": mx_api_key,
            "base_url": mx_api_url,
        },
    )

    skill_runtime_paths = context.get("skill_runtime_paths")
    if not isinstance(skill_runtime_paths, dict):
        skill_runtime_paths = {}
    skill_runtime_paths.setdefault(
        "builtin_skills_root",
        str(Path(__file__).resolve().parents[2] / "skills"),
    )
    context["skill_runtime_paths"] = skill_runtime_paths

    return context
