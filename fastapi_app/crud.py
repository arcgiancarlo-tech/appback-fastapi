import json
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .models import BillingIntegrationConfig, Category, ComfyUIServer, CreditPack, CreditPackConfig, FileAsset, Generation, RevenueCatWebhookEvent, Template, TemplatePageDisplayConfig, ThemeSettings, User
from .schemas import BillingIntegrationConfigUpdate, CategoryUpdate, ComfyUIServerUpdate, GenerationResultCreate, GenerationStatusUpdate, TemplatePageDisplayConfigUpdate, TemplateUpdate, ThemeSettingsUpdate
from .storage import copy_source_into_job, decode_base64_content, sanitize_filename, store_job_result_bytes


PENDING_STATUSES = ["pending", "processing", "uploaded", "queued", "running"]

DEFAULT_CREDIT_PACK_CONFIGS = [
    {"slot_number": 1, "credit_amount": 50, "price": 4.99, "display_price_text": "€4.99", "product_key": "credit_pack_1"},
    {"slot_number": 2, "credit_amount": 120, "price": 10.99, "display_price_text": "€10.99", "product_key": "credit_pack_2"},
    {"slot_number": 3, "credit_amount": 300, "price": 23.99, "display_price_text": "€23.99", "product_key": "credit_pack_3"},
    {"slot_number": 4, "credit_amount": 1000, "price": 59.99, "display_price_text": "€59.99", "product_key": "credit_pack_4"},
    {"slot_number": 5, "credit_amount": 5000, "price": 199.99, "display_price_text": "€199.99", "product_key": "credit_pack_5"},
]

DEFAULT_BILLING_PROVIDER_CONFIG = {
    "provider": "RevenueCat",
    "environment": "test",
    "connection_status": "disconnected",
    "public_api_key": "",
    "secret_key": "",
    "project_id": "",
    "notes": "",
}

DEFAULT_THEME_SETTINGS = {
    "primary_color": "#d8a64a",
    "secondary_color": "#c58d2a",
    "accent_color": "#b45309",
    "background_color": "#111111",
    "card_color": "#1b1b1b",
    "text_color": "#ffffff",
}

TEMPLATE_PAGE_TYPES = {"templates", "spicy_templates"}
TEMPLATE_PAGE_TYPE_ALIASES = {
    "main_templates": "templates",
    "templates": "templates",
    "spicy_templates": "spicy_templates",
}


def _ensure_credit_pack_configs(db: Session):
    existing = {row.slot_number: row for row in db.query(CreditPackConfig).all()}
    created = False
    for default in DEFAULT_CREDIT_PACK_CONFIGS:
        if default["slot_number"] in existing:
            continue
        row = CreditPackConfig(
            slot_number=default["slot_number"],
            credit_amount=default["credit_amount"],
            price=default["price"],
            display_price_text=default["display_price_text"],
            product_key=default["product_key"],
            active=True,
        )
        db.add(row)
        created = True
    if created:
        db.commit()


def _get_credit_pack_config_by_slot(db: Session, slot_number: int):
    return db.query(CreditPackConfig).filter(CreditPackConfig.slot_number == slot_number).first()


def get_billing_integration_config(db: Session):
    row = db.query(BillingIntegrationConfig).order_by(BillingIntegrationConfig.id.asc()).first()
    if row:
        return row

    row = BillingIntegrationConfig(**DEFAULT_BILLING_PROVIDER_CONFIG)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_billing_integration_config(db: Session, payload: BillingIntegrationConfigUpdate):
    row = get_billing_integration_config(db)
    data = payload.model_dump()
    data["provider"] = data["provider"].strip()
    data["environment"] = data["environment"].strip().lower()
    data["connection_status"] = data["connection_status"].strip().lower()
    data["public_api_key"] = data["public_api_key"].strip()
    data["secret_key"] = data["secret_key"].strip()
    data["project_id"] = data["project_id"].strip()
    data["notes"] = data["notes"].strip()

    for field, value in data.items():
        setattr(row, field, value)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_categories(db: Session, include_inactive: bool = True):
    q = db.query(Category)
    if not include_inactive:
        q = q.filter(Category.is_active.is_(True))
    return q.order_by(Category.name.asc(), Category.id.asc()).all()


def create_category(db: Session, name: str, is_active: bool = True):
    normalized = name.strip()
    existing = db.query(Category).filter(func.lower(Category.name) == normalized.lower()).first()
    if existing:
        raise ValueError(f"Category '{normalized}' already exists")
    row = Category(name=normalized, is_active=is_active)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_category(db: Session, category_id: int, payload: CategoryUpdate):
    row = db.query(Category).filter(Category.id == category_id).first()
    if not row:
        return None
    updates = payload.model_dump(exclude_unset=True)
    old_name = row.name
    if "name" in updates and updates["name"] is not None:
        new_name = updates["name"].strip()
        existing = db.query(Category).filter(func.lower(Category.name) == new_name.lower(), Category.id != category_id).first()
        if existing:
            raise ValueError(f"Category '{new_name}' already exists")
        row.name = new_name
        db.query(Template).filter(Template.category == old_name).update({Template.category: new_name}, synchronize_session=False)
    if "is_active" in updates:
        row.is_active = updates["is_active"]
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_category(db: Session, category_id: int):
    row = db.query(Category).filter(Category.id == category_id).first()
    if not row:
        return None
    db.query(Template).filter(Template.category == row.name).update({Template.category: None}, synchronize_session=False)
    db.delete(row)
    db.commit()
    return row


def _normalize_template_page_type(page_type: str) -> str:
    normalized = (page_type or "").strip().lower()
    normalized = TEMPLATE_PAGE_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in TEMPLATE_PAGE_TYPES:
        raise ValueError("page_type must be one of: templates, spicy_templates")
    return normalized


def _get_template_page_display_config_query(db: Session, page_type: Optional[str] = None, public_only: bool = False):
    q = db.query(TemplatePageDisplayConfig).join(Category, TemplatePageDisplayConfig.category_id == Category.id)
    if page_type is not None:
        q = q.filter(TemplatePageDisplayConfig.page_type == _normalize_template_page_type(page_type))
    if public_only:
        q = q.filter(Category.is_active.is_(True))
    return q.order_by(
        TemplatePageDisplayConfig.page_type.asc(),
        TemplatePageDisplayConfig.order.asc(),
        TemplatePageDisplayConfig.id.asc(),
    )


