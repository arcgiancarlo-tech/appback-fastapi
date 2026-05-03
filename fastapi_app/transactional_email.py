import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field


router = APIRouter(prefix="/internal/transactional-email", tags=["internal", "transactional-email"])


class TransactionalEmailSecurityError(RuntimeError):
    pass


@dataclass
class TransactionalEmailSettings:
    shared_secret: str
    provider: str
    provider_api_key: Optional[str]
    from_email: str
    app_base_url: str
    invite_base_url: str
    stub_mode: bool


class TransactionalEmailRecipient(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    locale: Optional[str] = "en"


class ResetEmailRequest(TransactionalEmailRecipient):
    reset_token: str = Field(..., min_length=12)
    reset_path: str = "/reset-password"
    expires_in_minutes: int = Field(60, ge=1, le=1440)


class InviteEmailRequest(TransactionalEmailRecipient):
    invite_token: str = Field(..., min_length=12)
    invited_by_email: Optional[EmailStr] = None
    invite_path: str = "/accept-invite"
    expires_in_days: int = Field(7, ge=1, le=30)


class NotifyEmailRequest(TransactionalEmailRecipient):
    subject: str = Field(..., min_length=1, max_length=200)
    message_text: str = Field(..., min_length=1, max_length=5000)
    notification_type: Literal["generic", "generation_complete", "generation_failed", "admin_notice"] = "generic"
    action_url: Optional[str] = None
    action_label: Optional[str] = Field(None, max_length=80)


class TransactionalEmailResponse(BaseModel):
    accepted: bool
    mode: Literal["stub", "live_configured"]
    provider: str
    template: Literal["password_reset", "invite", "notify"]
    to_email: EmailStr
    from_email: EmailStr
    subject: str
    preview_text: str
    delivery_stubbed: bool
    request_fingerprint: str
    generated_links: dict[str, str]
    missing_credentials: list[str]


class TransactionalEmailHealthResponse(BaseModel):
    ok: bool
    mode: Literal["stub", "live_configured"]
    provider: str
    missing_credentials: list[str]



def _load_settings() -> TransactionalEmailSettings:
    shared_secret = os.getenv("TRANSACTIONAL_EMAIL_SHARED_SECRET", "")
    if not shared_secret:
        raise TransactionalEmailSecurityError("TRANSACTIONAL_EMAIL_SHARED_SECRET is required")

    provider = os.getenv("TRANSACTIONAL_EMAIL_PROVIDER", "stub").strip().lower() or "stub"
    provider_api_key = os.getenv("TRANSACTIONAL_EMAIL_PROVIDER_API_KEY")
    from_email = os.getenv("TRANSACTIONAL_EMAIL_FROM_EMAIL", "noreply@example.com")
    app_base_url = os.getenv("APP_BASE_URL", "https://example.com").rstrip("/")
    invite_base_url = os.getenv("INVITE_BASE_URL", app_base_url).rstrip("/")
    stub_mode = os.getenv("TRANSACTIONAL_EMAIL_STUB_MODE", "true").strip().lower() not in {"0", "false", "no"}

    return TransactionalEmailSettings(
        shared_secret=shared_secret,
        provider=provider,
        provider_api_key=provider_api_key,
        from_email=from_email,
        app_base_url=app_base_url,
        invite_base_url=invite_base_url,
        stub_mode=stub_mode,
    )



def _require_shared_secret(x_transactional_email_secret: Optional[str]) -> TransactionalEmailSettings:
    settings = _load_settings()
    provided = x_transactional_email_secret or ""
    if not hmac.compare_digest(provided, settings.shared_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid transactional email secret")
    return settings



def _missing_credentials(settings: TransactionalEmailSettings) -> list[str]:
    missing = []
    if settings.provider != "stub" and not settings.provider_api_key:
        missing.append("TRANSACTIONAL_EMAIL_PROVIDER_API_KEY")
    if not settings.from_email:
        missing.append("TRANSACTIONAL_EMAIL_FROM_EMAIL")
    return missing



def _mode(settings: TransactionalEmailSettings) -> Literal["stub", "live_configured"]:
    return "stub" if settings.stub_mode or settings.provider == "stub" else "live_configured"



def _fingerprint(parts: list[str]) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]



def _join_url(base_url: str, path: str, params: dict[str, str]) -> str:
    cleaned_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url}{cleaned_path}?{urlencode(params)}"


