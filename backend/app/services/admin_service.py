from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import hash_password
from app.db.models import CreditTransaction, ModelPricing, User
from app.schemas.aniu import AdminUserCreateRequest, ModelPricingBase

logger = logging.getLogger(__name__)


class AdminService:
    def list_users(self, db: Session) -> list[User]:
        stmt = select(User).order_by(User.created_at.asc(), User.id.asc())
        return list(db.scalars(stmt).all())

    def create_user(self, db: Session, payload: AdminUserCreateRequest) -> User:
        existing = db.scalar(
            select(User).where(User.username == payload.username).limit(1)
        )
        if existing is not None:
            raise FileExistsError("用户名已存在。")
        user = User(
            username=payload.username.strip(),
            password_hash=hash_password(payload.password),
            role=payload.role,
            credit_balance=payload.credit_balance,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("admin created user: user_id=%s role=%s", user.id, user.role)
        return user

    def set_user_active(self, db: Session, user_id: int, is_active: bool) -> User:
        user = db.get(User, user_id)
        if user is None:
            raise LookupError("用户不存在。")
        user.is_active = is_active
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("admin updated user status: user_id=%s active=%s", user.id, user.is_active)
        return user

    def adjust_credit(
        self,
        db: Session,
        *,
        user_id: int,
        amount: int,
        note: str | None,
        tx_type: str = "recharge",
        related_run_id: int | None = None,
    ) -> User:
        user = db.get(User, user_id)
        if user is None:
            raise LookupError("用户不存在。")
        new_balance = int(user.credit_balance or 0) + int(amount)
        if new_balance < 0:
            raise ValueError("credit 余额不足。")
        user.credit_balance = new_balance
        db.add(user)
        db.flush()
        db.add(
            CreditTransaction(
                user_id=user.id,
                amount=int(amount),
                balance_after=new_balance,
                type=tx_type,
                related_run_id=related_run_id,
                note=note,
            )
        )
        db.commit()
        db.refresh(user)
        logger.info(
            "credit adjusted: user_id=%s amount=%s balance=%s type=%s",
            user.id,
            amount,
            new_balance,
            tx_type,
        )
        return user

    def list_model_pricing(self, db: Session) -> list[ModelPricing]:
        stmt = select(ModelPricing).order_by(ModelPricing.model_name.asc())
        return list(db.scalars(stmt).all())

    def replace_model_pricing(
        self,
        db: Session,
        payloads: list[ModelPricingBase],
    ) -> list[ModelPricing]:
        existing = {
            item.model_name: item
            for item in db.scalars(select(ModelPricing)).all()
        }
        seen: set[str] = set()
        for payload in payloads:
            model_name = payload.model_name.strip()
            if not model_name:
                continue
            seen.add(model_name)
            item = existing.get(model_name)
            if item is None:
                item = ModelPricing(
                    model_name=model_name,
                    credit_cost=payload.credit_cost,
                    is_active=payload.is_active,
                )
            else:
                item.credit_cost = payload.credit_cost
                item.is_active = payload.is_active
            db.add(item)

        for model_name, item in existing.items():
            if model_name not in seen:
                item.is_active = False
                db.add(item)

        db.commit()
        logger.info("model pricing replaced: models=%s", sorted(seen))
        return self.list_model_pricing(db)

    def get_model_price(self, db: Session, model_name: str | None) -> int:
        normalized = str(model_name or "").strip()
        if not normalized:
            return 0
        item = db.scalar(
            select(ModelPricing)
            .where(
                ModelPricing.model_name == normalized,
                ModelPricing.is_active.is_(True),
            )
            .limit(1)
        )
        if item is None:
            return 1
        return max(int(item.credit_cost or 0), 0)


admin_service = AdminService()
