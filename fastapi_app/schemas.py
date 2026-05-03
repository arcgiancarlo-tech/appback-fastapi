from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    email: str


class UserOut(ORMBaseModel):
    id: int
    email: str
    is_active: bool
    created_at: Optional[datetime] = None


class TemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_spicy: bool = False
    preview_image_file_id: Optional[int] = None
    credit_cost: int = 0
    disclaimer_text: Optional[str] = None
    best_use_text: Optional[str] = None
    generation_type: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    input_node_mapping: Optional[str] = None
    output_node_mapping: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    background_color: Optional[str] = None
    card_color: Optional[str] = None
    text_color: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    is_spicy: Optional[bool] = None
    preview_image_file_id: Optional[int] = None
    credit_cost: Optional[int] = None
    disclaimer_text: Optional[str] = None
    best_use_text: Optional[str] = None
    generation_type: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    input_node_mapping: Optional[str] = None
    output_node_mapping: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    background_color: Optional[str] = None
    card_color: Optional[str] = None
    text_color: Optional[str] = None
    is_active: Optional[bool] = None


class TemplateOut(ORMBaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_spicy: bool = False
    preview_image_file_id: Optional[int] = None
    credit_cost: int
    disclaimer_text: Optional[str] = None
    best_use_text: Optional[str] = None
    generation_type: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    input_node_mapping: Optional[str] = None
    output_node_mapping: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    background_color: Optional[str] = None
    card_color: Optional[str] = None
    text_color: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    preview_image_file: Optional[FileAssetOut] = None


class TemplatePreviewUploadCreate(BaseModel):
    filename: str
    mime_type: Optional[str] = None
    expires_in_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    max_bytes: Optional[int] = Field(default=None, ge=1)


class ComfyUIServerCreate(BaseModel):
    name: str
    base_url: str
    auth_token: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool = True
    healthcheck_status: Optional[str] = None
    healthcheck_message: Optional[str] = None
    last_checked_at: Optional[datetime] = None


class ComfyUIServerUpdate(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    auth_token: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None
    healthcheck_status: Optional[str] = None
    healthcheck_message: Optional[str] = None
    last_checked_at: Optional[datetime] = None


class ComfyUIServerOut(ORMBaseModel):
    id: int
    name: str
    base_url: str
    auth_token: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    healthcheck_status: Optional[str] = None
    healthcheck_message: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FileAssetCreate(BaseModel):
    owner_user_id: Optional[int] = None
    kind: str
    storage_driver: str = "local_private_disk"
    relative_path: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int = 0
    checksum: Optional[str] = None


class FileAssetOut(ORMBaseModel):
    id: int
    owner_user_id: Optional[int] = None
    kind: str
    storage_driver: str
    relative_path: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int
    checksum: Optional[str] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class UploadCreate(BaseModel):
    user_id: int
    filename: str
    mime_type: Optional[str] = None
    content_base64: str


class UploadSessionCreate(BaseModel):
    owner_user_id: Optional[int] = None
    filename: str
    mime_type: Optional[str] = None
    kind: str = "user_input"
    expires_in_seconds: Optional[int] = Field(default=None, ge=1, le=86400)
    max_bytes: Optional[int] = Field(default=None, ge=1)


class SignedFileUrlOut(BaseModel):
    file_id: int
    url: str
    expires_at: datetime
    method: str = "GET"


class UploadSessionOut(BaseModel):
    file: FileAssetOut
    upload: SignedFileUrlOut


class GenerationCreate(BaseModel):
    user_id: int
    template_id: int
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    input_file_id: Optional[int] = None
    output_file_id: Optional[int] = None
    comfyui_job_id: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None
    status: str = "pending"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: int = 0
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


class GenerationStatusUpdate(BaseModel):
    status: Optional[str] = None
    comfyui_job_id: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None
    output_path: Optional[str] = None
    output_file_id: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: Optional[int] = None
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


class GenerationResultCreate(BaseModel):
    filename: str
    mime_type: Optional[str] = None
    content_base64: Optional[str] = None
    source_path: Optional[str] = None
    comfyui_job_id: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None


class GenerationOut(ORMBaseModel):
    id: int
    user_id: int
    template_id: int
    input_path: str
    output_path: Optional[str] = None
    input_file_id: Optional[int] = None
    output_file_id: Optional[int] = None
    comfyui_job_id: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: int
    created_at: Optional[datetime] = None
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    input_file: Optional[FileAssetOut] = None
    output_file: Optional[FileAssetOut] = None


class CreditPackCreate(BaseModel):
    user_id: int
    pack_name: str
    credits: int
    price: float


class CreditPackOut(ORMBaseModel):
    id: int
    user_id: int
    pack_name: str
    credits: int
    price: float
    provider: Optional[str] = None
    product_key: Optional[str] = None
    external_transaction_id: Optional[str] = None
    purchased_at: Optional[datetime] = None


class CreditPackConfigBase(BaseModel):
    slot_number: int = Field(ge=1, le=5)
    credit_amount: int = Field(gt=0)
    price: float = Field(gt=0)
    display_price_text: str = Field(min_length=1)
    product_key: Optional[str] = None
    store_product_key_android: Optional[str] = None
    store_product_key_ios: Optional[str] = None
    active: bool = True


class CreditPackConfigCreate(CreditPackConfigBase):
    pass


class CreditPackConfigUpdate(BaseModel):
    slot_number: Optional[int] = Field(default=None, ge=1, le=5)
    credit_amount: Optional[int] = Field(default=None, gt=0)
    price: Optional[float] = Field(default=None, gt=0)
    display_price_text: Optional[str] = Field(default=None, min_length=1)
    product_key: Optional[str] = None
    store_product_key_android: Optional[str] = None
    store_product_key_ios: Optional[str] = None
    active: Optional[bool] = None


class CreditPackConfigOut(ORMBaseModel):
    id: int
    slot_number: int
    credit_amount: int
    price: float
    display_price_text: str
    product_key: Optional[str] = None
    store_product_key_android: Optional[str] = None
    store_product_key_ios: Optional[str] = None
    active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreditPurchaseVerifyIn(BaseModel):
    user_id: int
    platform: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    receipt_data: str = Field(min_length=1)
    app_user_id: Optional[str] = None


class CreditPurchaseVerifyOut(BaseModel):
    status: str
    credited: bool
    pack_id: int
    pack_name: str
    credits_granted: int
    remaining_credits: int
    transaction_id: Optional[str] = None
    provider: str = "RevenueCat"


class AdminUserCount(BaseModel):
    count: int


class AdminUserModerationAction(BaseModel):
    reason: Optional[str] = None


class AdminUserCreditActionCreate(BaseModel):
    credits: int = Field(ge=1)
    reason: Optional[str] = None
    note: Optional[str] = None


class AdminUserStatusOut(BaseModel):
    user_id: int
    email: str
    is_active: bool
    status: str
    reason: Optional[str] = None


class AdminUserCreditActionOut(BaseModel):
    id: int
    credits: int
    reason: Optional[str] = None
    note: Optional[str] = None
    created_at: Optional[datetime] = None


class AdminUserListItemOut(BaseModel):
    id: int
    email: str
    phone: Optional[str] = None
    signup_method: str = "email"
    is_active: bool
    status: str
    created_at: Optional[datetime] = None
    total_credits: int
    remaining_credits: int
    purchased_credit_packs: int
    total_spend: float
    total_generations: int
    completed_generations: int
    failed_generations: int
    pending_generations: int
    last_generation_at: Optional[datetime] = None


class AdminUserStateSummary(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    users_with_generations: int
    users_with_credit_packs: int


class GenerationReportOut(ORMBaseModel):
    id: int
    user_id: int
    user_email: str
    template_id: int
    template_name: str
    input_path: str
    output_path: Optional[str] = None
    input_file_id: Optional[int] = None
    output_file_id: Optional[int] = None
    comfyui_job_id: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    credits_used: int
    created_at: Optional[datetime] = None
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None


class AdminUserDetailOut(AdminUserListItemOut):
    recent_generations: List[GenerationReportOut]
    manual_credit_actions: List[AdminUserCreditActionOut]


class UserGenerationStatsOut(ORMBaseModel):
    user_id: int
    user_email: str
    total_jobs: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int
    last_job_at: Optional[datetime] = None


class GenerationStatusBreakdownOut(ORMBaseModel):
    status: str
    total_jobs: int


class TemplateUsageItemOut(BaseModel):
    template_id: int
    template_name: str
    category: Optional[str] = None
    is_active: bool
    generation_count: int
    completed_count: int
    pending_count: int
    failed_count: int
    last_used_at: Optional[datetime] = None


class TemplateUsageReportOut(BaseModel):
    total_templates: int
    active_templates: int
    inactive_templates: int
    total_generations: int
    templates: List[TemplateUsageItemOut]


class CreditStatsUserOut(BaseModel):
    user_id: int
    user_email: str
    issued_credits: int
    refunded_credits: int
    chargeback_credits: int
    purchased_credit_packs: int
    purchased_amount: float
    refunded_amount: float
    chargeback_amount: float
    net_issued_credits: int
    net_purchase_amount: float
    refund_event_count: int
    chargeback_event_count: int
    generation_count: int
    completed_generation_count: int
    failed_generation_count: int
    pending_generation_count: int
    consumed_credits: int
    remaining_credits: int


class CreditStatsReportOut(BaseModel):
    credits_per_generation: int
    total_users: int
    issued_credits: int
    refunded_credits: int
    chargeback_credits: int
    net_issued_credits: int
    purchased_credit_packs: int
    purchased_amount: float
    refunded_amount: float
    chargeback_amount: float
    net_purchase_amount: float
    refund_event_count: int
    chargeback_event_count: int
    generation_count: int
    completed_generation_count: int
    failed_generation_count: int
    pending_generation_count: int
    consumed_credits: int
    remaining_credits: int
    users: List[CreditStatsUserOut]


class BillingIntegrationConfigUpdate(BaseModel):
    provider: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    connection_status: str = Field(min_length=1)
    public_api_key: str = ""
    secret_key: str = ""
    project_id: str = ""
    notes: str = ""


class BillingIntegrationConfigOut(BillingIntegrationConfigUpdate):
    id: int
    updated_at: Optional[datetime] = None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1)
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    is_active: Optional[bool] = None


class CategoryOut(ORMBaseModel):
    id: int
    name: str
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemplatePageDisplayConfigCreate(BaseModel):
    page_type: str = Field(min_length=1)
    category_id: int
    order: int = Field(ge=0)


class TemplatePageDisplayConfigUpdate(BaseModel):
    page_type: Optional[str] = Field(default=None, min_length=1)
    category_id: Optional[int] = None
    order: Optional[int] = Field(default=None, ge=0)


class TemplatePageDisplayConfigOut(ORMBaseModel):
    id: int
    page_type: str
    category_id: int
    order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    category: CategoryOut


class ThemeSettingsUpdate(BaseModel):
    primary_color: str = Field(min_length=1)
    secondary_color: str = Field(min_length=1)
    accent_color: str = Field(min_length=1)
    background_color: str = Field(min_length=1)
    card_color: str = Field(min_length=1)
    text_color: str = Field(min_length=1)


class ThemeSettingsOut(ThemeSettingsUpdate):
    id: int
    updated_at: Optional[datetime] = None


class RevenueCatWebhookIn(BaseModel):
    event: Dict[str, Any]


class RevenueCatWebhookEventOut(ORMBaseModel):
    id: int
    event_id: str
    user_id: int
    event_type: str
    refund_kind: str
    app_user_id: str
    product_id: Optional[str] = None
    transaction_id: Optional[str] = None
    original_transaction_id: Optional[str] = None
    currency: Optional[str] = None
    amount: float
    credits_revoked: int
    cancel_reason: Optional[str] = None
    environment: Optional[str] = None
    raw_payload: str
    event_timestamp: Optional[datetime] = None
    processed_at: Optional[datetime] = None


class RevenueCatWebhookResultOut(BaseModel):
    status: str
    event_id: str
    processed: bool
    refund_kind: Optional[str] = None
    user_id: Optional[int] = None
    credits_revoked: int = 0


class RevenueCatRefundSummaryOut(BaseModel):
    total_events: int
    refund_event_count: int
    chargeback_event_count: int
    total_credits_revoked: int
    refunded_credits: int
    chargeback_credits: int
    total_amount_reversed: float
    refunded_amount: float
    chargeback_amount: float
    events: List[RevenueCatWebhookEventOut]


class SiteUsageSummaryOut(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    users_with_generations: int
    users_with_credit_packs: int
    total_jobs: int
    jobs_by_status: Dict[str, int]
    credits_spent: int
    credits_earned: int
    credits_refunded: int
    credits_refunded_chargebacks: int
    credits_balance: int


class UserCreditsSummaryOut(BaseModel):
    issued_credits: int
    purchased_credit_packs: int
    purchased_amount: float
    consumed_credits: int
    remaining_credits: int


class UserJobSummaryOut(BaseModel):
    total_jobs: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int
    last_job_at: Optional[datetime] = None


class UserTemplateSummaryItemOut(BaseModel):
    template_id: int
    template_name: str
    category: Optional[str] = None
    is_active: bool
    generation_count: int
    last_used_at: Optional[datetime] = None


class UserDashboardOverviewOut(BaseModel):
    user: UserOut
    credits: UserCreditsSummaryOut
    jobs: UserJobSummaryOut
    recent_generations: List[GenerationReportOut]
    templates: List[UserTemplateSummaryItemOut]


class ComfyPromptSubmissionRequest(BaseModel):
    user_id: int
    template_id: int
    input_path: Optional[str] = None
    input_file_id: Optional[int] = None
    prompt_id: Optional[str] = None
    client_id: Optional[str] = None
    workflow_key: Optional[str] = None
    comfyui_server_id: Optional[str] = None
    result_kind: Optional[str] = None
    credits_used: int = 0
    status: str = "queued"


class ComfyCallbackTokenRequest(BaseModel):
    client_id: str
    client_secret: str


class ComfyCallbackTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class ComfyPromptSubmissionResponse(BaseModel):
    prompt_id: str
    generation_id: int
    number: int = 0
    node_errors: Dict[str, Any] = Field(default_factory=dict)
    status: str


class ComfyJobStatusResponse(BaseModel):
    prompt_id: str
    generation_id: int
    status: str
    completed: bool
    failed: bool
    output_file_id: Optional[int] = None
    output_path: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    generation: GenerationOut


class ComfyResultCallbackRequest(BaseModel):
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    content_base64: Optional[str] = None
    source_path: Optional[str] = None
    status: str = "completed"
    comfyui_server_id: Optional[str] = None
    workflow_key: Optional[str] = None
    result_kind: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ComfyResultCallbackResponse(BaseModel):
    prompt_id: str
    generation_id: int
    status: str
    result_received: bool
    output_file_id: Optional[int] = None
    output_path: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