@router.get("/health", response_model=TransactionalEmailHealthResponse)
def transactional_email_health(x_transactional_email_secret: Optional[str] = Header(None)):
    settings = _require_shared_secret(x_transactional_email_secret)
    missing = _missing_credentials(settings)
    return TransactionalEmailHealthResponse(
        ok=len(missing) == 0 or _mode(settings) == "stub",
        mode=_mode(settings),
        provider=settings.provider,
        missing_credentials=missing,
    )


@router.post("/reset", response_model=TransactionalEmailResponse, status_code=status.HTTP_202_ACCEPTED)
def transactional_email_reset(payload: ResetEmailRequest, x_transactional_email_secret: Optional[str] = Header(None)):
    settings = _require_shared_secret(x_transactional_email_secret)
    reset_link = _join_url(
        settings.app_base_url,
        payload.reset_path,
        {"token": payload.reset_token, "email": payload.email},
    )
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=payload.expires_in_minutes)
    preview = f"Reset your password using the secure link. Expires at {expires_at.isoformat()}."
    return TransactionalEmailResponse(
        accepted=True,
        mode=_mode(settings),
        provider=settings.provider,
        template="password_reset",
        to_email=payload.email,
        from_email=settings.from_email,
        subject="Reset your password",
        preview_text=preview,
        delivery_stubbed=_mode(settings) == "stub",
        request_fingerprint=_fingerprint(["reset", payload.email, payload.reset_token]),
        generated_links={"reset_link": reset_link},
        missing_credentials=_missing_credentials(settings),
    )


@router.post("/invite", response_model=TransactionalEmailResponse, status_code=status.HTTP_202_ACCEPTED)
def transactional_email_invite(payload: InviteEmailRequest, x_transactional_email_secret: Optional[str] = Header(None)):
    settings = _require_shared_secret(x_transactional_email_secret)
    invite_link = _join_url(
        settings.invite_base_url,
        payload.invite_path,
        {"token": payload.invite_token, "email": payload.email},
    )
    preview = "You have been invited to join the workspace. Use the secure invite link before it expires."
    if payload.invited_by_email:
        preview = f"{preview} Invited by {payload.invited_by_email}."
    return TransactionalEmailResponse(
        accepted=True,
        mode=_mode(settings),
        provider=settings.provider,
        template="invite",
        to_email=payload.email,
        from_email=settings.from_email,
        subject="You're invited",
        preview_text=preview,
        delivery_stubbed=_mode(settings) == "stub",
        request_fingerprint=_fingerprint(["invite", payload.email, payload.invite_token]),
        generated_links={"invite_link": invite_link},
        missing_credentials=_missing_credentials(settings),
    )


@router.post("/notify", response_model=TransactionalEmailResponse, status_code=status.HTTP_202_ACCEPTED)
def transactional_email_notify(payload: NotifyEmailRequest, x_transactional_email_secret: Optional[str] = Header(None)):
    settings = _require_shared_secret(x_transactional_email_secret)
    generated_links = {}
    if payload.action_url:
        generated_links["action_url"] = payload.action_url
    preview = payload.message_text[:160]
    return TransactionalEmailResponse(
        accepted=True,
        mode=_mode(settings),
        provider=settings.provider,
        template="notify",
        to_email=payload.email,
        from_email=settings.from_email,
        subject=payload.subject,
        preview_text=preview,
        delivery_stubbed=_mode(settings) == "stub",
        request_fingerprint=_fingerprint(["notify", payload.email, payload.subject, payload.notification_type]),
        generated_links=generated_links,
        missing_credentials=_missing_credentials(settings),
    )
