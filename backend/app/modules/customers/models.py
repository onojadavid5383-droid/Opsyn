# ============================================================
# OPSYN CUSTOMER MODULE MODELS — app/modules/customers/models.py
# FieldDefinition · FieldVisibilityRule
# Customer · CustomerFieldValue · CustomerFormSubmission · CustomerAuditLog
# (PaymentRequest · PaymentConfirmation defined separately in payment models)
# ============================================================

from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, Integer, ForeignKey,
    DateTime, Text, Numeric,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from app.core.database import Base

# ── Valid field types accepted by the customer form builder ───
VALID_FIELD_TYPES = frozenset({
    'text', 'number', 'email', 'phone',
    'select', 'multiselect', 'date', 'file', 'textarea',
})


class LegacyFieldDefinition(Base):
    """
    Customer-pipeline-aware field definition (legacy — superseded by form_builder.FieldDefinition).
    Separate from FormField (0037) which serves general lead/task/onboarding forms.
    Stores stage visibility and department ownership alongside validation rules.
    """
    __tablename__      = 'legacy_field_definitions'
    __allow_unmapped__ = True

    id                      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id               = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    form_schema_id          = Column(UUID(as_uuid=True), ForeignKey('legacy_form_schemas.id', ondelete='CASCADE'), nullable=False)
    key                     = Column(String(100), nullable=False)
    label                   = Column(String(200), nullable=False)
    field_type              = Column(String(50),  nullable=False)
    validation_rules        = Column(JSONB,        nullable=True)
    is_required             = Column(Boolean(),    nullable=False, default=False)
    owner_department_id     = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    # Stage order at which this field first appears in the pipeline UI
    visible_from_stage_order = Column(Integer(), nullable=False, default=1)
    # Role names permitted to edit this field value
    roles_can_edit          = Column(ARRAY(Text()), nullable=False, default=list)
    field_order             = Column(Integer(),    nullable=False, default=0)
    is_deleted              = Column(Boolean(),    nullable=False, default=False)
    created_at              = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at              = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    visibility_rules = relationship(
        'FieldVisibilityRule',
        back_populates='field_definition',
        cascade='all, delete-orphan',
    )


class FieldVisibilityRule(Base):
    """
    Fine-grained stage × department visibility matrix.
    is_required_to_advance = True → field must be complete before stage advances.
    """
    __tablename__      = 'field_visibility_rules'
    __allow_unmapped__ = True

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id           = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    field_definition_id = Column(UUID(as_uuid=True), ForeignKey('legacy_field_definitions.id', ondelete='CASCADE'), nullable=False)
    stage_order         = Column(Integer(), nullable=False)
    department_id       = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='CASCADE'), nullable=False)
    is_required_to_advance = Column(Boolean(), nullable=False, default=False)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    field_definition = relationship('LegacyFieldDefinition', back_populates='visibility_rules')


class Customer(Base):
    """Master customer record. source_app tracks which external app created it."""
    __tablename__      = 'customers'
    __allow_unmapped__ = True

    id                    = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id             = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    first_name            = Column(String(100), nullable=False)
    last_name             = Column(String(100), nullable=False)
    email                 = Column(String(255), nullable=True)
    phone                 = Column(String(50),  nullable=True)
    address               = Column(Text(),      nullable=True)
    status                = Column(String(20),  nullable=False, default='pending')
    source_app            = Column(String(50),  nullable=False, default='manual')
    external_ref_id       = Column(String(255), nullable=True)
    created_by            = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    assigned_department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    is_deleted            = Column(Boolean(),   nullable=False, default=False)
    deleted_at            = Column(DateTime(timezone=True), nullable=True)
    deleted_by            = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at            = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at            = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    field_values = relationship('CustomerFieldValue', back_populates='customer', cascade='all, delete-orphan')
    audit_logs   = relationship('CustomerAuditLog',   back_populates='customer', cascade='all, delete-orphan')
    payment_requests = relationship('PaymentRequest', back_populates='customer', cascade='all, delete-orphan')


class CustomerFieldValue(Base):
    """Flat field value store. One row per field per customer (upsert pattern)."""
    __tablename__      = 'customer_field_values'
    __allow_unmapped__ = True

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id           = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id         = Column(UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    field_definition_id = Column(UUID(as_uuid=True), ForeignKey('legacy_field_definitions.id', ondelete='CASCADE'), nullable=False)
    value               = Column(Text(),      nullable=True)
    department_id       = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    updated_by          = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer         = relationship('Customer', back_populates='field_values')
    field_definition = relationship('LegacyFieldDefinition')


class CustomerFormSubmission(Base):
    """Per-stage JSONB snapshot of submitted field values."""
    __tablename__      = 'customer_form_submissions'
    __allow_unmapped__ = True

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id    = Column(UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    form_schema_id = Column(UUID(as_uuid=True), ForeignKey('legacy_form_schemas.id', ondelete='RESTRICT'), nullable=False)
    submitted_data = Column(JSONB, nullable=False, default=dict)
    submitted_by   = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    stage          = Column(Integer(), nullable=False, default=1)
    submitted_at   = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


class CustomerAuditLog(Base):
    """Full audit trail for every field change and lifecycle event on a customer."""
    __tablename__      = 'customer_audit_log'
    __allow_unmapped__ = True

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id   = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=True)
    actor_id    = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action      = Column(String(100), nullable=False)
    field_key   = Column(String(100), nullable=True)
    old_value   = Column(Text(),      nullable=True)
    new_value   = Column(Text(),      nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    customer = relationship('Customer', back_populates='audit_logs')


class PaymentRequest(Base):
    """Auto-generated payment request on customer creation."""
    __tablename__      = 'payment_requests'
    __allow_unmapped__ = True

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id           = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    customer_id         = Column(UUID(as_uuid=True), ForeignKey('customers.id', ondelete='CASCADE'), nullable=False)
    amount              = Column(Numeric(precision=12, scale=2), nullable=False, default=0)
    currency            = Column(String(10),  nullable=False, default='NGN')
    payment_link        = Column(Text(),      nullable=True)
    status              = Column(String(20),  nullable=False, default='pending')
    expires_at          = Column(DateTime(timezone=True), nullable=True)
    provider_reference  = Column(String(255), nullable=True)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer       = relationship('Customer', back_populates='payment_requests')
    confirmations  = relationship('PaymentConfirmation', back_populates='payment_request', cascade='all, delete-orphan')


class PaymentConfirmation(Base):
    """Written by Finance App webhook when payment is confirmed."""
    __tablename__      = 'payment_confirmations'
    __allow_unmapped__ = True

    id                   = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id            = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    payment_request_id   = Column(UUID(as_uuid=True), ForeignKey('payment_requests.id', ondelete='CASCADE'), nullable=False)
    confirmed_by_app     = Column(String(100), nullable=False)
    confirmation_payload = Column(JSONB, nullable=False, default=dict)
    confirmed_at         = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    payment_request = relationship('PaymentRequest', back_populates='confirmations')


class ExternalTaskLog(Base):
    """Immutable inbound webhook log. Written before processing for replay support."""
    __tablename__      = 'external_task_logs'
    __allow_unmapped__ = True

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id       = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    source_app      = Column(String(100), nullable=False)
    payload         = Column(JSONB, nullable=False, default=dict)
    status          = Column(String(20),  nullable=False, default='received')
    error           = Column(Text(),      nullable=True)
    processed_at    = Column(DateTime(timezone=True), nullable=True)
    external_ref_id = Column(String(255), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# Backward-compat alias — existing imports by the old name continue to work.
FieldDefinition = LegacyFieldDefinition
