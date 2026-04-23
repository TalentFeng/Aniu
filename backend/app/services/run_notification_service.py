from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib import error, request


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunNotificationConfig:
    enabled: bool
    channel: str | None
    bark_server_url: str | None
    bark_device_key: str | None
    wecom_webhook_url: str | None

    @classmethod
    def from_settings(cls, settings: Any) -> "RunNotificationConfig":
        channel = str(getattr(settings, "operation_notify_channel", "") or "").strip().lower()
        return cls(
            enabled=bool(getattr(settings, "operation_notify_enabled", False)),
            channel=channel or None,
            bark_server_url=str(getattr(settings, "bark_server_url", "") or "").strip() or None,
            bark_device_key=str(getattr(settings, "bark_device_key", "") or "").strip() or None,
            wecom_webhook_url=str(getattr(settings, "wecom_webhook_url", "") or "").strip() or None,
        )

    def is_configured(self) -> bool:
        if not self.enabled:
            return False
        if self.channel == "bark":
            return bool(self.bark_server_url and self.bark_device_key)
        if self.channel == "wecom":
            return bool(self.wecom_webhook_url)
        return False


class RunNotificationService:
    def send_run_result(
        self,
        *,
        settings: Any,
        run: Any,
        error_message: str | None = None,
    ) -> None:
        config = RunNotificationConfig.from_settings(settings)
        if not config.is_configured():
            return

        title, body = self._build_message(run=run, error_message=error_message)
        try:
            if config.channel == "bark":
                self._send_bark(config=config, title=title, body=body)
                return
            if config.channel == "wecom":
                self._send_wecom(config=config, title=title, body=body)
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "run notification failed: run_id=%s, channel=%s, error=%s",
                getattr(run, "id", None),
                config.channel,
                exc,
            )

    def _build_message(self, *, run: Any, error_message: str | None) -> tuple[str, str]:
        status = str(getattr(run, "status", "") or "").strip().lower()
        run_id = getattr(run, "id", None)
        run_type = str(getattr(run, "run_type", "") or "analysis").strip() or "analysis"
        trigger_source = str(getattr(run, "trigger_source", "") or "manual").strip() or "manual"
        schedule_name = str(getattr(run, "schedule_name", "") or "").strip()
        analysis_summary = str(getattr(run, "analysis_summary", "") or "").strip()
        final_answer = str(getattr(run, "final_answer", "") or "").strip()
        actions = getattr(run, "executed_actions", None)
        executed_actions = actions if isinstance(actions, list) else []
        trade_actions = [
            item for item in executed_actions
            if isinstance(item, dict) and str(item.get("action") or "").upper() in {"BUY", "SELL"}
        ]

        action_lines = []
        for item in trade_actions[:5]:
            action_name = "卖出" if str(item.get("action") or "").upper() == "SELL" else "买入"
            symbol = str(item.get("symbol") or "--")
            quantity = int(item.get("quantity") or 0)
            price = item.get("price")
            if price in (None, ""):
                action_lines.append(f"- {action_name} {symbol} x {quantity}")
            else:
                action_lines.append(f"- {action_name} {symbol} x {quantity} @ {price}")

        if len(trade_actions) > len(action_lines):
            action_lines.append(f"- 其余 {len(trade_actions) - len(action_lines)} 条已省略")

        title = "Aniu 任务失败" if status == "failed" else "Aniu 任务完成"
        lines = [
            f"运行 ID: #{run_id}" if run_id is not None else "运行 ID: --",
            f"运行类型: {run_type}",
            f"触发方式: {trigger_source}",
        ]
        if schedule_name:
            lines.append(f"任务名称: {schedule_name}")
        lines.append(f"状态: {status or '--'}")
        if trade_actions:
            lines.append(f"执行交易: {len(trade_actions)} 条")
            lines.extend(action_lines)
        if status == "failed" and error_message:
            lines.append(f"错误: {error_message}")
        elif analysis_summary:
            lines.append(f"摘要: {analysis_summary[:200]}")
        elif final_answer:
            lines.append(f"结果: {final_answer[:200]}")

        return title, "\n".join(lines)

    def _send_bark(
        self,
        *,
        config: RunNotificationConfig,
        title: str,
        body: str,
    ) -> None:
        server_url = str(config.bark_server_url or "https://api.day.app").rstrip("/")
        payload = {
            "device_key": config.bark_device_key,
            "title": title,
            "body": body,
        }
        self._post_json(f"{server_url}/push", payload)

    def _send_wecom(
        self,
        *,
        config: RunNotificationConfig,
        title: str,
        body: str,
    ) -> None:
        payload = {
            "msgtype": "text",
            "text": {
                "content": f"{title}\n{body}",
            },
        }
        self._post_json(str(config.wecom_webhook_url), payload)

    def _post_json(self, url: str, payload: dict[str, Any]) -> None:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=8) as response:
                status_code = getattr(response, "status", None) or response.getcode()
                if int(status_code) >= 400:
                    raise RuntimeError(f"notification http status {status_code}")
        except error.URLError as exc:
            raise RuntimeError("notification request failed") from exc


run_notification_service = RunNotificationService()
