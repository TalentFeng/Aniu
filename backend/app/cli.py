from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.config import get_settings
from app.db.database import hash_password, init_db, session_scope
from app.db.models import User


def create_admin(username: str, password: str) -> int:
    with session_scope() as db:
        existing = db.scalar(select(User).where(User.username == username).limit(1))
        if existing is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role="admin",
                    credit_balance=0,
                    is_active=True,
                )
            )
            db.flush()
            return 0

        existing.password_hash = hash_password(password)
        existing.role = "admin"
        existing.is_active = True
        db.add(existing)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin_parser = subparsers.add_parser("create-admin")
    create_admin_parser.add_argument("--username", default=None)
    create_admin_parser.add_argument("--password", default=None)

    args = parser.parse_args()
    settings = get_settings()

    if args.command == "create-admin":
        username = str(args.username or settings.admin_username).strip()
        password = str(args.password or settings.admin_password or settings.app_login_password or "").strip()
        if not username:
            raise SystemExit("缺少管理员用户名，请提供 --username 或 ADMIN_USERNAME。")
        if not password:
            raise SystemExit("缺少管理员密码，请提供 --password 或 ADMIN_PASSWORD。")
        init_db()
        return create_admin(username, password)

    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