def list_template_page_display_configs(
    db: Session,
    page_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    public_only: bool = False,
):
    return _get_template_page_display_config_query(db, page_type=page_type, public_only=public_only).offset(skip).limit(limit).all()


def get_template_page_display_config(db: Session, config_id: int):
    return (
        db.query(TemplatePageDisplayConfig)
        .join(Category, TemplatePageDisplayConfig.category_id == Category.id)
        .filter(TemplatePageDisplayConfig.id == config_id)
        .first()
    )


def _validate_template_page_display_config(db: Session, page_type: str, category_id: int, order: int, exclude_id: Optional[int] = None):
    normalized_page_type = _normalize_template_page_type(page_type)
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise ValueError(f"Category {category_id} does not exist")

    duplicate_category = db.query(TemplatePageDisplayConfig).filter(
        TemplatePageDisplayConfig.page_type == normalized_page_type,
        TemplatePageDisplayConfig.category_id == category_id,
    )
    duplicate_order = db.query(TemplatePageDisplayConfig).filter(
        TemplatePageDisplayConfig.page_type == normalized_page_type,
        TemplatePageDisplayConfig.order == order,
    )
    if exclude_id is not None:
        duplicate_category = duplicate_category.filter(TemplatePageDisplayConfig.id != exclude_id)
        duplicate_order = duplicate_order.filter(TemplatePageDisplayConfig.id != exclude_id)

    if duplicate_category.first():
        raise ValueError("Each category can only appear once per page_type")
    if duplicate_order.first():
        raise ValueError("Each order value can only appear once per page_type")

    return normalized_page_type


def create_template_page_display_config(db: Session, page_type: str, category_id: int, order: int):
    normalized_page_type = _validate_template_page_display_config(db, page_type=page_type, category_id=category_id, order=order)
    row = TemplatePageDisplayConfig(page_type=normalized_page_type, category_id=category_id, order=order)
    db.add(row)
    db.commit()
    return get_template_page_display_config(db, row.id)


def update_template_page_display_config(db: Session, config_id: int, payload: TemplatePageDisplayConfigUpdate):
    row = db.query(TemplatePageDisplayConfig).filter(TemplatePageDisplayConfig.id == config_id).first()
    if not row:
        return None

    updates = payload.model_dump(exclude_unset=True)
    next_page_type = updates.get("page_type", row.page_type)
    next_category_id = updates.get("category_id", row.category_id)
    next_order = updates.get("order", row.order)
    normalized_page_type = _validate_template_page_display_config(
        db,
        page_type=next_page_type,
        category_id=next_category_id,
        order=next_order,
        exclude_id=config_id,
    )

    row.page_type = normalized_page_type
    row.category_id = next_category_id
    row.order = next_order
    db.add(row)
    db.commit()
    return get_template_page_display_config(db, row.id)


def delete_template_page_display_config(db: Session, config_id: int):
    row = get_template_page_display_config(db, config_id)
    if not row:
        return None
    db.delete(row)
    db.commit()
    return row


