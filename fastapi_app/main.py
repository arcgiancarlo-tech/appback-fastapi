import os
import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.cors import CORSMiddleware

from .crud import (
    attach_generation_result,
    create_admin_manual_credit_action,
    create_category,
    create_comfyui_server,
    create_credit_pack,
    grant_credits_post_verification,
    create_credit_pack_config,
    create_file,
    create_generation,
    create_revenuecat_refund_event,
    create_template,
    create_template_page_display_config,
    create_user,
    deactivate_template,
    delete_comfyui_server,
    delete_category,
    delete_template_page_display_config,
    get_billing_integration_config,
    get_admin_user_count,
    get_admin_user_detail,
    get_admin_users,
    get_comfyui_server,
    get_comfyui_servers,
    get_credit_packs,
    get_theme_settings,
    list_credit_pack_configs,
    resolve_credit_pack_config_for_store_product,
    list_categories,
    get_credit_stats_report,
    get_file,
    get_files,
    get_generation,
    get_generation_for_user,
    get_generation_jobs_report,
    get_generation_stats_by_user,
    get_generation_status_breakdown,
    get_generations,
    get_revenuecat_refund_report,
    get_site_usage_summary,
    get_template,
    get_template_page_display_config,
    get_template_usage_report,
    get_templates,
    get_user_by_id,
    get_user_dashboard_credits,
    get_user_dashboard_job_summary,
    get_user_dashboard_overview,
    get_user_dashboard_templates,
    get_user_state_summary,
    get_users,
    list_template_page_display_configs,
    set_admin_user_active_state,
    delete_credit_pack_config,
    update_category,
    update_billing_integration_config,
    update_comfyui_server,
    update_credit_pack_config,
    update_generation_status,
    update_template_page_display_config,
    update_theme_settings,
    update_template,
)
from .db import Base, engine, get_db
from .models import Generation, User
from .observability import (
    AppMetrics,
    InMemoryRateLimiter,
    ObservabilityMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    db_ready,
    http_exception_handler,
    metrics_response,
    setup_logging,
    unhandled_exception_handler,
)
from .schemas import (
    AdminUserCount,
    AdminUserCreditActionCreate,
    AdminUserCreditActionOut,
    AdminUserDetailOut,
    AdminUserListItemOut,
    AdminUserModerationAction,
    AdminUserStateSummary,
    AdminUserStatusOut,
    BillingIntegrationConfigOut,
    BillingIntegrationConfigUpdate,
    CategoryCreate,
    CategoryOut,
    CategoryUpdate,
    ComfyJobStatusResponse,
    ComfyCallbackTokenRequest,
    ComfyCallbackTokenResponse,
    ComfyPromptSubmissionRequest,
    ComfyPromptSubmissionResponse,
    ComfyResultCallbackRequest,
    ComfyResultCallbackResponse,
    ComfyUIServerCreate,
    ComfyUIServerOut,
    ComfyUIServerUpdate,
    CreditPackCreate,
    CreditPackConfigCreate,
    CreditPackConfigOut,
    CreditPackConfigUpdate,
    CreditPackOut,
    CreditPurchaseVerifyIn,
    CreditPurchaseVerifyOut,
    CreditStatsReportOut,
    FileAssetCreate,
    FileAssetOut,
    GenerationCreate,
    GenerationOut,
    GenerationReportOut,
    GenerationResultCreate,
    GenerationStatusBreakdownOut,
    GenerationStatusUpdate,
    RevenueCatRefundSummaryOut,
    RevenueCatWebhookIn,
    RevenueCatWebhookResultOut,
    SignedFileUrlOut,
    SiteUsageSummaryOut,
    TemplateCreate,
    TemplateOut,
    TemplatePageDisplayConfigCreate,
    TemplatePageDisplayConfigOut,
    TemplatePageDisplayConfigUpdate,
    TemplatePreviewUploadCreate,
    TemplateUpdate,
    ThemeSettingsOut,
    ThemeSettingsUpdate,
    TemplateUsageReportOut,
    UploadCreate,
    UploadSessionCreate,
    UploadSessionOut,
    UserCreate,
    UserCreditsSummaryOut,
    UserDashboardOverviewOut,
    UserGenerationStatsOut,
    UserJobSummaryOut,
    UserOut,
    UserTemplateSummaryItemOut,
)
from .revenuecat import RevenueCatError, verify_purchase
from .storage import (
    MAX_SINGLE_UPLOAD_BYTES,
    PUBLIC_ASSET_PATH,
    allocate_upload_path,
    build_internal_signed_url,
    build_signed_url_payload,
    decode_base64_content,
    ensure_storage_root,
    get_download_media_type,
    get_managed_file_path,
    get_public_asset_url_path,
    sanitize_filename,
    store_upload_bytes,
    verify_signed_token,
)

logger = setup_logging()
metrics = AppMetrics()
rate_limiter = InMemoryRateLimiter(
    limit=int(os.getenv("RATE_LIMIT_REQUESTS", "120")),
    window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
)

app = FastAPI(
    title="SpinAI Studio Admin API",
    description="Admin and reporting endpoints for users, templates, files, generations, and credit activity.",
)

ensure_storage_root()
app.mount(PUBLIC_ASSET_PATH, StaticFiles(directory=str(ensure_storage_root()), check_dir=False), name="public-assets")

allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms", "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ObservabilityMiddleware, logger=logger, metrics=metrics)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, metrics=metrics, logger=logger)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

Base.metadata.create_all(bind=engine)

