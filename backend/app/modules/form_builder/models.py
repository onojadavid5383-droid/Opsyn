# ============================================================
# FORM BUILDER ORM MODELS — app/modules/form_builder/models.py
# FormSchema · FormSchemaVersion · FieldDefinition
# FormAssociation · FormSubmission
#
# Plan reference: §3.2 – §3.9
# ============================================================

from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, Integer, SmallInteger,
    ForeignKey, DateTime, Text, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from app.core.database import Base


# ── Type catalogue — single source of truth ──────────────────
FIELD_TYPES: tuple[str, ...] = (
    'string', 'text', 'integer', 'float', 'boolean',
    'date', 'datetime', 'time', 'email', 'phone', 'url',
    'enum', 'multiselect', 'radio',
    'file', 'image',
    'coordinates', 'address', 'currency', 'rating', 'signature',
    'lookup', 'computed', 'section_header',
)

SCHEMA_STATUSES = ('draft', 'published', 'archived')
SUBMISSION_STATUSES = ('draft', 'submitted', 'approved', 'rejected')
CONTEXT_TYPES = ('module', 'pipeline_stage', 'department', 'external_trigger', 'user_role')
TRIGGER_EVENTS = ('on_create', 'on_stage_enter', 'on_approval', 'manual')
MODULES = ('customer', 'infrastructure', 'pipeline', 'field_ops', 'generic')
WIDTH_VALUES = ('full', 'half', 'third')


class FormSchema(Base):
    """
    Named schema with tenant ownership, versioning, status, and module association.
    The 'what is this form for' layer (§3.2).
    """
    __tablename__      = 'form_schemas'
    __allow_unmapped__ = True

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id       = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    name            = Column(String(200), nullable=False)
    machine_name    = Column(String(100), nullable=False)
    description     = Column(Text(),      nullable=True)
    module          = Column(String(50),  nullable=False)
    status          = Column(String(20),  nullable=False, default='draft')
    current_version = Column(Integer(),   nullable=False, default=0)
    icon            = Column(String(50),  nullable=True)
    color           = Column(String(7),   nullable=True)
    is_deleted      = Column(Boolean(),   nullable=False, default=False)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at      = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by      = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    versions    = relationship('FormSchemaVersion',  back_populates='schema',       cascade='all, delete-orphan')
    fields      = relationship('FieldDefinition',    back_populates='schema',       cascade='all, delete-orphan')
    associations = relationship('FormAssociation',   back_populates='schema',       cascade='all, delete-orphan')
    submissions  = relationship('FormSubmission',    back_populates='schema',       cascade='all, delete-orphan')


class FormSchemaVersion(Base):
    """
    Immutable snapshot created each time a schema is published.
    field_snapshot is a complete JSONB copy of all field definitions at publish time.
    Old submissions always reference their exact version (§3.3).
    """
    __tablename__      = 'form_schema_versions'
    __allow_unmapped__ = True

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id      = Column(UUID(as_uuid=True), ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False)
    tenant_id      = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    version_number = Column(Integer(),   nullable=False)
    published_at   = Column(DateTime(timezone=True), nullable=True)
    published_by   = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    field_snapshot = Column(JSONB,       nullable=False, default=list)
    changelog      = Column(Text(),      nullable=True)
    is_current     = Column(Boolean(),   nullable=False, default=False)
    created_at     = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by     = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    schema      = relationship('FormSchema',     back_populates='versions')
    submissions = relationship('FormSubmission', back_populates='schema_version')


class FieldDefinition(Base):
    """
    Every field in every schema. The 'what fields does this form have' layer (§3.4).
    field_key is the stable machine key used in submitted JSONB data.
    schema_version_id is NULL while in draft; set when snapshotted on publish.
    """
    __tablename__      = 'field_definitions'
    __allow_unmapped__ = True
    __table_args__ = (
        CheckConstraint(
            f"field_type IN ({', '.join(repr(t) for t in FIELD_TYPES)})",
            name='ck_fb_field_definitions_field_type',
        ),
    )

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id         = Column(UUID(as_uuid=True), ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False)
    schema_version_id = Column(UUID(as_uuid=True), ForeignKey('form_schema_versions.id', ondelete='SET NULL'), nullable=True)
    tenant_id         = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    field_key         = Column(String(100), nullable=False)
    label             = Column(String(200), nullable=False)
    placeholder       = Column(String(300), nullable=True)
    help_text         = Column(Text(),      nullable=True)
    field_type        = Column(String(30),  nullable=False)
    display_order     = Column(SmallInteger(), nullable=False, default=0)
    is_required       = Column(Boolean(),   nullable=False, default=False)
    is_unique         = Column(Boolean(),   nullable=False, default=False)
    is_readonly       = Column(Boolean(),   nullable=False, default=False)
    is_hidden         = Column(Boolean(),   nullable=False, default=False)
    default_value     = Column(Text(),      nullable=True)
    validation_rules  = Column(JSONB,       nullable=False, default=dict)
    options           = Column(JSONB,       nullable=True)
    conditional_logic = Column(JSONB,       nullable=True)
    role_visibility   = Column(ARRAY(Text()), nullable=True)
    role_editable     = Column(ARRAY(Text()), nullable=True)
    stage_visible_from = Column(SmallInteger(), nullable=True)
    stage_required_at  = Column(SmallInteger(), nullable=True)
    department_owner  = Column(UUID(as_uuid=True), ForeignKey('departments.id', ondelete='SET NULL'), nullable=True)
    width             = Column(String(10),  nullable=False, default='full')
    section_group     = Column(String(100), nullable=True)
    is_deleted        = Column(Boolean(),   nullable=False, default=False)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at        = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by        = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    schema         = relationship('FormSchema', back_populates='fields')
    schema_version = relationship('FormSchemaVersion', foreign_keys=[schema_version_id])


