"""mx_core skill — delegates to the legacy mx_skill_service for now.

The legacy module already implements tool specs, handlers, run-type filters
and error hints. We wrap it here so the new skill registry can load / enable /
disable it like any other skill, without touching the battle-tested code path.
"""
from __future__ import annotations

from typing import Any

from app.skills.base import BaseSkill
from app.services.mx_service import MXClient
from app.services.mx_skill_service import _TOOL_PROFILES, mx_skill_service


def _load_specs() -> list[dict[str, Any]]:
    return [spec.to_openai_tool() for spec in mx_skill_service._tool_specs]


class Skill(BaseSkill):
    id = "mx_core"
    name = "妙想核心"
    description = "东方财富妙想 OpenAPI 与 A 股模拟交易工具集"
    run_types = ["analysis", "trade", "chat"]

    def __init__(self) -> None:
        self.tools = _load_specs()
        self.tool_run_type_filter = {}
        for run_type, tool_names in _TOOL_PROFILES.items():
            for tool_name in tool_names:
                self.tool_run_type_filter.setdefault(tool_name, set()).add(run_type)

    def handle(self, *, tool_name, arguments, context):
        app_settings = context.get("app_settings")
        client = context.get("client")
        if client is not None:
            return mx_skill_service.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                client=client,
                app_settings=app_settings,
            )

        with MXClient(api_key=getattr(app_settings, "mx_api_key", None)) as runtime_client:
            return mx_skill_service.execute_tool(
                tool_name=tool_name,
                arguments=arguments,
                client=runtime_client,
                app_settings=app_settings,
            )
