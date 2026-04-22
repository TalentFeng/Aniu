"""Shared execution context helpers for skill packages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SkillRuntimePaths:
    workspace_root: Path
    builtin_skills_root: Path
    chat_uploads_root: Path


@dataclass(frozen=True)
class ChatContextPorts:
    get_account_overview: Callable[..., dict[str, Any]]
    list_runs_page: Callable[..., dict[str, Any]]
    get_run: Callable[..., Any]
    session_scope_factory: Callable[[], Any]


@dataclass(frozen=True)
class MXClientConfig:
    api_key: str | None
    base_url: str


def _resolve_path(value: Any, *, fallback: Path) -> Path:
    raw = str(value or "").strip()
    path = Path(raw) if raw else fallback
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def get_skill_runtime_paths(
    context: dict[str, Any] | None,
    *,
    builtin_skills_root: Path,
) -> SkillRuntimePaths:
    payload = dict(context or {})
    provided = payload.get("skill_runtime_paths")
    if isinstance(provided, SkillRuntimePaths):
        return provided
    if isinstance(provided, dict):
        paths = SkillRuntimePaths(
            workspace_root=_resolve_path(
                provided.get("workspace_root"),
                fallback=Path.cwd() / "data" / "skill_workspace",
            ),
            builtin_skills_root=_resolve_path(
                provided.get("builtin_skills_root"),
                fallback=builtin_skills_root,
            ),
            chat_uploads_root=_resolve_path(
                provided.get("chat_uploads_root"),
                fallback=Path.cwd() / "data" / "chat_uploads",
            ),
        )
        if context is not None:
            context["skill_runtime_paths"] = paths
        return paths

    try:
        from app.core.config import (
            get_runtime_data_dir,
            get_settings,
            get_skill_workspace_root,
        )

        settings = get_settings()
        workspace_root = get_skill_workspace_root(settings)
        chat_uploads_root = get_runtime_data_dir(settings) / "chat_uploads"
    except Exception:
        workspace_root = Path.cwd() / "data" / "skill_workspace"
        chat_uploads_root = Path.cwd() / "data" / "chat_uploads"

    paths = SkillRuntimePaths(
        workspace_root=_resolve_path(workspace_root, fallback=workspace_root),
        builtin_skills_root=_resolve_path(builtin_skills_root, fallback=builtin_skills_root),
        chat_uploads_root=_resolve_path(chat_uploads_root, fallback=chat_uploads_root),
    )
    if context is not None:
        context["skill_runtime_paths"] = paths
    return paths


def get_chat_context_ports(context: dict[str, Any] | None) -> ChatContextPorts:
    payload = dict(context or {})
    provided = payload.get("chat_context_ports")
    if isinstance(provided, ChatContextPorts):
        return provided
    if isinstance(provided, dict):
        ports = ChatContextPorts(
            get_account_overview=provided["get_account_overview"],
            list_runs_page=provided["list_runs_page"],
            get_run=provided["get_run"],
            session_scope_factory=provided["session_scope_factory"],
        )
        if context is not None:
            context["chat_context_ports"] = ports
        return ports

    from app.db.database import session_scope
    from app.services.aniu_service import aniu_service

    ports = ChatContextPorts(
        get_account_overview=aniu_service.get_account_overview,
        list_runs_page=aniu_service.list_runs_page,
        get_run=aniu_service.get_run,
        session_scope_factory=session_scope,
    )
    if context is not None:
        context["chat_context_ports"] = ports
    return ports


def get_mx_client_config(context: dict[str, Any] | None) -> MXClientConfig:
    payload = dict(context or {})
    provided = payload.get("mx_client_config")
    if isinstance(provided, MXClientConfig):
        return provided
    if isinstance(provided, dict):
        config = MXClientConfig(
            api_key=(
                str(provided.get("api_key")).strip()
                if provided.get("api_key") is not None
                else None
            ),
            base_url=str(provided.get("base_url") or "").strip(),
        )
        if context is not None:
            context["mx_client_config"] = config
        return config

    app_settings = payload.get("app_settings")
    api_key = getattr(app_settings, "mx_api_key", None)
    base_url = getattr(app_settings, "mx_api_url", None)

    if not base_url:
        try:
            from app.core.config import get_settings

            settings = get_settings()
            api_key = api_key or settings.mx_apikey
            base_url = settings.mx_api_url
        except Exception:
            base_url = "https://mkapi2.dfcfs.com/finskillshub"

    config = MXClientConfig(
        api_key=str(api_key).strip() if api_key is not None and str(api_key).strip() else None,
        base_url=str(base_url or "https://mkapi2.dfcfs.com/finskillshub").strip(),
    )
    if context is not None:
        context["mx_client_config"] = config
    return config
