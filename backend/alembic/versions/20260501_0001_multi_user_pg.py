"""multi-user pg baseline

Revision ID: 20260501_0001
Revises:
Create Date: 2026-05-01 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def _true() -> sa.TextClause:
    return sa.text("1")


def _false() -> sa.TextClause:
    return sa.text("0")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("credit_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=_true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_users_is_active", "users", ["is_active"], unique=False)

    op.create_table(
        "model_pricing",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("credit_cost", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=_true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("model_name", name="uq_model_pricing_model_name"),
    )
    op.create_index("ix_model_pricing_model_name", "model_pricing", ["model_name"], unique=True)
    op.create_index("ix_model_pricing_is_active", "model_pricing", ["is_active"], unique=False)

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("provider_name", sa.String(length=32), nullable=False, server_default="openai-compatible"),
        sa.Column("mx_api_key", sa.String(length=255), nullable=True),
        sa.Column("llm_base_url", sa.String(length=255), nullable=True),
        sa.Column("llm_api_key", sa.String(length=255), nullable=True),
        sa.Column("llm_model", sa.String(length=128), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("disabled_skill_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("analyst_prompt", sa.Text(), nullable=False),
        sa.Column("market_query", sa.String(length=255), nullable=False),
        sa.Column("news_query", sa.String(length=255), nullable=False),
        sa.Column("screener_query", sa.String(length=255), nullable=False),
        sa.Column("max_actions", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("trade_enabled", sa.Boolean(), nullable=False, server_default=_true()),
        sa.Column("automation_session_id", sa.Integer(), nullable=True),
        sa.Column("automation_context_window_tokens", sa.Integer(), nullable=True, server_default="128000"),
        sa.Column("automation_recent_message_limit", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("automation_enable_auto_compaction", sa.Boolean(), nullable=False, server_default=_true()),
        sa.Column("automation_idle_summary_hours", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("roundtable_enabled", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("roundtable_moderator", sa.JSON(), nullable=True),
        sa.Column("roundtable_participants", sa.JSON(), nullable=True),
        sa.Column("operation_notify_enabled", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("operation_notify_channel", sa.String(length=16), nullable=True),
        sa.Column("bark_server_url", sa.String(length=255), nullable=True),
        sa.Column("bark_device_key", sa.String(length=255), nullable=True),
        sa.Column("wecom_webhook_url", sa.String(length=512), nullable=True),
        sa.Column("automation_context_source", sa.String(length=32), nullable=True, server_default="default"),
        sa.Column("automation_context_detected_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", name="uq_app_settings_user_id"),
    )
    op.create_index("ix_app_settings_user_id", "app_settings", ["user_id"], unique=False)

    op.create_table(
        "strategy_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("name", sa.String(length=64), nullable=False, server_default="默认调度任务"),
        sa.Column("run_type", sa.String(length=32), nullable=False, server_default="analysis"),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("cron_expression", sa.String(length=64), nullable=True),
        sa.Column("task_prompt", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=_false()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("retry_after_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_strategy_schedules_user_id", "strategy_schedules", ["user_id"], unique=False)

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="新对话"),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("slug", sa.String(length=120), nullable=True),
        sa.Column("archived_summary", sa.Text(), nullable=True),
        sa.Column("summary_updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_compacted_message_id", sa.Integer(), nullable=True),
        sa.Column("last_compacted_run_id", sa.Integer(), nullable=True),
        sa.Column("summary_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "slug", name="uq_chat_sessions_user_slug"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)
    op.create_index("ix_chat_sessions_kind", "chat_sessions", ["kind"], unique=False)
    op.create_index("ix_chat_sessions_slug", "chat_sessions", ["slug"], unique=False)
    op.create_index("ix_chat_sessions_created_at", "chat_sessions", ["created_at"], unique=False)
    op.create_index("ix_chat_sessions_last_message_at", "chat_sessions", ["last_message_at"], unique=False)

    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("trigger_source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("run_type", sa.String(length=32), nullable=False, server_default="analysis"),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("schedule_name", sa.String(length=64), nullable=True),
        sa.Column("chat_session_id", sa.Integer(), nullable=True),
        sa.Column("prompt_message_id", sa.Integer(), nullable=True),
        sa.Column("response_message_id", sa.Integer(), nullable=True),
        sa.Column("context_summary_version", sa.Integer(), nullable=True),
        sa.Column("context_tokens_estimate", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("analysis_summary", sa.Text(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("llm_request_payload", sa.JSON(), nullable=True),
        sa.Column("llm_response_payload", sa.JSON(), nullable=True),
        sa.Column("skill_payloads", sa.JSON(), nullable=True),
        sa.Column("decision_payload", sa.JSON(), nullable=True),
        sa.Column("executed_actions", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_strategy_runs_user_id", "strategy_runs", ["user_id"], unique=False)
    op.create_index("ix_strategy_runs_schedule_id", "strategy_runs", ["schedule_id"], unique=False)
    op.create_index("ix_strategy_runs_chat_session_id", "strategy_runs", ["chat_session_id"], unique=False)
    op.create_index("ix_strategy_runs_status", "strategy_runs", ["status"], unique=False)
    op.create_index("ix_strategy_runs_started_at", "strategy_runs", ["started_at"], unique=False)

    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("related_run_id", sa.Integer(), sa.ForeignKey("strategy_runs.id"), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"], unique=False)
    op.create_index("ix_credit_transactions_type", "credit_transactions", ["type"], unique=False)
    op.create_index("ix_credit_transactions_related_run_id", "credit_transactions", ["related_run_id"], unique=False)

    op.create_table(
        "trade_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("strategy_runs.id"), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_type", sa.String(length=16), nullable=False, server_default="MARKET"),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="submitted"),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_trade_orders_user_id", "trade_orders", ["user_id"], unique=False)
    op.create_index("ix_trade_orders_run_id", "trade_orders", ["run_id"], unique=False)
    op.create_index("ix_trade_orders_symbol", "trade_orders", ["symbol"], unique=False)

    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, server_default="1"),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False, server_default="application/octet-stream"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chat_attachments_user_id", "chat_attachments", ["user_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("message_kind", sa.String(length=32), nullable=True),
        sa.Column("meta_payload", sa.JSON(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"], unique=False)
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"], unique=False)
    op.create_index("ix_chat_messages_run_id", "chat_messages", ["run_id"], unique=False)
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_messages_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_run_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_user_id", table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index("ix_chat_attachments_user_id", table_name="chat_attachments")
    op.drop_table("chat_attachments")

    op.drop_index("ix_trade_orders_symbol", table_name="trade_orders")
    op.drop_index("ix_trade_orders_run_id", table_name="trade_orders")
    op.drop_index("ix_trade_orders_user_id", table_name="trade_orders")
    op.drop_table("trade_orders")

    op.drop_index("ix_credit_transactions_related_run_id", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_type", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_user_id", table_name="credit_transactions")
    op.drop_table("credit_transactions")

    op.drop_index("ix_strategy_runs_started_at", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_status", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_chat_session_id", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_schedule_id", table_name="strategy_runs")
    op.drop_index("ix_strategy_runs_user_id", table_name="strategy_runs")
    op.drop_table("strategy_runs")

    op.drop_index("ix_chat_sessions_last_message_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_created_at", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_slug", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_kind", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.drop_index("ix_strategy_schedules_user_id", table_name="strategy_schedules")
    op.drop_table("strategy_schedules")

    op.drop_index("ix_app_settings_user_id", table_name="app_settings")
    op.drop_table("app_settings")

    op.drop_index("ix_model_pricing_is_active", table_name="model_pricing")
    op.drop_index("ix_model_pricing_model_name", table_name="model_pricing")
    op.drop_table("model_pricing")

    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
