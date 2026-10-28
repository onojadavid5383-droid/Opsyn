# ============================================================
# OPSYN FORM SYSTEM MODELS — app/modules/forms/models.py
# FormSchema · FormField · FormFieldDependency · FormSubmission
# ============================================================

from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Boolean, Integer, ForeignKey, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


VALID_FIELD_TYPES = {
    'text', 'textarea', 'number', 'dropdown',
    'date', 'phone', 'email', 'boolean', 'file', 'coordinates',
}

VALID_CONTEXTS = {'lead', 'task', 'project', 'onboarding'}

VALID_OPERATORS = {'eq', 'neq', 'gt', 'lt', 'contains', 'is_empty', 'is_not_empty'}

VALID_ACTIONS = {'show', 'hide', 'require'}


class LegacyFormSchema(Base):
    __tablename__      = 'legacy_form_schemas'
    __allow_unmapped__ = True

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id     = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    context       = Column(String(50),  nullable=False)
    version       = Column(Integer(),   nullable=False, default=1)
    is_published  = Column(Boolean(),   nullable=False, default=False)
    # is_active mirrors is_published; used by customer-module queries (added migration 0053)
    is_active     = Column(Boolean(),   nullable=False, default=False)
    title         = Column(String(200), nullable=False)
    description   = Column(Text(),      nullable=True)
    # department_id scopes schema to a department; NULL = global (added migration 0053)
    department_id = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    created_by    = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    fields       = relationship(
        'LegacyFormField', back_populates='schema',
        cascade='all, delete-orphan',
        order_by='LegacyFormField.field_order',
    )
    dependencies = relationship(
        'LegacyFormFieldDependency', back_populates='schema',
        cascade='all, delete-orphan',
    )


class LegacyFormField(Base):
    __tablename__      = 'legacy_form_fields'
    __allow_unmapped__ = True

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id        = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id        = Column(UUID(as_uuid=True), ForeignKey('legacy_form_schemas.id', ondelete='CASCADE'), nullable=False)
    field_key        = Column(String(100), nullable=False)
    field_type       = Column(String(50),  nullable=False)
    label            = Column(String(200), nullable=False)
    placeholder      = Column(Text(),      nullable=True)
    help_text        = Column(Text(),      nullable=True)
    required         = Column(Boolean(),   nullable=False, default=False)
    field_order      = Column(Integer(),   nullable=False, default=0)
    options          = Column(JSONB,       nullable=True)
    validation_rules = Column(JSONB,       nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    schema = relationship('LegacyFormSchema', back_populates='fields')


class LegacyFormFieldDependency(Base):
    __tablename__      = 'legacy_form_field_dependencies'
    __allow_unmapped__ = True

    id                 = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id          = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id          = Column(UUID(as_uuid=True), ForeignKey('legacy_form_schemas.id', ondelete='CASCADE'), nullable=False)
    source_field_key   = Column(String(100), nullable=False)
    target_field_key   = Column(String(100), nullable=False)
    condition_operator = Column(String(50),  nullable=False)
    condition_value    = Column(Text(),      nullable=True)
    action             = Column(String(20),  nullable=False)

    schema = relationship('LegacyFormSchema', back_populates='dependencies')


class LegacyFormSubmission(Base):
    __tablename__      = 'legacy_form_submissions'
    __allow_unmapped__ = True

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id      = Column(UUID(as_uuid=True), ForeignKey('legacy_form_schemas.id'), nullable=False)
    entity_type    = Column(String(50),  nullable=True)
    entity_id      = Column(UUID(as_uuid=True), nullable=True)
    submitted_by   = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    submitted_data = Column(JSONB,       nullable=False, default=dict)
    submitted_at   = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# Backward-compat aliases — existing imports by old names continue to work.
FormSchema          = LegacyFormSchema
FormField           = LegacyFormField
FormFieldDependency = LegacyFormFieldDependency
FormSubmission      = LegacyFormSubmission
