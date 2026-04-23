from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from skills.mx_core.client import MXClient

from app.services.llm_service import llm_service


@dataclass(slots=True)
class RoundtableParticipant:
    id: str
    name: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str


class RoundtableService:
    def is_enabled(self, settings: Any) -> bool:
        participants = self._enabled_participants(settings)
        moderator = self._moderator(settings)
        return bool(getattr(settings, "roundtable_enabled", False)) and moderator is not None and len(participants) >= 2

    def run_chat_roundtable(
        self,
        *,
        settings: Any,
        messages: list[dict[str, Any]],
        emit: Any = None,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        participants = self._enabled_participants(settings)
        moderator = self._moderator(settings)
        if moderator is None or len(participants) < 2:
            raise RuntimeError("圆桌会议至少需要 1 个主持人和 2 个启用的参与者。")

        _emit = emit if callable(emit) else (lambda *_a, **_kw: None)
        speeches: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        transcript_markdown = ""

        for index, participant in enumerate(participants, start=1):
            _emit("stage", stage="roundtable_participant", message=f"{participant.name} 发言中", participant=participant.name)
            try:
                content = llm_service.chat(
                    model=participant.llm_model,
                    base_url=participant.llm_base_url,
                    api_key=participant.llm_api_key,
                    system_prompt=self._participant_prompt(settings, participant.name),
                    messages=messages,
                    timeout_seconds=180,
                    tool_context={"app_settings": settings},
                    emit=emit,
                    cancel_event=cancel_event,
                )
                speeches.append(
                    {
                        "id": participant.id,
                        "name": participant.name,
                        "content": content,
                        "status": "completed",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "id": participant.id,
                        "name": participant.name,
                        "error": str(exc),
                        "status": "failed",
                    }
                )
                _emit(
                    "stage",
                    stage="roundtable_participant_failed",
                    message=f"{participant.name} 发言失败：{exc}",
                    participant=participant.name,
                )
            transcript_markdown = self._format_roundtable_markdown(
                speeches=speeches,
                failures=failures,
                moderator_name=moderator.name,
                summary=None,
            )
            _emit("llm_message", iteration=index, content=transcript_markdown)

        if not speeches:
            raise RuntimeError("所有圆桌参与者均执行失败，无法生成总结。")

        _emit("stage", stage="roundtable_moderator", message=f"{moderator.name} 总结中", participant=moderator.name)
        summary = llm_service.chat(
            model=moderator.llm_model,
            base_url=moderator.llm_base_url,
            api_key=moderator.llm_api_key,
            system_prompt=self._moderator_prompt(settings, moderator.name),
            messages=[
                {
                    "role": "user",
                    "content": self._build_moderator_input(messages=messages, speeches=speeches),
                }
            ],
            timeout_seconds=180,
            tool_context={"app_settings": settings},
            emit=emit,
            cancel_event=cancel_event,
        )

        return {
            "content": self._format_roundtable_markdown(
                speeches=speeches,
                failures=failures,
                moderator_name=moderator.name,
                summary=summary,
            ),
            "roundtable": {
                "enabled": True,
                "moderator": {
                    "id": moderator.id,
                    "name": moderator.name,
                },
                "speeches": speeches,
                "failures": failures,
                "summary": summary,
            },
        }

    def run_analysis_roundtable(
        self,
        *,
        settings: Any,
        client: MXClient,
        messages: list[dict[str, Any]],
        emit: Any = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        participants = self._enabled_participants(settings)
        moderator = self._moderator(settings)
        if moderator is None or len(participants) < 2:
            raise RuntimeError("圆桌会议至少需要 1 个主持人和 2 个启用的参与者。")

        _emit = emit if callable(emit) else (lambda *_a, **_kw: None)
        speeches: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        aggregated_tool_calls: list[dict[str, Any]] = []
        participant_requests: list[dict[str, Any]] = []
        participant_responses: list[dict[str, Any]] = []
        participant_traces: list[dict[str, Any]] = []

        for index, participant in enumerate(participants, start=1):
            participant_settings = self._participant_settings(
                settings=settings,
                participant=participant,
                system_prompt=self._participant_prompt(settings, participant.name),
            )
            _emit("stage", stage="roundtable_participant", message=f"{participant.name} 发言中", participant=participant.name)
            try:
                decision, request_payload, response_payload, runtime_trace = (
                    llm_service.run_agent_with_messages(
                        app_settings=participant_settings,
                        client=client,
                        messages=messages,
                        emit=emit,
                    )
                )
                content = str(decision.get("final_answer") or "").strip() or "该参与者未给出明确结论。"
                speeches.append(
                    {
                        "id": participant.id,
                        "name": participant.name,
                        "content": content,
                        "status": "completed",
                    }
                )
                tool_calls = decision.get("tool_calls")
                if isinstance(tool_calls, list):
                    for item in tool_calls:
                        if not isinstance(item, dict):
                            continue
                        enriched = dict(item)
                        enriched["speaker_name"] = participant.name
                        aggregated_tool_calls.append(enriched)
                participant_requests.append(
                    {
                        "participant_id": participant.id,
                        "participant_name": participant.name,
                        "request": request_payload,
                    }
                )
                participant_responses.append(
                    {
                        "participant_id": participant.id,
                        "participant_name": participant.name,
                        "response": response_payload,
                    }
                )
                participant_traces.append(
                    {
                        "participant_id": participant.id,
                        "participant_name": participant.name,
                        "trace": runtime_trace,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "id": participant.id,
                        "name": participant.name,
                        "error": str(exc),
                        "status": "failed",
                    }
                )
                _emit(
                    "stage",
                    stage="roundtable_participant_failed",
                    message=f"{participant.name} 发言失败：{exc}",
                    participant=participant.name,
                )
            _emit(
                "llm_message",
                iteration=index,
                content=self._format_roundtable_markdown(
                    speeches=speeches,
                    failures=failures,
                    moderator_name=moderator.name,
                    summary=None,
                ),
            )

        if not speeches:
            raise RuntimeError("所有圆桌参与者均执行失败，无法生成总结。")

        _emit("stage", stage="roundtable_moderator", message=f"{moderator.name} 总结中", participant=moderator.name)
        moderator_settings = self._participant_settings(
            settings=settings,
            participant=moderator,
            system_prompt=self._moderator_prompt(settings, moderator.name),
            run_type="chat",
        )
        summary = llm_service.chat(
            model=moderator_settings.llm_model,
            base_url=moderator_settings.llm_base_url,
            api_key=moderator_settings.llm_api_key,
            system_prompt=moderator_settings.system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": self._build_moderator_input(messages=messages, speeches=speeches),
                }
            ],
            timeout_seconds=int(getattr(settings, "timeout_seconds", 1800) or 1800),
            tool_context={"app_settings": moderator_settings, "client": client},
            emit=emit,
        )

        final_answer = self._format_roundtable_markdown(
            speeches=speeches,
            failures=failures,
            moderator_name=moderator.name,
            summary=summary,
        )
        return (
            {
                "final_answer": final_answer,
                "tool_calls": aggregated_tool_calls,
                "roundtable": {
                    "enabled": True,
                    "moderator": {"id": moderator.id, "name": moderator.name},
                    "speeches": speeches,
                    "failures": failures,
                    "summary": summary,
                },
            },
            {
                "participants": participant_requests,
                "moderator": {
                    "name": moderator.name,
                    "prompt": self._build_moderator_input(messages=messages, speeches=speeches),
                    "model": moderator.llm_model,
                },
            },
            {
                "participants": participant_responses,
                "moderator": {
                    "name": moderator.name,
                    "summary": summary,
                },
            },
            {
                "participants": participant_traces,
                "moderator": {"name": moderator.name, "summary": summary},
            },
        )

    def _enabled_participants(self, settings: Any) -> list[RoundtableParticipant]:
        raw_items = getattr(settings, "roundtable_participants", None) or []
        items: list[RoundtableParticipant] = []
        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            if not bool(item.get("enabled", True)):
                continue
            resolved = self._resolve_participant(settings, item, fallback_id=f"participant-{index}")
            if resolved is not None:
                items.append(resolved)
        return items

    def _moderator(self, settings: Any) -> RoundtableParticipant | None:
        raw = getattr(settings, "roundtable_moderator", None)
        if not isinstance(raw, dict):
            return None
        return self._resolve_participant(settings, raw, fallback_id="moderator")

    def _resolve_participant(
        self,
        settings: Any,
        item: dict[str, Any],
        *,
        fallback_id: str,
    ) -> RoundtableParticipant | None:
        base_url = str(item.get("llm_base_url") or getattr(settings, "llm_base_url", "") or "").strip()
        api_key = str(item.get("llm_api_key") or getattr(settings, "llm_api_key", "") or "").strip()
        model = str(item.get("llm_model") or getattr(settings, "llm_model", "") or "").strip()
        name = str(item.get("name") or "").strip()
        if not (base_url and api_key and model and name):
            return None
        return RoundtableParticipant(
            id=str(item.get("id") or fallback_id),
            name=name,
            llm_base_url=base_url,
            llm_api_key=api_key,
            llm_model=model,
        )

    def _participant_prompt(self, settings: Any, name: str) -> str:
        base_prompt = str(getattr(settings, "system_prompt", "") or "").strip()
        suffix = (
            f"你是圆桌会议参与者【{name}】。"
            "请独立给出观点，不要假装知道其他参与者的意见。"
            "输出请尽量包含：结论、核心理由、风险提示、若有必要的后续观察点。"
        )
        return "\n\n".join(part for part in (base_prompt, suffix) if part)

    def _moderator_prompt(self, settings: Any, name: str) -> str:
        base_prompt = str(getattr(settings, "system_prompt", "") or "").strip()
        suffix = (
            f"你是圆桌会议主持人【{name}】。"
            "你的任务是阅读所有参与者发言，提炼共识、分歧、关键风险，并给出最后总结。"
            "不要重复抄写原文，优先做压缩、归纳和结论化表达。"
        )
        return "\n\n".join(part for part in (base_prompt, suffix) if part)

    def _build_moderator_input(
        self,
        *,
        messages: list[dict[str, Any]],
        speeches: list[dict[str, Any]],
    ) -> str:
        latest_user = ""
        for item in reversed(messages):
            if str(item.get("role") or "") == "user":
                latest_user = str(item.get("content") or "").strip()
                if latest_user:
                    break
        speech_blocks = [
            f"### {speech['name']}\n{str(speech.get('content') or '').strip()}"
            for speech in speeches
        ]
        parts = [
            "请基于以下圆桌发言生成最终总结。",
            f"原始问题：\n{latest_user}" if latest_user else "",
            "\n\n".join(speech_blocks),
        ]
        return "\n\n".join(part for part in parts if part)

    def _format_roundtable_markdown(
        self,
        *,
        speeches: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        moderator_name: str,
        summary: str | None,
    ) -> str:
        parts = ["## 圆桌会议纪要"]
        for speech in speeches:
            speaker_name = str(speech.get("name") or "参与者").strip()
            content = str(speech.get("content") or "").strip()
            parts.append(f"### {speaker_name}\n{content or '暂无发言'}")
        if failures:
            failure_lines = [
                f"- {str(item.get('name') or '参与者')}: {str(item.get('error') or '执行失败')}"
                for item in failures
            ]
            parts.append("### 未成功发言的参与者\n" + "\n".join(failure_lines))
        if summary is not None:
            parts.append(f"## 主持人总结（{moderator_name}）\n{str(summary or '').strip()}")
        return "\n\n".join(parts).strip()

    def _participant_settings(
        self,
        *,
        settings: Any,
        participant: RoundtableParticipant,
        system_prompt: str,
        run_type: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            mx_api_key=getattr(settings, "mx_api_key", None),
            system_prompt=system_prompt,
            llm_model=participant.llm_model,
            llm_base_url=participant.llm_base_url,
            llm_api_key=participant.llm_api_key,
            timeout_seconds=int(getattr(settings, "timeout_seconds", 1800) or 1800),
            run_type=str(run_type or getattr(settings, "run_type", "analysis") or "analysis"),
        )


roundtable_service = RoundtableService()
