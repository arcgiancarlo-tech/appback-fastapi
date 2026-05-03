from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, Text, ForeignKey, Float
from sqlalchemy.orm import relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Template(Base):
    __tablename__ = "templates"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    category = Column(String, nullable=True)
    is_spicy = Column(Boolean, nullable=False, default=False, server_default="0")
    preview_image_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    credit_cost = Column(Integer, nullable=False, default=0, server_default="0")
    disclaimer_text = Column(Text, nullable=True)
    best_use_text = Column(Text, nullable=True)
    generation_type = Column(String, nullable=True)
    comfyui_server_id = Column(String, nullable=True)
    workflow_key = Column(String, nullable=True)
    input_node_mapping = Column(String, nullable=True)
    output_node_mapping = Column(String, nullable=True)
    primary_color = Column(String, nullable=True)
    secondary_color = Column(String, nullable=True)
    accent_color = Column(String, nullable=True)
    background_color = Column(String, nullable=True)
    card_color = Column(String, nullable=True)
    text_color = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    preview_image_file = relationship("FileAsset", foreign_keys=[preview_image_file_id])

class FileAsset(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    kind = Column(String, nullable=False)
    storage_driver = Column(String, nullable=False, default="local_private_disk", server_default="local_private_disk")
    relative_path = Column(String, nullable=False, unique=True)
    original_filename = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0, server_default="0")
    checksum = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", backref="files")


class ComfyUIServer(Base):
    __tablename__ = "comfyui_servers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    base_url = Column(String, nullable=False)
    auth_token = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    healthcheck_status = Column(String, nullable=True)
    healthcheck_message = Column(Text, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Generation(Base):
    __tablename__ = "generations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    template_id = Column(Integer, ForeignKey("templates.id"))
    input_path = Column(String, nullable=False)
    output_path = Column(String, nullable=True)
    input_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    output_file_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    comfyui_job_id = Column(String, nullable=True)
    comfyui_server_id = Column(String, nullable=True)
    workflow_key = Column(String, nullable=True)
    result_kind = Column(String, nullable=True)
    status = Column(String, default="pending")
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    credits_used = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    queued_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", backref="generations")
    template = relationship("Template", backref="generations")
    input_file = relationship("FileAsset", foreign_keys=[input_file_id])
    output_file = relationship("FileAsset", foreign_keys=[output_file_id])

class CreditPack(Base):
    __tablename__ = "credit_packs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    pack_name = Column(String, nullable=False) # e.g., "50 credits"
    credits = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    provider = Column(String, nullable=True)
    product_key = Column(String, nullable=True)
    external_transaction_id = Column(String, nullable=True, unique=True, index=True)
    purchased_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="credit_packs")


class CreditPackConfig(Base):
    __tablename__ = "credit_pack_configs"

    id = Column(Integer, primary_key=True, index=True)
    slot_number = Column(Integer, nullable=False, unique=True, index=True)
    credit_amount = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    display_price_text = Column(String, nullable=False)
    product_key = Column(String, nullable=True)
    store_product_key_android = Column(String, nullable=True)
    store_product_key_ios = Column(String, nullable=True)
    active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RevenueCatWebhookEvent(Base):
    __tablename__ = "revenuecat_webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String, nullable=False)
    refund_kind = Column(String, nullable=False)  # refund | chargeback
    app_user_id = Column(String, nullable=False)
    product_id = Column(String, nullable=True)
    transaction_id = Column(String, nullable=True)
    original_transaction_id = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    amount = Column(Float, nullable=False, default=0.0, server_default="0")
    credits_revoked = Column(Integer, nullable=False, default=0, server_default="0")
    cancel_reason = Column(String, nullable=True)
    environment = Column(String, nullable=True)
    raw_payload = Column(Text, nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", backref="revenuecat_webhook_events")


class BillingIntegrationConfig(Base):
    __tablename__ = "billing_integration_config"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, default="RevenueCat", server_default="RevenueCat")
    environment = Column(String, nullable=False, default="test", server_default="test")
    connection_status = Column(String, nullable=False, default="disconnected", server_default="disconnected")
    public_api_key = Column(Text, nullable=True)
    secret_key = Column(Text, nullable=True)
    project_id = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TemplatePageDisplayConfig(Base):
    __tablename__ = "template_page_display_configs"

    id = Column(Integer, primary_key=True, index=True)
    page_type = Column(String, nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    order = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category = relationship("Category")


class ThemeSettings(Base):
    __tablename__ = "theme_settings"

    id = Column(Integer, primary_key=True, index=True)
    primary_color = Column(String, nullable=False, default="#d8a64a", server_default="#d8a64a")
    secondary_color = Column(String, nullable=False, default="#c58d2a", server_default="#c58d2a")
    accent_color = Column(String, nullable=False, default="#b45309", server_default="#b45309")
    background_color = Column(String, nullable=False, default="#111111", server_default="#111111")
    card_color = Column(String, nullable=False, default="#1b1b1b", server_default="#1b1b1b")
    text_color = Column(String, nullable=False, default="#ffffff", server_default="#ffffff")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