def get_theme_settings(db: Session):
    row = db.query(ThemeSettings).order_by(ThemeSettings.id.asc()).first()
    if row:
        return row
    row = ThemeSettings(**DEFAULT_THEME_SETTINGS)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_theme_settings(db: Session, payload: ThemeSettingsUpdate):
    row = get_theme_settings(db)
    for field, value in payload.model_dump().items():
        setattr(row, field, value.strip())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_product_credit_map():
    raw = os.getenv("REVENUECAT_PRODUCT_CREDITS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(key): int(value) for key, value in parsed.items()}


def _resolve_credits_revoked(event: dict) -> int:
    for key in ("credits_revoked", "credits", "credit_amount"):
        value = event.get(key)
        if value is not None:
            try:
                return abs(int(value))
            except (TypeError, ValueError):
                pass
    product_id = event.get("product_id")
    return _get_product_credit_map().get(str(product_id), 0)


def _resolve_amount(event: dict) -> float:
    for key in ("amount", "price", "price_in_purchased_currency"):
        value = event.get(key)
        if value is not None:
            try:
                return abs(float(value))
            except (TypeError, ValueError):
                pass
    return 0.0


def _normalize_refund_kind(event_type: str, cancel_reason: Optional[str]) -> Optional[str]:
    event_type_upper = (event_type or "").upper()
    cancel_reason_upper = (cancel_reason or "").upper()
    if "CHARGEBACK" in event_type_upper or "CHARGEBACK" in cancel_reason_upper:
        return "chargeback"
    if event_type_upper in {"REFUND", "REFUNDED"}:
        return "refund"
    if event_type_upper == "CANCELLATION":
        if any(token in cancel_reason_upper for token in ["CHARGEBACK", "REVOKE"]):
            return "chargeback"
        if any(token in cancel_reason_upper for token in ["REFUND", "SUPPORT", "CUSTOMER", "FRAUD"]):
            return "refund"
    return None


def _parse_event_timestamp(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def get_user_by_revenuecat_app_user_id(db: Session, app_user_id: str):
    if app_user_id is None:
        return None
    normalized = str(app_user_id).strip()
    if not normalized:
        return None
    if normalized.isdigit():
        user = get_user_by_id(db, int(normalized))
        if user:
            return user
    return db.query(User).filter(User.email == normalized).first()


def get_revenuecat_event_by_event_id(db: Session, event_id: str):
    return db.query(RevenueCatWebhookEvent).filter(RevenueCatWebhookEvent.event_id == event_id).first()


def create_revenuecat_refund_event(db: Session, event: dict):
    event_id = str(event.get("id") or event.get("event_id") or "").strip()
    if not event_id:
        raise ValueError("RevenueCat event is missing id")

    existing = get_revenuecat_event_by_event_id(db, event_id)
    if existing:
        return existing, False

    event_type = str(event.get("type") or event.get("event_type") or "").strip()
    cancel_reason = event.get("cancel_reason")
    refund_kind = _normalize_refund_kind(event_type, cancel_reason)
    if refund_kind is None:
        return None, False

    app_user_id = str(event.get("app_user_id") or "").strip()
    if not app_user_id:
        raise ValueError("RevenueCat refund event is missing app_user_id")

    user = get_user_by_revenuecat_app_user_id(db, app_user_id)
    if not user:
        raise ValueError(f"No user matched RevenueCat app_user_id '{app_user_id}'")

    record = RevenueCatWebhookEvent(
        event_id=event_id,
        user_id=user.id,
        event_type=event_type or "unknown",
        refund_kind=refund_kind,
        app_user_id=app_user_id,
        product_id=event.get("product_id"),
        transaction_id=event.get("transaction_id"),
        original_transaction_id=event.get("original_transaction_id"),
        currency=event.get("currency") or event.get("currency_code"),
        amount=_resolve_amount(event),
        credits_revoked=_resolve_credits_revoked(event),
        cancel_reason=cancel_reason,
        environment=event.get("environment"),
        raw_payload=json.dumps(event, sort_keys=True),
        event_timestamp=_parse_event_timestamp(event.get("event_timestamp_ms") or event.get("event_timestamp") or event.get("purchased_at_ms")),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, True


def get_revenuecat_refund_report(db: Session, user_id: Optional[int] = None, limit: int = 100):
    q = db.query(RevenueCatWebhookEvent).order_by(RevenueCatWebhookEvent.processed_at.desc(), RevenueCatWebhookEvent.id.desc())
    if user_id is not None:
        q = q.filter(RevenueCatWebhookEvent.user_id == user_id)
    events = q.limit(limit).all()
    refunded_credits = sum(event.credits_revoked for event in events if event.refund_kind == "refund")
    chargeback_credits = sum(event.credits_revoked for event in events if event.refund_kind == "chargeback")
    refunded_amount = sum(event.amount for event in events if event.refund_kind == "refund")
    chargeback_amount = sum(event.amount for event in events if event.refund_kind == "chargeback")
    return {
        "total_events": len(events),
        "refund_event_count": sum(1 for event in events if event.refund_kind == "refund"),
        "chargeback_event_count": sum(1 for event in events if event.refund_kind == "chargeback"),
        "total_credits_revoked": refunded_credits + chargeback_credits,
        "refunded_credits": refunded_credits,
        "chargeback_credits": chargeback_credits,
        "total_amount_reversed": refunded_amount + chargeback_amount,
        "refunded_amount": refunded_amount,
        "chargeback_amount": chargeback_amount,
        "events": events,
    }


def _get_revenuecat_reversal_totals(db: Session, user_id: Optional[int] = None):
    q = db.query(RevenueCatWebhookEvent)
    if user_id is not None:
        q = q.filter(RevenueCatWebhookEvent.user_id == user_id)

    refunded_credits = (
        q.with_entities(func.coalesce(func.sum(case((RevenueCatWebhookEvent.refund_kind == "refund", RevenueCatWebhookEvent.credits_revoked), else_=0)), 0)).scalar()
        or 0
    )
    chargeback_credits = (
        q.with_entities(func.coalesce(func.sum(case((RevenueCatWebhookEvent.refund_kind == "chargeback", RevenueCatWebhookEvent.credits_revoked), else_=0)), 0)).scalar()
        or 0
    )
    refunded_amount = (
        q.with_entities(func.coalesce(func.sum(case((RevenueCatWebhookEvent.refund_kind == "refund", RevenueCatWebhookEvent.amount), else_=0.0)), 0.0)).scalar()
        or 0.0
    )
    chargeback_amount = (
        q.with_entities(func.coalesce(func.sum(case((RevenueCatWebhookEvent.refund_kind == "chargeback", RevenueCatWebhookEvent.amount), else_=0.0)), 0.0)).scalar()
        or 0.0
    )
    refund_event_count = q.filter(RevenueCatWebhookEvent.refund_kind == "refund").count()
    chargeback_event_count = q.filter(RevenueCatWebhookEvent.refund_kind == "chargeback").count()
    return {
        "refunded_credits": refunded_credits,
        "chargeback_credits": chargeback_credits,
        "refunded_amount": float(refunded_amount),
        "chargeback_amount": float(chargeback_amount),
        "refund_event_count": refund_event_count,
        "chargeback_event_count": chargeback_event_count,
    }


PENDING_STATUSES = ["pending", "processing"]


def get_users(db: Session, skip: int = 0, limit: int = 10):
    return db.query(User).order_by(User.id.asc()).offset(skip).limit(limit).all()


def create_user(db: Session, email: str):
    db_user = User(email=email)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def _apply_admin_user_filters(q, is_active: Optional[bool] = None, email_query: Optional[str] = None, search: Optional[str] = None):
    search_term = (search or email_query or "").strip()
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    if search_term:
        q = q.filter(User.email.ilike(f"%{search_term}%"))
    return q


def _build_admin_user_summary(db: Session, user: User):
    issued_credits = db.query(func.coalesce(func.sum(CreditPack.credits), 0)).filter(CreditPack.user_id == user.id).scalar() or 0
    purchased_credit_packs = db.query(func.count(CreditPack.id)).filter(CreditPack.user_id == user.id).scalar() or 0
    total_spend = db.query(func.coalesce(func.sum(CreditPack.price), 0.0)).filter(CreditPack.user_id == user.id).scalar() or 0.0
    generation_row = (
        db.query(
            func.count(Generation.id).label("total_generations"),
            func.sum(case((Generation.status == "completed", 1), else_=0)).label("completed_generations"),
            func.sum(case((Generation.status == "failed", 1), else_=0)).label("failed_generations"),
            func.sum(case((Generation.status.in_(PENDING_STATUSES), 1), else_=0)).label("pending_generations"),
            func.coalesce(func.sum(Generation.credits_used), 0).label("consumed_credits"),
            func.max(Generation.created_at).label("last_generation_at"),
        )
        .filter(Generation.user_id == user.id)
        .first()
    )
    total_credits = int(issued_credits or 0)
    consumed_credits = int((generation_row.consumed_credits if generation_row else 0) or 0)
    return {
        "id": user.id,
        "email": user.email,
        "phone": None,
        "signup_method": "email",
        "is_active": user.is_active,
        "status": "active" if user.is_active else "suspended",
        "created_at": user.created_at,
        "total_credits": total_credits,
        "remaining_credits": total_credits - consumed_credits,
        "purchased_credit_packs": int(purchased_credit_packs or 0),
        "total_spend": float(total_spend or 0.0),
        "total_generations": int((generation_row.total_generations if generation_row else 0) or 0),
        "completed_generations": int((generation_row.completed_generations if generation_row else 0) or 0),
        "failed_generations": int((generation_row.failed_generations if generation_row else 0) or 0),
        "pending_generations": int((generation_row.pending_generations if generation_row else 0) or 0),
        "last_generation_at": generation_row.last_generation_at if generation_row else None,
    }


def get_admin_users(
    db: Session,
    skip: int = 0,
    limit: int = 10,
    is_active: Optional[bool] = None,
    email_query: Optional[str] = None,
    search: Optional[str] = None,
):
    q = _apply_admin_user_filters(db.query(User), is_active=is_active, email_query=email_query, search=search)
    users = q.order_by(User.id.asc()).offset(skip).limit(limit).all()
    return [_build_admin_user_summary(db, user) for user in users]


def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()


def get_admin_user_detail(db: Session, user_id: int):
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    recent_generations = get_generation_jobs_report(db, user_id=user_id, limit=10)
    manual_credit_actions = [
        {
            "id": row.id,
            "credits": row.credits,
            "reason": "manual_credit",
            "note": row.pack_name,
            "created_at": row.purchased_at,
        }
        for row in db.query(CreditPack)
        .filter(CreditPack.user_id == user_id, CreditPack.price == 0)
        .order_by(CreditPack.purchased_at.desc(), CreditPack.id.desc())
        .all()
    ]
    return {
        **_build_admin_user_summary(db, user),
        "recent_generations": recent_generations,
        "manual_credit_actions": manual_credit_actions,
    }


def set_admin_user_active_state(db: Session, user_id: int, is_active: bool):
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    user.is_active = is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_admin_manual_credit_action(db: Session, user_id: int, credits: int, reason: Optional[str] = None, note: Optional[str] = None):
    label_parts = ["manual_credit"]
    if reason:
        label_parts.append(reason.strip())
    if note:
        label_parts.append(note.strip())
    pack_name = " | ".join([part for part in label_parts if part])
    return create_credit_pack(db, user_id=user_id, pack_name=pack_name, credits=credits, price=0.0)


def get_admin_user_count(
    db: Session,
    is_active: Optional[bool] = None,
    email_query: Optional[str] = None,
    search: Optional[str] = None,
):
    q = _apply_admin_user_filters(db.query(func.count(User.id)), is_active=is_active, email_query=email_query, search=search)
    return q.scalar() or 0


def get_user_state_summary(db: Session):
    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    inactive_users = total_users - active_users
    users_with_generations = (
        db.query(func.count(func.distinct(Generation.user_id)))
        .filter(Generation.user_id.isnot(None))
        .scalar()
        or 0
    )
    users_with_credit_packs = (
        db.query(func.count(func.distinct(CreditPack.user_id)))
        .filter(CreditPack.user_id.isnot(None))
        .scalar()
        or 0
    )
    return {
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "users_with_generations": users_with_generations,
        "users_with_credit_packs": users_with_credit_packs,
    }


def get_templates(db: Session, skip: int = 0, limit: int = 10, include_inactive: bool = False):
    q = db.query(Template)
    if not include_inactive:
        q = q.filter(Template.is_active.is_(True))
    return q.order_by(Template.id.asc()).offset(skip).limit(limit).all()


def get_template(db: Session, template_id: int, include_inactive: bool = True):
    q = db.query(Template).filter(Template.id == template_id)
    if not include_inactive:
        q = q.filter(Template.is_active.is_(True))
    return q.first()


def _map_comfyui_server_status(is_active: bool, healthcheck_status: Optional[str]) -> str:
    if not is_active:
        return "Disabled"

    normalized = (healthcheck_status or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"", "unknown"}:
        return "Offline"
    if normalized in {"online", "healthy", "ok", "pass", "passing", "connected", "available", "ready", "success"}:
        return "Online"
    if normalized in {"offline", "unreachable", "down", "timeout", "timed_out", "disconnected"}:
        return "Offline"
    if normalized in {"disabled", "inactive"}:
        return "Disabled"
    if normalized in {"testing", "checking", "pending", "running", "in_progress"}:
        return "Testing"
    if normalized in {"connection_error", "error", "failed", "failure", "invalid_auth", "unauthorized", "misconfigured"}:
        return "Connection Error"
    return "Connection Error"


def _serialize_comfyui_server(server: ComfyUIServer):
    return {
        "id": server.id,
        "name": server.name,
        "base_url": server.base_url,
        "auth_token": server.auth_token,
        "notes": server.notes,
        "is_active": server.is_active,
        "healthcheck_status": server.healthcheck_status,
        "healthcheck_message": server.healthcheck_message,
        "last_checked_at": server.last_checked_at,
        "status": _map_comfyui_server_status(server.is_active, server.healthcheck_status),
        "created_at": server.created_at,
        "updated_at": server.updated_at,
    }


def get_comfyui_servers(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    include_inactive: bool = True,
    status: Optional[str] = None,
):
    q = db.query(ComfyUIServer)
    if not include_inactive:
        q = q.filter(ComfyUIServer.is_active.is_(True))

    rows = q.order_by(ComfyUIServer.id.asc()).offset(skip).limit(limit).all()
    serialized = [_serialize_comfyui_server(row) for row in rows]
    if status:
        desired = status.strip().lower()
        serialized = [row for row in serialized if row["status"].lower() == desired]
    return serialized


def get_comfyui_server(db: Session, server_id: int):
    server = db.query(ComfyUIServer).filter(ComfyUIServer.id == server_id).first()
    return _serialize_comfyui_server(server) if server else None


def create_comfyui_server(
    db: Session,
    name: str,
    base_url: str,
    auth_token: Optional[str] = None,
    notes: Optional[str] = None,
    is_active: bool = True,
    healthcheck_status: Optional[str] = None,
    healthcheck_message: Optional[str] = None,
    last_checked_at: Optional[datetime] = None,
):
    server = ComfyUIServer(
        name=name,
        base_url=base_url,
        auth_token=auth_token,
        notes=notes,
        is_active=is_active,
        healthcheck_status=healthcheck_status,
        healthcheck_message=healthcheck_message,
        last_checked_at=last_checked_at,
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    return _serialize_comfyui_server(server)


def update_comfyui_server(db: Session, server_id: int, payload: ComfyUIServerUpdate):
    server = db.query(ComfyUIServer).filter(ComfyUIServer.id == server_id).first()
    if not server:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(server, field, value)
    db.add(server)
    db.commit()
    db.refresh(server)
    return _serialize_comfyui_server(server)


def delete_comfyui_server(db: Session, server_id: int):
    server = db.query(ComfyUIServer).filter(ComfyUIServer.id == server_id).first()
    if not server:
        return False
    db.delete(server)
    db.commit()
    return True


def create_template(
    db: Session,
    name: str,
    description: str = None,
    category: str = None,
    is_spicy: bool = False,
    preview_image_file_id: int = None,
    credit_cost: int = 0,
    disclaimer_text: str = None,
    best_use_text: str = None,
    generation_type: str = None,
    comfyui_server_id: str = None,
    workflow_key: str = None,
    input_node_mapping: str = None,
    output_node_mapping: str = None,
    primary_color: str = None,
    secondary_color: str = None,
    accent_color: str = None,
    background_color: str = None,
    card_color: str = None,
    text_color: str = None,
):
    db_template = Template(
        name=name,
        description=description,
        category=category,
        is_spicy=is_spicy,
        preview_image_file_id=preview_image_file_id,
        credit_cost=credit_cost,
        disclaimer_text=disclaimer_text,
        best_use_text=best_use_text,
        generation_type=generation_type,
        comfyui_server_id=comfyui_server_id,
        workflow_key=workflow_key,
        input_node_mapping=input_node_mapping,
        output_node_mapping=output_node_mapping,
        primary_color=primary_color,
        secondary_color=secondary_color,
        accent_color=accent_color,
        background_color=background_color,
        card_color=card_color,
        text_color=text_color,
    )
    db.add(db_template)
    db.commit()
    db.refresh(db_template)
    return db_template


def update_template(db: Session, template_id: int, payload: TemplateUpdate):
    template = get_template(db, template_id)
    if not template:
        return None
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(template, field, value)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def deactivate_template(db: Session, template_id: int):
    template = get_template(db, template_id)
    if not template:
        return False
    template.is_active = False
    db.add(template)
    db.commit()
    return True


def get_files(db: Session, owner_user_id: int = None, kind: str = None, skip: int = 0, limit: int = 50):
    q = db.query(FileAsset)
    if owner_user_id is not None:
        q = q.filter(FileAsset.owner_user_id == owner_user_id)
    if kind is not None:
        q = q.filter(FileAsset.kind == kind)
    return q.order_by(FileAsset.id.asc()).offset(skip).limit(limit).all()


def get_file(db: Session, file_id: int):
    return db.query(FileAsset).filter(FileAsset.id == file_id).first()


def create_file(
    db: Session,
    *,
    owner_user_id: Optional[int],
    kind: str,
    relative_path: str,
    original_filename: Optional[str] = None,
    mime_type: Optional[str] = None,
    size_bytes: int = 0,
    checksum: Optional[str] = None,
    storage_driver: str = "local_private_disk",
):
    db_file = FileAsset(
        owner_user_id=owner_user_id,
        kind=kind,
        storage_driver=storage_driver,
        relative_path=relative_path,
        original_filename=sanitize_filename(original_filename) if original_filename else None,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file


def get_generations(db: Session, user_id: int = None, status: str = None, skip: int = 0, limit: int = 10):
    q = db.query(Generation)
    if user_id is not None:
        q = q.filter(Generation.user_id == user_id)
    if status is not None:
        q = q.filter(Generation.status == status)
    return q.order_by(Generation.id.asc()).offset(skip).limit(limit).all()


def get_generation(db: Session, generation_id: int):
    return db.query(Generation).filter(Generation.id == generation_id).first()


def get_generation_for_user(db: Session, generation_id: int, user_id: int):
    return db.query(Generation).filter(Generation.id == generation_id, Generation.user_id == user_id).first()


def create_generation(
    db: Session,
    user_id: int,
    template_id: int,
    input_path: str,
    output_path: str = None,
    input_file_id: int = None,
    output_file_id: int = None,
    comfyui_job_id: str = None,
    comfyui_server_id: str = None,
    workflow_key: str = None,
    result_kind: str = None,
    status: str = "pending",
    error_code: str = None,
    error_message: str = None,
    credits_used: int = 0,
    queued_at: Optional[datetime] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
    failed_at: Optional[datetime] = None,
):
    if input_file_id and not input_path:
        input_file = get_file(db, input_file_id)
        if input_file:
            input_path = input_file.relative_path
    if output_file_id and not output_path:
        output_file = get_file(db, output_file_id)
        if output_file:
            output_path = output_file.relative_path

    db_gen = Generation(
        user_id=user_id,
        template_id=template_id,
        input_path=input_path,
        output_path=output_path,
        input_file_id=input_file_id,
        output_file_id=output_file_id,
        comfyui_job_id=comfyui_job_id,
        comfyui_server_id=comfyui_server_id,
        workflow_key=workflow_key,
        result_kind=result_kind,
        status=status,
        error_code=error_code,
        error_message=error_message,
        credits_used=credits_used,
        queued_at=queued_at,
        started_at=started_at,
        completed_at=completed_at,
        failed_at=failed_at,
    )
    db.add(db_gen)
    db.commit()
    db.refresh(db_gen)
    return db_gen


def update_generation_status(db: Session, generation_id: int, payload: GenerationStatusUpdate):
    generation = get_generation(db, generation_id)
    if not generation:
        return None

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(generation, field, value)

    if generation.status == "completed" and generation.completed_at is None:
        generation.completed_at = datetime.utcnow()
    if generation.status == "failed" and generation.failed_at is None:
        generation.failed_at = datetime.utcnow()
    if generation.status == "queued" and generation.queued_at is None:
        generation.queued_at = datetime.utcnow()
    if generation.status == "running" and generation.started_at is None:
        generation.started_at = datetime.utcnow()

    db.add(generation)
    db.commit()
    db.refresh(generation)
    return generation


def attach_generation_result(db: Session, generation_id: int, payload: GenerationResultCreate):
    generation = get_generation(db, generation_id)
    if not generation:
        return None

    content_base64 = payload.content_base64
    source_path = payload.source_path
    if not content_base64 and not source_path:
        raise ValueError("Either source_path or content_base64 is required")

    if content_base64:
        content = decode_base64_content(content_base64)
        relative_path, checksum, size_bytes = store_job_result_bytes(
            generation.user_id,
            generation.id,
            payload.filename,
            content,
            payload.mime_type,
        )
    else:
        relative_path, checksum, size_bytes = copy_source_into_job(
            generation.user_id,
            generation.id,
            source_path,
            "output",
            payload.filename,
        )

    file_record = create_file(
        db,
        owner_user_id=generation.user_id,
        kind="generation_output",
        relative_path=relative_path,
        original_filename=payload.filename,
        mime_type=payload.mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
    )

    generation.output_file_id = file_record.id
    generation.output_path = file_record.relative_path
    generation.status = "completed"
    generation.completed_at = datetime.utcnow()
    generation.failed_at = None
    generation.error_code = None
    generation.error_message = None

    if payload.comfyui_job_id is not None:
        generation.comfyui_job_id = payload.comfyui_job_id
    if payload.comfyui_server_id is not None:
        generation.comfyui_server_id = payload.comfyui_server_id
    if payload.workflow_key is not None:
        generation.workflow_key = payload.workflow_key
    if payload.result_kind is not None:
        generation.result_kind = payload.result_kind

    db.add(generation)
    db.commit()
    db.refresh(generation)
    return generation


def get_generation_jobs_report(
    db: Session,
    user_id: int = None,
    template_id: int = None,
    status: str = None,
    skip: int = 0,
    limit: int = 50,
):
    q = (
        db.query(
            Generation.id.label("id"),
            Generation.user_id.label("user_id"),
            User.email.label("user_email"),
            Generation.template_id.label("template_id"),
            Template.name.label("template_name"),
            Generation.input_path.label("input_path"),
            Generation.output_path.label("output_path"),
            Generation.input_file_id.label("input_file_id"),
            Generation.output_file_id.label("output_file_id"),
            Generation.comfyui_job_id.label("comfyui_job_id"),
            Generation.comfyui_server_id.label("comfyui_server_id"),
            Generation.workflow_key.label("workflow_key"),
            Generation.result_kind.label("result_kind"),
            Generation.status.label("status"),
            Generation.error_code.label("error_code"),
            Generation.error_message.label("error_message"),
            Generation.credits_used.label("credits_used"),
            Generation.created_at.label("created_at"),
            Generation.queued_at.label("queued_at"),
            Generation.started_at.label("started_at"),
            Generation.completed_at.label("completed_at"),
            Generation.failed_at.label("failed_at"),
        )
        .join(User, User.id == Generation.user_id)
        .join(Template, Template.id == Generation.template_id)
        .order_by(Generation.created_at.desc(), Generation.id.desc())
    )
    if user_id is not None:
        q = q.filter(Generation.user_id == user_id)
    if template_id is not None:
        q = q.filter(Generation.template_id == template_id)
    if status is not None:
        q = q.filter(Generation.status == status)
    return q.offset(skip).limit(limit).all()


def get_generation_stats_by_user(db: Session, template_id: int = None):
    q = (
        db.query(
            User.id.label("user_id"),
            User.email.label("user_email"),
            func.count(Generation.id).label("total_jobs"),
            func.sum(case((Generation.status.in_(PENDING_STATUSES), 1), else_=0)).label("pending_jobs"),
            func.sum(case((Generation.status == "completed", 1), else_=0)).label("completed_jobs"),
            func.sum(case((Generation.status == "failed", 1), else_=0)).label("failed_jobs"),
            func.max(Generation.created_at).label("last_job_at"),
        )
        .join(Generation, Generation.user_id == User.id)
        .group_by(User.id, User.email)
        .order_by(func.count(Generation.id).desc(), User.id.asc())
    )
    if template_id is not None:
        q = q.filter(Generation.template_id == template_id)
    return q.all()


def get_generation_status_breakdown(db: Session, template_id: int = None):
    q = (
        db.query(
            Generation.status.label("status"),
            func.count(Generation.id).label("total_jobs"),
        )
        .group_by(Generation.status)
        .order_by(func.count(Generation.id).desc(), Generation.status.asc())
    )
    if template_id is not None:
        q = q.filter(Generation.template_id == template_id)
    return q.all()


def get_credit_packs(db: Session, user_id: int = None, skip: int = 0, limit: int = 10):
    q = db.query(CreditPack)
    if user_id is not None:
        q = q.filter(CreditPack.user_id == user_id)
    return q.order_by(CreditPack.id.asc()).offset(skip).limit(limit).all()


def create_credit_pack(db: Session, user_id: int, pack_name: str, credits: int, price: float):
    db_pack = CreditPack(user_id=user_id, pack_name=pack_name, credits=credits, price=price)
    db.add(db_pack)
    db.commit()
    db.refresh(db_pack)
    return db_pack


def resolve_credit_pack_config_for_store_product(db: Session, product_id: str, platform: Optional[str] = None):
    _ensure_credit_pack_configs(db)
    normalized_product = (product_id or "").strip()
    normalized_platform = (platform or "").strip().lower()
    for row in list_credit_pack_configs(db, include_inactive=False):
        candidates = [row.product_key]
        if normalized_platform == "ios":
            candidates.append(row.store_product_key_ios)
        elif normalized_platform == "android":
            candidates.append(row.store_product_key_android)
        else:
            candidates.extend([row.store_product_key_ios, row.store_product_key_android])
        if normalized_product in {candidate for candidate in candidates if candidate}:
            return row
    return None


def grant_credits_post_verification(
    db: Session,
    *,
    user_id: int,
    product_id: str,
    platform: Optional[str] = None,
    transaction_id: Optional[str] = None,
    provider: str = "RevenueCat",
):
    if transaction_id:
        existing = db.query(CreditPack).filter(CreditPack.external_transaction_id == transaction_id).first()
        if existing:
            return existing, False

    config = resolve_credit_pack_config_for_store_product(db, product_id=product_id, platform=platform)
    if not config:
        raise ValueError(f"No active credit pack config matched product_id '{product_id}'")

    db_pack = CreditPack(
        user_id=user_id,
        pack_name=f"{config.credit_amount} credits",
        credits=config.credit_amount,
        price=config.price,
        provider=provider,
        product_key=product_id,
        external_transaction_id=transaction_id,
    )
    db.add(db_pack)
    db.commit()
    db.refresh(db_pack)
    return db_pack, True


def list_credit_pack_configs(db: Session, include_inactive: bool = True):
    _ensure_credit_pack_configs(db)
    q = db.query(CreditPackConfig)
    if not include_inactive:
        q = q.filter(CreditPackConfig.active.is_(True))
    return q.order_by(CreditPackConfig.slot_number.asc()).all()


def create_credit_pack_config(db: Session, **payload):
    _ensure_credit_pack_configs(db)
    slot_number = payload["slot_number"]
    current = db.query(func.count(CreditPackConfig.id)).scalar() or 0
    existing = _get_credit_pack_config_by_slot(db, slot_number)
    if existing:
        raise ValueError(f"Slot {slot_number} already exists")
    if current >= 5:
        raise ValueError("Exactly five credit pack slots are supported")
    row = CreditPackConfig(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_credit_pack_config(db: Session, slot_number: int, payload):
    _ensure_credit_pack_configs(db)
    row = _get_credit_pack_config_by_slot(db, slot_number)
    if not row:
        return None
    data = payload.model_dump(exclude_unset=True)
    target_slot = data.get("slot_number")
    if target_slot is not None and target_slot != slot_number:
        if _get_credit_pack_config_by_slot(db, target_slot):
            raise ValueError(f"Slot {target_slot} already exists")
    for field, value in data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def delete_credit_pack_config(db: Session, slot_number: int):
    _ensure_credit_pack_configs(db)
    row = _get_credit_pack_config_by_slot(db, slot_number)
    if not row:
        return None
    row.credit_amount = next(item["credit_amount"] for item in DEFAULT_CREDIT_PACK_CONFIGS if item["slot_number"] == slot_number)
    row.price = next(item["price"] for item in DEFAULT_CREDIT_PACK_CONFIGS if item["slot_number"] == slot_number)
    row.display_price_text = next(item["display_price_text"] for item in DEFAULT_CREDIT_PACK_CONFIGS if item["slot_number"] == slot_number)
    row.product_key = next(item["product_key"] for item in DEFAULT_CREDIT_PACK_CONFIGS if item["slot_number"] == slot_number)
    row.store_product_key_android = None
    row.store_product_key_ios = None
    row.active = False
    db.commit()
    db.refresh(row)
    return row


def get_template_usage_report(db: Session, include_inactive: bool = True):
    rows = (
        db.query(
            Template.id.label("template_id"),
            Template.name.label("template_name"),
            Template.category.label("category"),
            Template.is_active.label("is_active"),
            func.count(Generation.id).label("generation_count"),
            func.sum(case((Generation.status == "completed", 1), else_=0)).label("completed_count"),
            func.sum(case((Generation.status.in_(PENDING_STATUSES), 1), else_=0)).label("pending_count"),
            func.sum(case((Generation.status == "failed", 1), else_=0)).label("failed_count"),
            func.max(Generation.created_at).label("last_used_at"),
        )
        .outerjoin(Generation, Generation.template_id == Template.id)
        .group_by(Template.id, Template.name, Template.category, Template.is_active)
        .order_by(Template.id.asc())
    )
    if not include_inactive:
        rows = rows.filter(Template.is_active.is_(True))

    templates = [
        {
            "template_id": row.template_id,
            "template_name": row.template_name,
            "category": row.category,
            "is_active": row.is_active,
            "generation_count": row.generation_count or 0,
            "completed_count": row.completed_count or 0,
            "pending_count": row.pending_count or 0,
            "failed_count": row.failed_count or 0,
            "last_used_at": row.last_used_at,
        }
        for row in rows.all()
    ]
    return {
        "total_templates": len(templates),
        "active_templates": sum(1 for row in templates if row["is_active"]),
        "inactive_templates": sum(1 for row in templates if not row["is_active"]),
        "total_generations": sum(row["generation_count"] for row in templates),
        "templates": templates,
    }


def get_credit_stats_report(
    db: Session,
    user_id: Optional[int] = None,
    credits_per_generation: int = 1,
):
    user_rows = db.query(User.id, User.email).order_by(User.id.asc())
    if user_id is not None:
        user_rows = user_rows.filter(User.id == user_id)

    users = []
    for row in user_rows.all():
        reversal_totals = _get_revenuecat_reversal_totals(db, user_id=row.id)
        issued_credits = (
            db.query(func.coalesce(func.sum(CreditPack.credits), 0))
            .filter(CreditPack.user_id == row.id)
            .scalar()
            or 0
        )
        purchased_credit_packs = db.query(func.count(CreditPack.id)).filter(CreditPack.user_id == row.id).scalar() or 0
        purchased_amount = (
            db.query(func.coalesce(func.sum(CreditPack.price), 0.0))
            .filter(CreditPack.user_id == row.id)
            .scalar()
            or 0.0
        )
        generation_count = db.query(func.count(Generation.id)).filter(Generation.user_id == row.id).scalar() or 0
        completed_generation_count = (
            db.query(func.count(Generation.id))
            .filter(Generation.user_id == row.id, Generation.status == "completed")
            .scalar()
            or 0
        )
        failed_generation_count = (
            db.query(func.count(Generation.id))
            .filter(Generation.user_id == row.id, Generation.status == "failed")
            .scalar()
            or 0
        )
        pending_generation_count = (
            db.query(func.count(Generation.id))
            .filter(Generation.user_id == row.id, Generation.status.in_(["pending", "processing", "uploaded", "queued", "running"]))
            .scalar()
            or 0
        )
        stored_consumption = (
            db.query(func.coalesce(func.sum(Generation.credits_used), 0))
            .filter(Generation.user_id == row.id)
            .scalar()
            or 0
        )
        consumed_credits = stored_consumption if stored_consumption > 0 else generation_count * credits_per_generation
        net_issued_credits = issued_credits - reversal_totals["refunded_credits"] - reversal_totals["chargeback_credits"]
        net_purchase_amount = float(purchased_amount) - reversal_totals["refunded_amount"] - reversal_totals["chargeback_amount"]
        users.append(
            {
                "user_id": row.id,
                "user_email": row.email,
                "issued_credits": issued_credits,
                "refunded_credits": reversal_totals["refunded_credits"],
                "chargeback_credits": reversal_totals["chargeback_credits"],
                "purchased_credit_packs": purchased_credit_packs,
                "purchased_amount": float(purchased_amount),
                "refunded_amount": reversal_totals["refunded_amount"],
                "chargeback_amount": reversal_totals["chargeback_amount"],
                "net_issued_credits": net_issued_credits,
                "net_purchase_amount": net_purchase_amount,
                "refund_event_count": reversal_totals["refund_event_count"],
                "chargeback_event_count": reversal_totals["chargeback_event_count"],
                "generation_count": generation_count,
                "completed_generation_count": completed_generation_count,
                "failed_generation_count": failed_generation_count,
                "pending_generation_count": pending_generation_count,
                "consumed_credits": consumed_credits,
                "remaining_credits": net_issued_credits - consumed_credits,
            }
        )

    return {
        "credits_per_generation": credits_per_generation,
        "total_users": len(users),
        "issued_credits": sum(user["issued_credits"] for user in users),
        "refunded_credits": sum(user["refunded_credits"] for user in users),
        "chargeback_credits": sum(user["chargeback_credits"] for user in users),
        "net_issued_credits": sum(user["net_issued_credits"] for user in users),
        "purchased_credit_packs": sum(user["purchased_credit_packs"] for user in users),
        "purchased_amount": sum(user["purchased_amount"] for user in users),
        "refunded_amount": sum(user["refunded_amount"] for user in users),
        "chargeback_amount": sum(user["chargeback_amount"] for user in users),
        "net_purchase_amount": sum(user["net_purchase_amount"] for user in users),
        "refund_event_count": sum(user["refund_event_count"] for user in users),
        "chargeback_event_count": sum(user["chargeback_event_count"] for user in users),
        "generation_count": sum(user["generation_count"] for user in users),
        "completed_generation_count": sum(user["completed_generation_count"] for user in users),
        "failed_generation_count": sum(user["failed_generation_count"] for user in users),
        "pending_generation_count": sum(user["pending_generation_count"] for user in users),
        "consumed_credits": sum(user["consumed_credits"] for user in users),
        "remaining_credits": sum(user["remaining_credits"] for user in users),
        "users": users,
    }


def get_site_usage_summary(db: Session):
    user_summary = get_user_state_summary(db)
    status_rows = get_generation_status_breakdown(db)
    jobs_by_status = {row.status: row.total_jobs for row in status_rows}
    credits_spent = db.query(func.coalesce(func.sum(Generation.credits_used), 0)).scalar() or 0
    credits_earned = db.query(func.coalesce(func.sum(CreditPack.credits), 0)).scalar() or 0
    reversal_totals = _get_revenuecat_reversal_totals(db)
    return {
        **user_summary,
        "total_jobs": sum(jobs_by_status.values()),
        "jobs_by_status": jobs_by_status,
        "credits_spent": credits_spent,
        "credits_earned": credits_earned,
        "credits_refunded": reversal_totals["refunded_credits"],
        "credits_refunded_chargebacks": reversal_totals["chargeback_credits"],
        "credits_balance": credits_earned - reversal_totals["refunded_credits"] - reversal_totals["chargeback_credits"] - credits_spent,
    }


def get_user_dashboard_credits(db: Session, user_id: int):
    reversal_totals = _get_revenuecat_reversal_totals(db, user_id=user_id)
    issued_credits = (
        db.query(func.coalesce(func.sum(CreditPack.credits), 0)).filter(CreditPack.user_id == user_id).scalar() or 0
    )
    purchased_credit_packs = db.query(func.count(CreditPack.id)).filter(CreditPack.user_id == user_id).scalar() or 0
    purchased_amount = (
        db.query(func.coalesce(func.sum(CreditPack.price), 0.0)).filter(CreditPack.user_id == user_id).scalar() or 0.0
    )
    consumed_credits = (
        db.query(func.coalesce(func.sum(Generation.credits_used), 0)).filter(Generation.user_id == user_id).scalar() or 0
    )
    return {
        "issued_credits": issued_credits - reversal_totals["refunded_credits"] - reversal_totals["chargeback_credits"],
        "purchased_credit_packs": purchased_credit_packs,
        "purchased_amount": float(purchased_amount) - reversal_totals["refunded_amount"] - reversal_totals["chargeback_amount"],
        "consumed_credits": consumed_credits,
        "remaining_credits": issued_credits - reversal_totals["refunded_credits"] - reversal_totals["chargeback_credits"] - consumed_credits,
    }


def get_user_dashboard_job_summary(db: Session, user_id: int):
    row = (
        db.query(
            func.count(Generation.id).label("total_jobs"),
            func.sum(case((Generation.status.in_(PENDING_STATUSES), 1), else_=0)).label("pending_jobs"),
            func.sum(case((Generation.status == "completed", 1), else_=0)).label("completed_jobs"),
            func.sum(case((Generation.status == "failed", 1), else_=0)).label("failed_jobs"),
            func.max(Generation.created_at).label("last_job_at"),
        )
        .filter(Generation.user_id == user_id)
        .first()
    )
    return {
        "total_jobs": row.total_jobs or 0,
        "pending_jobs": row.pending_jobs or 0,
        "completed_jobs": row.completed_jobs or 0,
        "failed_jobs": row.failed_jobs or 0,
        "last_job_at": row.last_job_at,
    }


def get_user_dashboard_templates(db: Session, user_id: int, include_inactive: bool = False):
    q = (
        db.query(
            Template.id.label("template_id"),
            Template.name.label("template_name"),
            Template.category.label("category"),
            Template.is_active.label("is_active"),
            func.count(Generation.id).label("generation_count"),
            func.max(Generation.created_at).label("last_used_at"),
        )
        .outerjoin(
            Generation,
            (Generation.template_id == Template.id) & (Generation.user_id == user_id),
        )
        .group_by(Template.id, Template.name, Template.category, Template.is_active)
        .order_by(Template.id.asc())
    )
    if not include_inactive:
        q = q.filter(Template.is_active.is_(True))
    return [
        {
            "template_id": row.template_id,
            "template_name": row.template_name,
            "category": row.category,
            "is_active": row.is_active,
            "generation_count": row.generation_count or 0,
            "last_used_at": row.last_used_at,
        }
        for row in q.all()
    ]


def get_user_dashboard_overview(db: Session, user_id: int):
    user = get_user_by_id(db, user_id)
    if not user:
        return None
    recent_generations = get_generation_jobs_report(db, user_id=user_id, limit=5)
    return {
        "user": user,
        "credits": get_user_dashboard_credits(db, user_id),
        "jobs": get_user_dashboard_job_summary(db, user_id),
        "recent_generations": recent_generations,
        "templates": get_user_dashboard_templates(db, user_id),
    }