REVENUECAT_WEBHOOK_SECRET = os.getenv("REVENUECAT_WEBHOOK_SECRET", "")
COMFYUI_CALLBACK_SECRET = os.getenv("COMFYUI_CALLBACK_SECRET", "")
COMFYUI_CALLBACK_CLIENT_ID = os.getenv("COMFYUI_CALLBACK_CLIENT_ID", "")
COMFYUI_CALLBACK_CLIENT_SECRET = os.getenv("COMFYUI_CALLBACK_CLIENT_SECRET", "")
COMFYUI_CALLBACK_TOKEN_TTL_SECONDS = int(os.getenv("COMFYUI_CALLBACK_TOKEN_TTL_SECONDS", "900"))
COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET = os.getenv("COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET", COMFYUI_CALLBACK_SECRET)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _issue_comfyui_callback_token(client_id: str) -> str:
    if not COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET:
        raise HTTPException(status_code=503, detail="ComfyUI callback token signing secret is not configured")

    now = int(time.time())
    payload = {
        "sub": client_id,
        "iat": now,
        "exp": now + COMFYUI_CALLBACK_TOKEN_TTL_SECONDS,
    }
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def _verify_comfyui_callback_credentials(
    authorization: Optional[str],
    x_comfyui_secret: Optional[str],
):
    if not any([
        COMFYUI_CALLBACK_SECRET,
        COMFYUI_CALLBACK_CLIENT_ID and COMFYUI_CALLBACK_CLIENT_SECRET and COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET,
    ]):
        return

    bearer_value = authorization.removeprefix("Bearer ").strip() if authorization else None

    if COMFYUI_CALLBACK_SECRET:
        presented_secret = bearer_value or x_comfyui_secret
        if presented_secret and hmac.compare_digest(presented_secret, COMFYUI_CALLBACK_SECRET):
            return

    if bearer_value and COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET:
        try:
            encoded_payload, signature = bearer_value.split(".", 1)
            expected_signature = hmac.new(
                COMFYUI_CALLBACK_TOKEN_SIGNING_SECRET.encode("utf-8"),
                encoded_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("invalid signature")
            payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
            if int(payload.get("exp", 0)) < int(time.time()):
                raise ValueError("token expired")
        except (ValueError, json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=401, detail="Invalid ComfyUI callback credentials")
        return

    raise HTTPException(status_code=401, detail="Missing ComfyUI callback credentials")


def _ensure_file_access(file_asset, owner_user_id: Optional[int] = None):
    if not file_asset or file_asset.deleted_at is not None:
        raise HTTPException(status_code=404, detail="File not found")
    if owner_user_id is not None and file_asset.owner_user_id not in (None, owner_user_id):
        raise HTTPException(status_code=404, detail="File not found")
    return file_asset


def _build_signed_path_url(request: Request, route_name: str, file_asset, action: str, expires_in_seconds: Optional[int] = None, extra: Optional[dict] = None):
    payload = build_signed_url_payload(
        action=action,
        file_id=file_asset.id,
        relative_path=file_asset.relative_path,
        ttl_seconds=expires_in_seconds,
        extra=extra,
    )
    token_stub = "TOKEN_PLACEHOLDER"
    base_url = str(request.url_for(route_name, token=token_stub)).replace(token_stub, "").rstrip("/")
    url, expires_at = build_internal_signed_url(base_url, payload)
    return {
        "file_id": file_asset.id,
        "url": url,
        "expires_at": expires_at,
        "method": "PUT" if action == "upload" else "GET",
    }


def _build_public_asset_url(request: Request, file_asset):
    return str(request.base_url).rstrip("/") + get_public_asset_url_path(file_asset.relative_path)


@app.get("/users/", response_model=List[UserOut], tags=["users"])
def list_users(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return get_users(db, skip=skip, limit=limit)


@app.post("/users/", response_model=UserOut, status_code=status.HTTP_201_CREATED, tags=["users"])
def add_user(user: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    return create_user(db, email=user.email)


@app.get("/admin/users/", response_model=List[AdminUserListItemOut], tags=["admin", "users"])
def admin_list_users(
    skip: int = 0,
    limit: int = 50,
    is_active: Optional[bool] = Query(None, description="Filter users by active state."),
    email_query: Optional[str] = Query(None, description="Case-insensitive partial match against email."),
    search: Optional[str] = Query(None, description="Alias for email_query, used by the admin UsersPage search box."),
    db: Session = Depends(get_db),
):
    return get_admin_users(db, skip=skip, limit=limit, is_active=is_active, email_query=email_query, search=search)


@app.get("/admin/users/count", response_model=AdminUserCount, tags=["admin", "users", "reports"])
def admin_user_count(
    is_active: Optional[bool] = Query(None, description="Filter counted users by active state."),
    email_query: Optional[str] = Query(None, description="Case-insensitive partial match against email."),
    search: Optional[str] = Query(None, description="Alias for email_query, used by the admin UsersPage search box."),
    db: Session = Depends(get_db),
):
    return {"count": get_admin_user_count(db, is_active=is_active, email_query=email_query, search=search)}


@app.get("/admin/users/state-summary", response_model=AdminUserStateSummary, tags=["admin", "users", "reports"])
def admin_user_state_summary(db: Session = Depends(get_db)):
    return get_user_state_summary(db)


@app.get("/admin/users/{user_id}", response_model=AdminUserDetailOut, tags=["admin", "users"])
def admin_get_user(user_id: int, db: Session = Depends(get_db)):
    user = get_admin_user_detail(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/admin/users/{user_id}/suspend", response_model=AdminUserStatusOut, tags=["admin", "users"])
def admin_suspend_user(user_id: int, payload: Optional[AdminUserModerationAction] = None, db: Session = Depends(get_db)):
    user = set_admin_user_active_state(db, user_id, is_active=False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "status": "suspended",
        "reason": payload.reason if payload else None,
    }


@app.post("/admin/users/{user_id}/reactivate", response_model=AdminUserStatusOut, tags=["admin", "users"])
def admin_reactivate_user(user_id: int, payload: Optional[AdminUserModerationAction] = None, db: Session = Depends(get_db)):
    user = set_admin_user_active_state(db, user_id, is_active=True)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user.id,
        "email": user.email,
        "is_active": user.is_active,
        "status": "active",
        "reason": payload.reason if payload else None,
    }


@app.post("/admin/users/{user_id}/credit-actions", response_model=AdminUserCreditActionOut, status_code=status.HTTP_201_CREATED, tags=["admin", "users", "credits"])
def admin_create_credit_action(user_id: int, payload: AdminUserCreditActionCreate, db: Session = Depends(get_db)):
    if not get_user_by_id(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    action = create_admin_manual_credit_action(db, user_id=user_id, credits=payload.credits, reason=payload.reason, note=payload.note)
    return {
        "id": action.id,
        "credits": action.credits,
        "reason": payload.reason or "manual_credit",
        "note": payload.note or action.pack_name,
        "created_at": action.purchased_at,
    }


@app.get("/templates/", response_model=List[TemplateOut], tags=["templates"])
def list_templates(skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return get_templates(db, skip=skip, limit=limit)


@app.get("/templates/page-display-configs", response_model=List[TemplatePageDisplayConfigOut], tags=["templates", "categories"])
def public_list_template_page_display_configs(
    page_type: str = Query(..., description="Page type to load, for example templates or spicy_templates."),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    try:
        return list_template_page_display_configs(db, page_type=page_type, skip=skip, limit=limit, public_only=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/templates/{template_id}", response_model=TemplateOut, tags=["templates"])
def public_get_template(template_id: int, db: Session = Depends(get_db)):
    template = get_template(db, template_id, include_inactive=False)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@app.post("/templates/", response_model=TemplateOut, status_code=status.HTTP_201_CREATED, tags=["templates"])
def add_template(template: TemplateCreate, db: Session = Depends(get_db)):
    return create_template(
        db,
        name=template.name,
        description=template.description,
        category=template.category,
        is_spicy=template.is_spicy,
        preview_image_file_id=template.preview_image_file_id,
        credit_cost=template.credit_cost,
        disclaimer_text=template.disclaimer_text,
        best_use_text=template.best_use_text,
        generation_type=template.generation_type,
        comfyui_server_id=template.comfyui_server_id,
        workflow_key=template.workflow_key,
        input_node_mapping=template.input_node_mapping,
        output_node_mapping=template.output_node_mapping,
        primary_color=template.primary_color,
        secondary_color=template.secondary_color,
        accent_color=template.accent_color,
        background_color=template.background_color,
        card_color=template.card_color,
        text_color=template.text_color,
    )


@app.get("/files/", response_model=List[FileAssetOut], tags=["files"])
def list_files(
    owner_user_id: Optional[int] = None,
    kind: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return get_files(db, owner_user_id=owner_user_id, kind=kind, skip=skip, limit=limit)


@app.post("/files/", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED, tags=["files"])
def add_file(file: FileAssetCreate, db: Session = Depends(get_db)):
    return create_file(
        db,
        owner_user_id=file.owner_user_id,
        kind=file.kind,
        storage_driver=file.storage_driver,
        relative_path=file.relative_path,
        original_filename=file.original_filename,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        checksum=file.checksum,
    )


@app.get("/files/{file_id}", response_model=FileAssetOut, tags=["files"])
def get_file_detail(file_id: int, db: Session = Depends(get_db)):
    file_asset = get_file(db, file_id)
    if not file_asset:
        raise HTTPException(status_code=404, detail="File not found")
    return file_asset


@app.post("/files/upload-sessions", response_model=UploadSessionOut, status_code=status.HTTP_201_CREATED, tags=["files", "uploads"])
def create_upload_session(payload: UploadSessionCreate, request: Request, db: Session = Depends(get_db)):
    relative_path, safe_name = allocate_upload_path(payload.owner_user_id, payload.filename, payload.mime_type, payload.kind)
    file_asset = create_file(
        db,
        owner_user_id=payload.owner_user_id,
        kind=payload.kind,
        relative_path=relative_path,
        original_filename=safe_name,
        mime_type=payload.mime_type,
        size_bytes=0,
        checksum=None,
    )
    return {
        "file": file_asset,
        "upload": _build_signed_path_url(
            request,
            "upload_managed_file",
            file_asset,
            "upload",
            expires_in_seconds=payload.expires_in_seconds,
            extra={"filename": safe_name, "max_bytes": min(payload.max_bytes or MAX_SINGLE_UPLOAD_BYTES, MAX_SINGLE_UPLOAD_BYTES)},
        ),
    }


@app.get("/files/{file_id}/download-url", response_model=SignedFileUrlOut, tags=["files"])
def get_file_download_url(
    file_id: int,
    request: Request,
    user_id: Optional[int] = Query(None, description="Optional ownership filter for app-style reads."),
    expires_in_seconds: Optional[int] = Query(None, ge=1, le=86400),
    db: Session = Depends(get_db),
):
    file_asset = _ensure_file_access(get_file(db, file_id), user_id)
    return _build_signed_path_url(
        request,
        "download_managed_file",
        file_asset,
        "download",
        expires_in_seconds=expires_in_seconds,
        extra={"filename": file_asset.original_filename or sanitize_filename(file_asset.relative_path), "disposition": "attachment"},
    )


@app.get("/files/{file_id}/public-url", tags=["files"])
def get_file_public_url(
    file_id: int,
    request: Request,
    user_id: Optional[int] = Query(None, description="Optional ownership filter for app-style reads."),
    db: Session = Depends(get_db),
):
    file_asset = _ensure_file_access(get_file(db, file_id), user_id)
    return {"file_id": file_asset.id, "url": _build_public_asset_url(request, file_asset)}


@app.post("/uploads/", response_model=FileAssetOut, status_code=status.HTTP_201_CREATED, tags=["files", "uploads"])
def add_upload(payload: UploadCreate, db: Session = Depends(get_db)):
    content = decode_base64_content(payload.content_base64)
    relative_path, checksum, size_bytes = store_upload_bytes(payload.user_id, payload.filename, content)
    return create_file(
        db,
        owner_user_id=payload.user_id,
        kind="user_input",
        relative_path=relative_path,
        original_filename=payload.filename,
        mime_type=payload.mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
    )


@app.put("/storage/upload/{token}", status_code=status.HTTP_201_CREATED, name="upload_managed_file", tags=["files", "uploads"])
async def upload_managed_file(token: str, request: Request, db: Session = Depends(get_db)):
    try:
        payload = verify_signed_token(token, expected_action="upload")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    file_asset = _ensure_file_access(get_file(db, int(payload["file_id"])))
    if file_asset.relative_path != payload.get("path"):
        raise HTTPException(status_code=403, detail="Token path mismatch")

    max_bytes = int(payload.get("max_bytes") or MAX_SINGLE_UPLOAD_BYTES)
    full_path = get_managed_file_path(file_asset.relative_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with full_path.open("wb") as handle:
            async for chunk in request.stream():
                if not chunk:
                    continue
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    handle.close()
                    full_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Upload exceeds allowed size")
                digest.update(chunk)
                handle.write(chunk)
    except HTTPException:
        raise

    checksum = digest.hexdigest()
    file_asset.size_bytes = size_bytes
    file_asset.checksum = checksum
    if not file_asset.mime_type:
        file_asset.mime_type = request.headers.get("content-type")
    db.add(file_asset)
    db.commit()
    db.refresh(file_asset)
    return {"file_id": file_asset.id, "relative_path": file_asset.relative_path, "size_bytes": size_bytes, "checksum": checksum, "stored": True}


@app.get("/storage/download/{token}", name="download_managed_file", tags=["files"])
def download_managed_file(token: str, db: Session = Depends(get_db)):
    try:
        payload = verify_signed_token(token, expected_action="download")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    file_asset = _ensure_file_access(get_file(db, int(payload["file_id"])))
    if file_asset.relative_path != payload.get("path"):
        raise HTTPException(status_code=403, detail="Token path mismatch")

    full_path = get_managed_file_path(file_asset.relative_path)
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Stored file not found")

    filename = sanitize_filename(payload.get("filename") or file_asset.original_filename or full_path.name)
    return FileResponse(path=full_path, media_type=get_download_media_type(filename, file_asset.mime_type), filename=filename)


@app.get("/generations/", response_model=List[GenerationOut], tags=["generations"])
def list_generations(
    user_id: int = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    return get_generations(db, user_id=user_id, status=status_filter, skip=skip, limit=limit)


@app.post("/generations/", response_model=GenerationOut, status_code=status.HTTP_201_CREATED, tags=["generations"])
def add_generation(gen: GenerationCreate, db: Session = Depends(get_db)):
    return create_generation(
        db,
        user_id=gen.user_id,
        template_id=gen.template_id,
        input_path=gen.input_path,
        output_path=gen.output_path,
        input_file_id=gen.input_file_id,
        output_file_id=gen.output_file_id,
        comfyui_job_id=gen.comfyui_job_id,
        comfyui_server_id=gen.comfyui_server_id,
        workflow_key=gen.workflow_key,
        result_kind=gen.result_kind,
        status=gen.status,
        error_code=gen.error_code,
        error_message=gen.error_message,
        completed_at=gen.completed_at,
        failed_at=gen.failed_at,
        queued_at=gen.queued_at,
        started_at=gen.started_at,
        credits_used=gen.credits_used,
    )


@app.get("/generations/{generation_id}", response_model=GenerationOut, tags=["generations"])
def generation_detail(
    generation_id: int,
    user_id: Optional[int] = Query(None, description="Optional ownership filter for app-style reads."),
    db: Session = Depends(get_db),
):
    generation = get_generation_for_user(db, generation_id, user_id) if user_id is not None else get_generation(db, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


@app.get("/generations/{generation_id}/result-url", response_model=SignedFileUrlOut, tags=["generations", "files"])
def generation_result_download_url(
    generation_id: int,
    request: Request,
    user_id: Optional[int] = Query(None, description="Optional ownership filter for app-style reads."),
    expires_in_seconds: Optional[int] = Query(None, ge=1, le=86400),
    db: Session = Depends(get_db),
):
    generation = get_generation_for_user(db, generation_id, user_id) if user_id is not None else get_generation(db, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    if not generation.output_file_id:
        raise HTTPException(status_code=409, detail="Generation result is not available yet")
    file_asset = _ensure_file_access(get_file(db, generation.output_file_id), user_id)
    return _build_signed_path_url(
        request,
        "download_managed_file",
        file_asset,
        "download",
        expires_in_seconds=expires_in_seconds,
        extra={"filename": file_asset.original_filename or sanitize_filename(file_asset.relative_path), "disposition": "attachment"},
    )


@app.get("/generations/{generation_id}/result-public-url", tags=["generations", "files"])
def generation_result_public_url(
    generation_id: int,
    request: Request,
    user_id: Optional[int] = Query(None, description="Optional ownership filter for app-style reads."),
    db: Session = Depends(get_db),
):
    generation = get_generation_for_user(db, generation_id, user_id) if user_id is not None else get_generation(db, generation_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    if not generation.output_file_id:
        raise HTTPException(status_code=409, detail="Generation result is not available yet")
    file_asset = _ensure_file_access(get_file(db, generation.output_file_id), user_id)
    return {"generation_id": generation.id, "file_id": file_asset.id, "url": _build_public_asset_url(request, file_asset)}


@app.post("/generations/{generation_id}/status", response_model=GenerationOut, tags=["generations"])
def update_generation(
    generation_id: int,
    payload: GenerationStatusUpdate,
    authorization: Optional[str] = Header(None),
    x_comfyui_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    _verify_comfyui_callback_credentials(authorization, x_comfyui_secret)
    generation = update_generation_status(db, generation_id, payload)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


@app.post("/generations/{generation_id}/result", response_model=GenerationOut, tags=["generations"])
def attach_result(
    generation_id: int,
    payload: GenerationResultCreate,
    authorization: Optional[str] = Header(None),
    x_comfyui_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    _verify_comfyui_callback_credentials(authorization, x_comfyui_secret)
    try:
        generation = attach_generation_result(db, generation_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


def _get_generation_by_prompt_id(db: Session, prompt_id: str):
    return db.query(Generation).filter(Generation.comfyui_job_id == prompt_id).first()


@app.post("/comfyui/prompt", response_model=ComfyPromptSubmissionResponse, status_code=status.HTTP_201_CREATED, tags=["comfyui", "generations"])
def submit_comfyui_prompt(
    payload: ComfyPromptSubmissionRequest,
    authorization: Optional[str] = Header(None),
    x_comfyui_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    _verify_comfyui_callback_credentials(authorization, x_comfyui_secret)
    prompt_id = payload.prompt_id or f"prompt-{uuid4()}"
    generation = create_generation(
        db,
        user_id=payload.user_id,
        template_id=payload.template_id,
        input_path=payload.input_path,
        input_file_id=payload.input_file_id,
        comfyui_job_id=prompt_id,
        comfyui_server_id=payload.comfyui_server_id,
        workflow_key=payload.workflow_key,
        result_kind=payload.result_kind,
        status=payload.status,
        credits_used=payload.credits_used,
    )
    return {
        "prompt_id": prompt_id,
        "generation_id": generation.id,
        "number": generation.id,
        "node_errors": {},
        "status": generation.status,
    }


@app.get("/comfyui/history/{prompt_id}", response_model=ComfyJobStatusResponse, tags=["comfyui", "generations"])
def comfyui_prompt_status(prompt_id: str, db: Session = Depends(get_db)):
    generation = _get_generation_by_prompt_id(db, prompt_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")
    return {
        "prompt_id": prompt_id,
        "generation_id": generation.id,
        "status": generation.status,
        "completed": generation.status == "completed",
        "failed": generation.status == "failed",
        "output_file_id": generation.output_file_id,
        "output_path": generation.output_path,
        "error_code": generation.error_code,
        "error_message": generation.error_message,
        "generation": generation,
    }


@app.post("/comfyui/history/{prompt_id}/result", response_model=ComfyResultCallbackResponse, tags=["comfyui", "generations"])
def comfyui_result_callback(
    prompt_id: str,
    payload: ComfyResultCallbackRequest,
    authorization: Optional[str] = Header(None),
    x_comfyui_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    _verify_comfyui_callback_credentials(authorization, x_comfyui_secret)
    generation = _get_generation_by_prompt_id(db, prompt_id)
    if not generation:
        raise HTTPException(status_code=404, detail="Generation not found")

    if payload.status == "failed":
        updated = update_generation_status(
            db,
            generation.id,
            GenerationStatusUpdate(
                status="failed",
                comfyui_job_id=prompt_id,
                comfyui_server_id=payload.comfyui_server_id,
                workflow_key=payload.workflow_key,
                result_kind=payload.result_kind,
                error_code=payload.error_code,
                error_message=payload.error_message,
            ),
        )
        return {
            "prompt_id": prompt_id,
            "generation_id": updated.id,
            "status": updated.status,
            "result_received": False,
            "output_file_id": updated.output_file_id,
            "output_path": updated.output_path,
            "error_code": updated.error_code,
            "error_message": updated.error_message,
        }

    if not payload.filename:
        raise HTTPException(status_code=422, detail="filename is required for completed result callbacks")

    try:
        updated = attach_generation_result(
            db,
            generation.id,
            GenerationResultCreate(
                filename=payload.filename,
                mime_type=payload.mime_type,
                content_base64=payload.content_base64,
                source_path=payload.source_path,
                comfyui_job_id=prompt_id,
                comfyui_server_id=payload.comfyui_server_id,
                workflow_key=payload.workflow_key,
                result_kind=payload.result_kind,
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "prompt_id": prompt_id,
        "generation_id": updated.id,
        "status": updated.status,
        "result_received": True,
        "output_file_id": updated.output_file_id,
        "output_path": updated.output_path,
        "error_code": updated.error_code,
        "error_message": updated.error_message,
    }


@app.post("/comfyui/auth/token", response_model=ComfyCallbackTokenResponse, tags=["comfyui", "auth"])
def issue_comfyui_callback_token(payload: ComfyCallbackTokenRequest):
    if not COMFYUI_CALLBACK_CLIENT_ID or not COMFYUI_CALLBACK_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="ComfyUI callback client credentials are not configured")
    if payload.client_id != COMFYUI_CALLBACK_CLIENT_ID or not hmac.compare_digest(payload.client_secret, COMFYUI_CALLBACK_CLIENT_SECRET):
        raise HTTPException(status_code=401, detail="Invalid ComfyUI callback client credentials")
    return {
        "access_token": _issue_comfyui_callback_token(payload.client_id),
        "token_type": "Bearer",
        "expires_in": COMFYUI_CALLBACK_TOKEN_TTL_SECONDS,
    }


@app.get("/credit_packs/", response_model=List[CreditPackOut], tags=["credits"])
def list_credit_packs(user_id: int = None, skip: int = 0, limit: int = 10, db: Session = Depends(get_db)):
    return get_credit_packs(db, user_id=user_id, skip=skip, limit=limit)


@app.post("/credit_packs/", response_model=CreditPackOut, status_code=status.HTTP_201_CREATED, tags=["credits"])
def add_credit_pack(pack: CreditPackCreate, db: Session = Depends(get_db)):
    return create_credit_pack(
        db,
        user_id=pack.user_id,
        pack_name=pack.pack_name,
        credits=pack.credits,
        price=pack.price,
    )


@app.get("/credits/packs", response_model=List[CreditPackConfigOut], tags=["credits"])
def list_store_credit_pack_configs(include_inactive: bool = Query(True), db: Session = Depends(get_db)):
    return list_credit_pack_configs(db, include_inactive=include_inactive)


@app.post("/credits/purchase/verify", response_model=CreditPurchaseVerifyOut, tags=["credits", "revenuecat"])
def verify_credit_purchase(payload: CreditPurchaseVerifyIn, db: Session = Depends(get_db)):
    user = get_user_by_id(db, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    normalized_platform = payload.platform.strip().lower()
    if normalized_platform not in {"ios", "android", "web"}:
        raise HTTPException(status_code=422, detail="platform must be one of ios, android, or web")

    pack_config = resolve_credit_pack_config_for_store_product(db, payload.product_id, normalized_platform)
    if not pack_config:
        raise HTTPException(status_code=422, detail=f"No active credit pack config matched product_id '{payload.product_id}'")

    revenuecat_app_user_id = payload.app_user_id or str(payload.user_id)
    try:
        verification = verify_purchase(payload.receipt_data, revenuecat_app_user_id)
    except RevenueCatError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    customer_info = verification.get("customer_info") or {}
    non_subscriptions = customer_info.get("non_subscriptions") or {}
    matching_transactions = non_subscriptions.get(payload.product_id) or []
    latest_transaction = matching_transactions[-1] if matching_transactions else {}
    transaction_id = (
        latest_transaction.get("transaction_id")
        or latest_transaction.get("id")
        or verification.get("transaction_id")
    )

    granted_pack, created = grant_credits_post_verification(
        db,
        user_id=payload.user_id,
        product_id=payload.product_id,
        platform=normalized_platform,
        transaction_id=transaction_id,
        provider="RevenueCat",
    )
    credit_summary = get_user_dashboard_credits(db, payload.user_id)
    return {
        "status": "credited" if created else "duplicate",
        "credited": created,
        "pack_id": granted_pack.id,
        "pack_name": granted_pack.pack_name,
        "credits_granted": granted_pack.credits,
        "remaining_credits": credit_summary["remaining_credits"],
        "transaction_id": granted_pack.external_transaction_id,
        "provider": "RevenueCat",
    }


@app.get("/admin/credit-pack-configs", response_model=List[CreditPackConfigOut], tags=["admin", "credits"])
def admin_list_credit_pack_configs(include_inactive: bool = Query(True), db: Session = Depends(get_db)):
    return list_credit_pack_configs(db, include_inactive=include_inactive)


@app.post("/admin/credit-pack-configs", response_model=CreditPackConfigOut, status_code=status.HTTP_201_CREATED, tags=["admin", "credits"])
def admin_create_credit_pack_config(payload: CreditPackConfigCreate, db: Session = Depends(get_db)):
    try:
        return create_credit_pack_config(db, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/admin/credit-pack-configs/{slot_number}", response_model=CreditPackConfigOut, tags=["admin", "credits"])
def admin_patch_credit_pack_config(slot_number: int, payload: CreditPackConfigUpdate, db: Session = Depends(get_db)):
    try:
        updated = update_credit_pack_config(db, slot_number, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Credit pack config not found")
    return updated


@app.delete("/admin/credit-pack-configs/{slot_number}", response_model=CreditPackConfigOut, tags=["admin", "credits"])
def admin_delete_credit_pack_config(slot_number: int, db: Session = Depends(get_db)):
    deleted = delete_credit_pack_config(db, slot_number)
    if not deleted:
        raise HTTPException(status_code=404, detail="Credit pack config not found")
    return deleted


@app.get("/admin/billing-integration", response_model=BillingIntegrationConfigOut, tags=["admin", "billing"])
def admin_get_billing_integration_config(db: Session = Depends(get_db)):
    return get_billing_integration_config(db)


@app.put("/admin/billing-integration", response_model=BillingIntegrationConfigOut, tags=["admin", "billing"])
def admin_put_billing_integration_config(payload: BillingIntegrationConfigUpdate, db: Session = Depends(get_db)):
    return update_billing_integration_config(db, payload)


@app.get("/admin/categories", response_model=List[CategoryOut], tags=["admin", "categories"])
def admin_list_categories(include_inactive: bool = Query(True), db: Session = Depends(get_db)):
    return list_categories(db, include_inactive=include_inactive)


@app.post("/admin/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED, tags=["admin", "categories"])
def admin_create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    try:
        return create_category(db, name=payload.name, is_active=payload.is_active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/categories/{category_id}", response_model=CategoryOut, tags=["admin", "categories"])
def admin_update_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db)):
    try:
        category = update_category(db, category_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@app.delete("/admin/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin", "categories"])
def admin_delete_category(category_id: int, db: Session = Depends(get_db)):
    category = delete_category(db, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/admin/theme-settings", response_model=ThemeSettingsOut, tags=["admin", "theme"])
def admin_get_theme_settings(db: Session = Depends(get_db)):
    return get_theme_settings(db)


@app.put("/admin/theme-settings", response_model=ThemeSettingsOut, tags=["admin", "theme"])
def admin_put_theme_settings(payload: ThemeSettingsUpdate, db: Session = Depends(get_db)):
    return update_theme_settings(db, payload)


@app.get("/admin/template-page-display-configs", response_model=List[TemplatePageDisplayConfigOut], tags=["admin", "categories", "templates"])
def admin_list_template_page_display_configs(
    page_type: Optional[str] = Query(None, description="Optional page type filter: templates or spicy_templates."),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    try:
        return list_template_page_display_configs(db, page_type=page_type, skip=skip, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/template-page-display-configs/{config_id}", response_model=TemplatePageDisplayConfigOut, tags=["admin", "categories", "templates"])
def admin_get_template_page_display_config(config_id: int, db: Session = Depends(get_db)):
    row = get_template_page_display_config(db, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Template page display config not found")
    return row


@app.post("/admin/template-page-display-configs", response_model=TemplatePageDisplayConfigOut, status_code=status.HTTP_201_CREATED, tags=["admin", "categories", "templates"])
def admin_create_template_page_display_config(payload: TemplatePageDisplayConfigCreate, db: Session = Depends(get_db)):
    try:
        return create_template_page_display_config(db, page_type=payload.page_type, category_id=payload.category_id, order=payload.order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/admin/template-page-display-configs/{config_id}", response_model=TemplatePageDisplayConfigOut, tags=["admin", "categories", "templates"])
def admin_update_template_page_display_config(config_id: int, payload: TemplatePageDisplayConfigUpdate, db: Session = Depends(get_db)):
    try:
        row = update_template_page_display_config(db, config_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Template page display config not found")
    return row


@app.delete("/admin/template-page-display-configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin", "categories", "templates"])
def admin_delete_template_page_display_config(config_id: int, db: Session = Depends(get_db)):
    deleted = delete_template_page_display_config(db, config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template page display config not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/admin/templates/", response_model=List[TemplateOut], tags=["admin"])
def admin_list_templates(
    include_inactive: bool = Query(True, description="Include inactive templates in admin listings."),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return get_templates(db, skip=skip, limit=limit, include_inactive=include_inactive)


@app.get("/admin/comfyui/servers", response_model=List[ComfyUIServerOut], tags=["admin", "comfyui"])
def admin_list_comfyui_servers(
    include_inactive: bool = Query(True, description="Include disabled servers in admin listings."),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter derived server status values like Online or Disabled."),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return get_comfyui_servers(db, skip=skip, limit=limit, include_inactive=include_inactive, status=status_filter)


@app.get("/admin/comfyui/servers/{server_id}", response_model=ComfyUIServerOut, tags=["admin", "comfyui"])
def admin_get_comfyui_server(server_id: int, db: Session = Depends(get_db)):
    server = get_comfyui_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="ComfyUI server not found")
    return server


@app.post("/admin/comfyui/servers", response_model=ComfyUIServerOut, status_code=status.HTTP_201_CREATED, tags=["admin", "comfyui"])
def admin_create_comfyui_server(payload: ComfyUIServerCreate, db: Session = Depends(get_db)):
    return create_comfyui_server(
        db,
        name=payload.name,
        base_url=payload.base_url,
        auth_token=payload.auth_token,
        notes=payload.notes,
        is_active=payload.is_active,
        healthcheck_status=payload.healthcheck_status,
        healthcheck_message=payload.healthcheck_message,
        last_checked_at=payload.last_checked_at,
    )


@app.put("/admin/comfyui/servers/{server_id}", response_model=ComfyUIServerOut, tags=["admin", "comfyui"])
def admin_update_comfyui_server(server_id: int, payload: ComfyUIServerUpdate, db: Session = Depends(get_db)):
    server = update_comfyui_server(db, server_id, payload)
    if not server:
        raise HTTPException(status_code=404, detail="ComfyUI server not found")
    return server


@app.delete("/admin/comfyui/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin", "comfyui"])
def admin_delete_comfyui_server(server_id: int, db: Session = Depends(get_db)):
    deleted = delete_comfyui_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="ComfyUI server not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/admin/templates/{template_id}", response_model=TemplateOut, tags=["admin"])
def admin_get_template(template_id: int, db: Session = Depends(get_db)):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@app.post("/admin/templates/", response_model=TemplateOut, status_code=status.HTTP_201_CREATED, tags=["admin"])
def admin_create_template(template: TemplateCreate, db: Session = Depends(get_db)):
    return create_template(
        db,
        name=template.name,
        description=template.description,
        category=template.category,
        is_spicy=template.is_spicy,
        preview_image_file_id=template.preview_image_file_id,
        credit_cost=template.credit_cost,
        disclaimer_text=template.disclaimer_text,
        best_use_text=template.best_use_text,
        generation_type=template.generation_type,
        comfyui_server_id=template.comfyui_server_id,
        workflow_key=template.workflow_key,
        input_node_mapping=template.input_node_mapping,
        output_node_mapping=template.output_node_mapping,
        primary_color=template.primary_color,
        secondary_color=template.secondary_color,
        accent_color=template.accent_color,
        background_color=template.background_color,
        card_color=template.card_color,
        text_color=template.text_color,
    )


@app.post("/admin/templates/{template_id}/preview-upload-session", response_model=UploadSessionOut, status_code=status.HTTP_201_CREATED, tags=["admin", "templates", "uploads"])
def admin_create_template_preview_upload_session(
    template_id: int,
    payload: TemplatePreviewUploadCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    template = get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    relative_path, safe_name = allocate_upload_path(None, payload.filename, payload.mime_type, "template_preview")
    file_asset = create_file(
        db,
        owner_user_id=None,
        kind="template_preview",
        relative_path=relative_path,
        original_filename=safe_name,
        mime_type=payload.mime_type,
        size_bytes=0,
        checksum=None,
    )
    template.preview_image_file_id = file_asset.id
    db.add(template)
    db.commit()
    db.refresh(template)

    return {
        "file": file_asset,
        "upload": _build_signed_path_url(
            request,
            "upload_managed_file",
            file_asset,
            "upload",
            expires_in_seconds=payload.expires_in_seconds,
            extra={"filename": safe_name, "max_bytes": min(payload.max_bytes or MAX_SINGLE_UPLOAD_BYTES, MAX_SINGLE_UPLOAD_BYTES)},
        ),
    }


@app.get("/templates/{template_id}/preview-url", response_model=SignedFileUrlOut, tags=["templates", "files"])
def template_preview_download_url(
    template_id: int,
    request: Request,
    expires_in_seconds: Optional[int] = Query(None, ge=1, le=86400),
    db: Session = Depends(get_db),
):
    template = get_template(db, template_id, include_inactive=False)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.preview_image_file_id:
        raise HTTPException(status_code=404, detail="Template preview image not found")
    file_asset = _ensure_file_access(get_file(db, template.preview_image_file_id))
    return _build_signed_path_url(
        request,
        "download_managed_file",
        file_asset,
        "download",
        expires_in_seconds=expires_in_seconds,
        extra={"filename": file_asset.original_filename or sanitize_filename(file_asset.relative_path), "disposition": "inline"},
    )


@app.get("/templates/{template_id}/preview-public-url", tags=["templates", "files"])
def template_preview_public_url(
    template_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    template = get_template(db, template_id, include_inactive=False)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if not template.preview_image_file_id:
        raise HTTPException(status_code=404, detail="Template preview image not found")
    file_asset = _ensure_file_access(get_file(db, template.preview_image_file_id))
    return {"template_id": template.id, "file_id": file_asset.id, "url": _build_public_asset_url(request, file_asset)}


@app.put("/admin/templates/{template_id}", response_model=TemplateOut, tags=["admin"])
def admin_update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db)):
    template = update_template(db, template_id, payload)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@app.delete("/admin/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["admin"])
def admin_delete_template(template_id: int, db: Session = Depends(get_db)):
    deleted = deactivate_template(db, template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/admin/reports/usage-summary", response_model=SiteUsageSummaryOut, tags=["admin", "reports"])
def admin_site_usage_summary(db: Session = Depends(get_db)):
    return get_site_usage_summary(db)


@app.get("/admin/reports/template-usage", response_model=TemplateUsageReportOut, tags=["admin", "reports"])
def admin_template_usage_report(
    include_inactive: bool = Query(True, description="Include inactive templates in the usage report."),
    db: Session = Depends(get_db),
):
    return get_template_usage_report(db, include_inactive=include_inactive)


@app.get("/admin/reports/credits", response_model=CreditStatsReportOut, tags=["admin", "reports"])
def admin_credit_stats_report(
    user_id: Optional[int] = Query(None, description="Filter report to one user."),
    credits_per_generation: int = Query(1, ge=1, description="Legacy parameter kept for compatibility. Consumption now comes from stored generation credits_used values."),
    db: Session = Depends(get_db),
):
    return get_credit_stats_report(db, user_id=user_id, credits_per_generation=credits_per_generation)


@app.get("/admin/reports/revenuecat/refunds", response_model=RevenueCatRefundSummaryOut, tags=["admin", "reports", "revenuecat"])
def admin_revenuecat_refund_report(
    user_id: Optional[int] = Query(None, description="Filter RevenueCat refund events to one user."),
    limit: int = Query(100, ge=1, le=500, description="Maximum refund or chargeback events to return."),
    db: Session = Depends(get_db),
):
    return get_revenuecat_refund_report(db, user_id=user_id, limit=limit)


@app.get("/admin/jobs/", response_model=List[GenerationReportOut], tags=["admin", "reports"])
def admin_list_jobs(
    user_id: Optional[int] = Query(None, description="Filter jobs for one user."),
    template_id: Optional[int] = Query(None, description="Filter jobs for one template."),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter jobs by status."),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return get_generation_jobs_report(
        db,
        user_id=user_id,
        template_id=template_id,
        status=status_filter,
        skip=skip,
        limit=limit,
    )


@app.get("/admin/reports/jobs/users", response_model=List[UserGenerationStatsOut], tags=["admin", "reports"])
def admin_jobs_per_user_report(
    template_id: Optional[int] = Query(None, description="Filter user job stats to one template."),
    db: Session = Depends(get_db),
):
    return get_generation_stats_by_user(db, template_id=template_id)


@app.get(
    "/admin/reports/jobs/status-breakdown",
    response_model=List[GenerationStatusBreakdownOut],
    tags=["admin", "reports"],
)
def admin_job_status_breakdown_report(
    template_id: Optional[int] = Query(None, description="Filter breakdown to one template."),
    db: Session = Depends(get_db),
):
    return get_generation_status_breakdown(db, template_id=template_id)


@app.post("/webhooks/revenuecat", response_model=RevenueCatWebhookResultOut, tags=["webhooks", "revenuecat"])
def revenuecat_webhook(
    payload: RevenueCatWebhookIn,
    authorization: Optional[str] = Header(None),
    x_webhook_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    if REVENUECAT_WEBHOOK_SECRET:
        bearer_value = authorization.removeprefix("Bearer ").strip() if authorization else None
        presented_secret = bearer_value or x_webhook_secret
        if presented_secret != REVENUECAT_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid RevenueCat webhook secret")

    event = payload.event
    event_type = str(event.get("type") or event.get("event_type") or "").strip().upper()
    cancel_reason = str(event.get("cancel_reason") or "").strip().upper()
    event_id = str(event.get("id") or event.get("event_id") or "").strip()
    if not event_id:
        raise HTTPException(status_code=422, detail="RevenueCat event id is required")

    candidate = (
        event_type in {"REFUND", "REFUNDED", "CHARGEBACK"}
        or (event_type == "CANCELLATION" and any(token in cancel_reason for token in ["REFUND", "SUPPORT", "CUSTOMER", "FRAUD", "CHARGEBACK", "REVOKE"]))
    )
    if not candidate:
        return {
            "status": "ignored",
            "event_id": event_id,
            "processed": False,
            "credits_revoked": 0,
        }

    try:
        record, created = create_revenuecat_refund_event(db, event)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if record is None:
        return {
            "status": "ignored",
            "event_id": event_id,
            "processed": False,
            "credits_revoked": 0,
        }

    return {
        "status": "processed" if created else "duplicate",
        "event_id": event_id,
        "processed": created,
        "refund_kind": record.refund_kind,
        "user_id": record.user_id,
        "credits_revoked": record.credits_revoked,
    }


@app.get("/dashboard/admin/overview", response_model=SiteUsageSummaryOut, tags=["dashboard", "admin"])
def admin_dashboard_overview(db: Session = Depends(get_db)):
    return get_site_usage_summary(db)


@app.get("/dashboard/admin/users", response_model=List[AdminUserListItemOut], tags=["dashboard", "admin"])
def admin_dashboard_users(
    skip: int = 0,
    limit: int = 50,
    is_active: Optional[bool] = Query(None),
    email_query: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    return get_admin_users(db, skip=skip, limit=limit, is_active=is_active, email_query=email_query, search=search)


@app.get("/dashboard/admin/templates", response_model=List[TemplateOut], tags=["dashboard", "admin"])
def admin_dashboard_templates(
    include_inactive: bool = Query(True),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return get_templates(db, skip=skip, limit=limit, include_inactive=include_inactive)


@app.get("/dashboard/admin/comfyui/servers", response_model=List[ComfyUIServerOut], tags=["dashboard", "admin"])
def admin_dashboard_comfyui_servers(
    include_inactive: bool = Query(True),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return get_comfyui_servers(db, skip=skip, limit=limit, include_inactive=include_inactive, status=status_filter)


@app.get("/dashboard/admin/jobs", response_model=List[GenerationReportOut], tags=["dashboard", "admin"])
def admin_dashboard_jobs(
    user_id: Optional[int] = Query(None),
    template_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return get_generation_jobs_report(
        db,
        user_id=user_id,
        template_id=template_id,
        status=status_filter,
        skip=skip,
        limit=limit,
    )


@app.get("/dashboard/admin/credits", response_model=CreditStatsReportOut, tags=["dashboard", "admin"])
def admin_dashboard_credits(
    user_id: Optional[int] = Query(None),
    credits_per_generation: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    return get_credit_stats_report(db, user_id=user_id, credits_per_generation=credits_per_generation)


@app.get("/dashboard/admin/template-usage", response_model=TemplateUsageReportOut, tags=["dashboard", "admin"])
def admin_dashboard_template_usage(
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db),
):
    return get_template_usage_report(db, include_inactive=include_inactive)


@app.get("/dashboard/admin/jobs/users", response_model=List[UserGenerationStatsOut], tags=["dashboard", "admin"])
def admin_dashboard_jobs_users(
    template_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    return get_generation_stats_by_user(db, template_id=template_id)


@app.get(
    "/dashboard/admin/jobs/status-breakdown",
    response_model=List[GenerationStatusBreakdownOut],
    tags=["dashboard", "admin"],
)
def admin_dashboard_jobs_status_breakdown(
    template_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    return get_generation_status_breakdown(db, template_id=template_id)


@app.get("/dashboard/users/{user_id}/overview", response_model=UserDashboardOverviewOut, tags=["dashboard", "users"])
def user_dashboard_overview(user_id: int, db: Session = Depends(get_db)):
    overview = get_user_dashboard_overview(db, user_id)
    if not overview:
        raise HTTPException(status_code=404, detail="User not found")
    return overview


@app.get("/dashboard/users/{user_id}/jobs", response_model=List[GenerationReportOut], tags=["dashboard", "users"])
def user_dashboard_jobs(
    user_id: int,
    template_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    if not get_user_by_id(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return get_generation_jobs_report(db, user_id=user_id, template_id=template_id, status=status_filter, skip=skip, limit=limit)


@app.get("/dashboard/users/{user_id}/credits", response_model=UserCreditsSummaryOut, tags=["dashboard", "users"])
def user_dashboard_credits_view(user_id: int, db: Session = Depends(get_db)):
    if not get_user_by_id(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return get_user_dashboard_credits(db, user_id)


@app.get("/dashboard/users/{user_id}/templates", response_model=List[UserTemplateSummaryItemOut], tags=["dashboard", "users"])
def user_dashboard_templates_view(
    user_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    if not get_user_by_id(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return get_user_dashboard_templates(db, user_id, include_inactive=include_inactive)


@app.get("/dashboard/users/{user_id}/job-summary", response_model=UserJobSummaryOut, tags=["dashboard", "users"])
def user_dashboard_job_summary_view(user_id: int, db: Session = Depends(get_db)):
    if not get_user_by_id(db, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return get_user_dashboard_job_summary(db, user_id)


@app.get("/healthz", tags=["system"])
def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["system"])
def readyz(db: Session = Depends(get_db)):
    if not db_ready(db):
        raise HTTPException(status_code=503, detail="Database is not ready")
    return {"status": "ready"}


@app.get("/metrics", tags=["system"])
def get_metrics():
    return metrics_response(metrics)


@app.get("/", tags=["system"])
def read_root():
    return {
        "message": "Hello, world! FastAPI is running in Docker.",
        "monitoring": {
            "health": "/healthz",
            "readiness": "/readyz",
            "metrics": "/metrics",
        },
        "assets": {
            "public_base_path": PUBLIC_ASSET_PATH,
        },
    }
