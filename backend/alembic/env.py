# ============================================================
# OPSYN ALEMBIC ENV — alembic/env.py
# Connects Alembic to SQLAlchemy async engine + all ORM models
# ============================================================

import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# Load Opsyn config
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import settings
from app.core.database import Base

# ── Import ALL models so Alembic can see their metadata ───────
# Tenants (root entity — must be imported first)
from app.modules.tenants.models import Tenant

# Staff
from app.modules.staff.models import User, StaffProfile

# Remaining models (defined in all_modules.py)
from app.modules.all_modules import (
    Department, Team, Region,
    Role, UserScope, UserRoleHistory,
    StaffOnboardingRequest, Notification, Project, OutageIncident
)
from app.modules.tasks.router import Task, TaskComment, TaskTag
from app.modules.audit.router import AuditLog
from app.modules.activity.models import ActivityTimeline
from app.modules.infrastructure.models import (
    InfrastructureSite, InfrastructureNode, InfrastructureRoute,
    InfraUploadSession, InfraDeletionSession,
    Cabinet, OLT, SplitterBox,
    InfraUploadStaging, InfraAuditLog,
)
from app.modules.fttx_designer.models import (
    FttxDesignRun, FttxDesignRunLayer, FttxDesignRunOutput,
)
from app.modules.network.models import NetAsset, NetCable, NetConnection, NetFiber, NetPort
from app.modules.design.models import (
    Design, DesignInput, DesignInputUpload, DesignOperation, DesignValidationIssue, DesignVersion,
)

# Legacy form system (renamed tables — kept for backward compatibility)
from app.modules.forms.models import (
    FormSchema as LegacyFormSchema,
    FormField as LegacyFormField,
    FormFieldDependency as LegacyFormFieldDependency,
    FormSubmission as LegacyFormSubmission,
)
from app.modules.customers.models import (
    FieldDefinition as LegacyFieldDefinition,
    FieldVisibilityRule,
    Customer, CustomerFieldValue, CustomerFormSubmission, CustomerAuditLog,
)

# Form Builder — new schema-driven dynamic form system
from app.modules.form_builder.models import (
    FormSchema as FBFormSchema,
    FormSchemaVersion,
    FieldDefinition as FBFieldDefinition,
    FormAssociation,
    FormSubmission as FBFormSubmission,
    SchemaMigrationHistory,
)

# ── Alembic config ────────────────────────────────────────────
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations using async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