class FormAssociation(Base):
    """
    Links a schema to a context: module, pipeline stage, department, external trigger,
    or user role. The 'where does this form appear' layer (§3.8).
    """
    __tablename__      = 'form_associations'
    __allow_unmapped__ = True

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id           = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id           = Column(UUID(as_uuid=True), ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False)
    schema_version_id   = Column(UUID(as_uuid=True), ForeignKey('form_schema_versions.id', ondelete='SET NULL'), nullable=True)
    context_type        = Column(String(50),  nullable=False)
    context_id          = Column(UUID(as_uuid=True), nullable=True)
    context_label       = Column(String(200), nullable=False)
    is_mandatory        = Column(Boolean(),   nullable=False, default=False)
    display_order       = Column(SmallInteger(), nullable=False, default=0)
    trigger_event       = Column(String(50),  nullable=True)
    auto_populate_fields = Column(JSONB,      nullable=True)
    is_deleted          = Column(Boolean(),   nullable=False, default=False)
    created_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at          = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by          = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    schema         = relationship('FormSchema', back_populates='associations')
    schema_version = relationship('FormSchemaVersion', foreign_keys=[schema_version_id])
    submissions    = relationship('FormSubmission', back_populates='association')


class FormSubmission(Base):
    """
    Actual submitted values stored as versioned JSONB. The 'real data' layer (§3.9).
    schema_version_id is immutable — historical submissions always read against
    the version they were submitted under, even if the schema changed later.
    """
    __tablename__      = 'form_submissions'
    __allow_unmapped__ = True

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id         = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id         = Column(UUID(as_uuid=True), ForeignKey('form_schemas.id', ondelete='RESTRICT'), nullable=False)
    schema_version_id = Column(UUID(as_uuid=True), ForeignKey('form_schema_versions.id', ondelete='RESTRICT'), nullable=False)
    entity_type       = Column(String(50),  nullable=False)
    entity_id         = Column(UUID(as_uuid=True), nullable=True)
    association_id    = Column(UUID(as_uuid=True), ForeignKey('form_associations.id', ondelete='SET NULL'), nullable=True)
    submitted_by      = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    submitted_at      = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    status            = Column(String(20),  nullable=False, default='submitted')
    data              = Column(JSONB,       nullable=False, default=dict)
    draft_data        = Column(JSONB,       nullable=True)
    approved_by       = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    approved_at       = Column(DateTime(timezone=True), nullable=True)
    rejection_reason  = Column(Text(),      nullable=True)
    is_deleted        = Column(Boolean(),   nullable=False, default=False)
    created_at        = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at        = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by        = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    schema         = relationship('FormSchema',        back_populates='submissions')
    schema_version = relationship('FormSchemaVersion', back_populates='submissions')
    association    = relationship('FormAssociation',   back_populates='submissions')


class SchemaMigrationHistory(Base):
    """
    One executed change to a tenant's dynamic entity table
    (tenant_{tenant_id}_{machine_name}_data). The audit trail behind
    SchemaMigrationService: what was applied, by whom, and whether the
    inverse SQL can be replayed.

    No migration files are generated at runtime -- forward_sql is executed
    transactionally on the request's own session, and this table is the
    source of truth. See alembic/versions/0095_schema_migration_history.py.
    """
    __tablename__      = 'schema_migration_history'
    __allow_unmapped__ = True
    __table_args__     = (
        CheckConstraint("change_type IN ('create_table', 'add_column', 'alter_column',"
                        " 'drop_column', 'add_index', 'add_constraint')",
                        name='ck_schema_migration_history_change_type'),
        CheckConstraint("status IN ('pending', 'in_progress', 'applied',"
                        " 'failed', 'rolled_back')",
                        name='ck_schema_migration_history_status'),
    )

    id                     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id              = Column(UUID(as_uuid=True), ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False)
    schema_id              = Column(UUID(as_uuid=True), ForeignKey('form_schemas.id', ondelete='CASCADE'), nullable=False)

    # Migration identification
    migration_name         = Column(String(100), nullable=False)
    plan_hash              = Column(String(64),  nullable=False)   # sha256 of forward_sql
    alembic_revision       = Column(String(32),  nullable=True)    # informational only

    # Change tracking
    change_type            = Column(String(50),  nullable=False)
    field_changes          = Column(JSONB,       nullable=False, default=list)
    table_name             = Column(String(200), nullable=True)

    # SQL executed
    forward_sql            = Column(Text(),      nullable=False)
    rollback_sql           = Column(Text(),      nullable=True)

    # Execution tracking
    status                 = Column(String(20),  nullable=False, default='pending')
    is_destructive         = Column(Boolean(),   nullable=False, default=False)
    error_message          = Column(Text(),      nullable=True)
    execution_duration_ms  = Column(Integer(),   nullable=True)

    # Audit
    applied_by             = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    applied_at             = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at         = Column(DateTime(timezone=True), nullable=True)
    rolled_back_by         = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Metadata
    created_at             = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    created_by             = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    schema                 = relationship('FormSchema', foreign_keys=[schema_id])
    applied_by_user        = relationship('User', foreign_keys=[applied_by])
    created_by_user        = relationship('User', foreign_keys=[created_by])
    rolled_back_by_user    = relationship('User', foreign_keys=[rolled_back_by])
