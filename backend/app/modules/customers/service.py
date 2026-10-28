# ============================================================
# OPSYN CUSTOMER SERVICE — app/modules/customers/service.py
# Business logic for customer creation, field submission,
# payment request generation, and pipeline bootstrapping.
# ============================================================

from __future__ import annotations

import uuid
import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.customers.models import (
    Customer, CustomerFieldValue, CustomerAuditLog, PaymentRequest, FieldDefinition,
)
from app.modules.customers.field_validator import validate_field_values
from app.modules.projects.models import Project, ProjectPipelineStage, PipelineTemplate, PipelineTemplateStage
from app.modules.staff.models import User

import logging
log = logging.getLogger("opsyn.customers")


def _actor_label(user: Optional[User]) -> str:
    """Architecture-invariant actor label resolution."""
    if user is None:
        return 'System'
    if user.staff_profile:
        return user.staff_profile.full_name
    return user.username


# ── Payment link helpers ──────────────────────────────────────

async def _generate_payment_link(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    payment_request_id: uuid.UUID,
) -> str:
    """
    Generate a payment link. Tries configured payment provider first.
    Falls back to internal pending link — never blocks customer creation.
    """
    try:
        from sqlalchemy import text
        async with db.begin_nested():  # SAVEPOINT — keeps outer tx clean if table missing
            config_row = (await db.execute(
                text("""
                    SELECT config_data FROM integration_configs
                    WHERE tenant_id = :tid AND app_name = 'payment' AND is_active = true
                    LIMIT 1
                """),
                {'tid': str(tenant_id)},
            )).fetchone()
        if config_row and config_row[0]:
            base_url = config_row[0].get('payment_base_url', '')
            if base_url:
                return f"{base_url.rstrip('/')}/{payment_request_id}"
    except Exception:
        # Falling through silently would change the payment URL the
        # customer is sent to, so record why the lookup failed.
        log.warning("payment_base_url_lookup_failed", exc_info=True)

    # Internal fallback
    return f"https://pay.opsyn.internal/pending/{payment_request_id}"


# ── Pipeline bootstrapping ────────────────────────────────────

async def _bootstrap_pipeline(
    db: AsyncSession,
    project: Project,
    customer: Customer,
    caller: Optional[User],
) -> None:
    """
    Start the project pipeline. Uses matching template if found,
    else seeds the 5-stage fallback — mirrors auto_generator.py logic.
    """
    from app.modules.projects.pipeline_service import start_pipeline

    dept_id = customer.assigned_department_id or project.department_id
    if not dept_id:
        return

    # Find an active template for the department
    template = (await db.execute(
        select(PipelineTemplate)
        .join(PipelineTemplateStage, PipelineTemplate.id == PipelineTemplateStage.template_id)
        .where(
            PipelineTemplateStage.department_id == dept_id,
            PipelineTemplate.is_active == True,  # noqa: E712
        )
        .limit(1)
    )).scalar_one_or_none()

    if template and caller:
        # Fixed arg order: project_id, template_id, db, current_user
        await start_pipeline(project.id, template.id, db, caller)
        return

    # Fallback: seed 5 generic stages
    FALLBACK_STAGES = [
        ("New", 1), ("Assigned", 2), ("In Progress", 3), ("Review", 4), ("Done", 5),
    ]
    now = datetime.datetime.utcnow()
    stages: list[ProjectPipelineStage] = []
    for name, order in FALLBACK_STAGES:
        stage = ProjectPipelineStage(
            project_id    = project.id,
            stage_order   = order,
            stage_name    = name,
            department_id = dept_id,
            status        = "pending",
        )
        db.add(stage)
        stages.append(stage)

    await db.flush()

    stages[0].status     = "active"
    stages[0].entered_at = now
    project.pipeline_status      = "active"
    project.current_stage_id     = stages[0].id
    project.pipeline_started_at  = now


# ── Core service ──────────────────────────────────────────────

class CustomerService:

    async def create_customer(
        self,
        db:             AsyncSession,
        tenant_id:      uuid.UUID,
        caller:         Optional[User],
        first_name:     str,
        last_name:      str,
        email:          Optional[str],
        phone:          Optional[str],
        address:        Optional[str],
        source_app:     str,
        external_ref_id: Optional[str],
        assigned_department_id: Optional[uuid.UUID],
        amount:         float = 0.0,
        currency:       str   = 'NGN',
    ) -> tuple[Customer, PaymentRequest]:
        """
        Atomically create customer + payment_request.
        Caller must commit after this returns.
        """
        customer = Customer(
            tenant_id               = tenant_id,
            first_name              = first_name,
            last_name               = last_name,
            email                   = email,
            phone                   = phone,
            address                 = address,
            status                  = 'pending',
            source_app              = source_app,
            external_ref_id         = external_ref_id,
            created_by              = caller.id if caller else None,
            assigned_department_id  = assigned_department_id,
        )
        db.add(customer)
        await db.flush()

        # Generate payment link (best-effort, never fails)
        payment_request_id = uuid.uuid4()
        link = await _generate_payment_link(db, tenant_id, payment_request_id)

        pr = PaymentRequest(
            id         = payment_request_id,
            tenant_id  = tenant_id,
            customer_id = customer.id,
            amount     = amount,
            currency   = currency,
            payment_link = link,
            status     = 'pending',
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(days=7),
        )
        db.add(pr)

        # Audit log for creation
        db.add(CustomerAuditLog(
            tenant_id   = tenant_id,
            customer_id = customer.id,
            actor_id    = caller.id if caller else None,
            action      = 'customer_created',
            new_value   = f"{first_name} {last_name} via {source_app}",
        ))

        return customer, pr

    async def submit_field_values(
        self,
        db:          AsyncSession,
        tenant_id:   uuid.UUID,
        customer_id: uuid.UUID,
        caller:      User,
        stage_order: int,
        submitted:   dict[str, Any],
    ) -> dict[str, str]:
        """
        Validate and upsert field values for a customer at a given pipeline stage.
        Returns field-level error dict (empty = success).
        """
        # Load field definitions visible at this stage
        fds = (await db.execute(
            select(FieldDefinition)
            .where(
                FieldDefinition.tenant_id              == tenant_id,
                FieldDefinition.is_deleted             == False,  # noqa: E712
                FieldDefinition.visible_from_stage_order <= stage_order,
            )
            .options(selectinload(FieldDefinition.visibility_rules))
        )).scalars().all()

        # Role filter — only fields the caller can edit
        caller_role = (caller.role.name or '').lower() if caller.role else ''
        role_level  = caller.role.level if caller.role else 1
        editable = [
            fd for fd in fds
            if role_level >= 5 or not fd.roles_can_edit
            or caller_role in [r.lower() for r in fd.roles_can_edit]
        ]

        field_defs_for_validation = [
            {
                "key":              fd.key,
                "field_type":       fd.field_type,
                "validation_rules": fd.validation_rules or {},
                "is_required":      fd.is_required,
            }
            for fd in editable
        ]

        errors = validate_field_values(submitted, field_defs_for_validation)
        if errors:
            return errors

        # Upsert each submitted value
        key_to_fd = {fd.key: fd for fd in editable}
        dept_id = caller.staff_profile.department_id if caller.staff_profile else None

        for key, value in submitted.items():
            fd = key_to_fd.get(key)
            if not fd:
                continue

            existing = (await db.execute(
                select(CustomerFieldValue)
                .where(
                    CustomerFieldValue.customer_id         == customer_id,
                    CustomerFieldValue.field_definition_id == fd.id,
                )
            )).scalar_one_or_none()

            if existing:
                old_val = existing.value
                existing.value       = str(value) if value is not None else None
                existing.department_id = dept_id
                existing.updated_by  = caller.id
                existing.updated_at  = datetime.datetime.utcnow()
                db.add(CustomerAuditLog(
                    tenant_id   = tenant_id,
                    customer_id = customer_id,
                    actor_id    = caller.id,
                    action      = 'field_updated',
                    field_key   = key,
                    old_value   = old_val,
                    new_value   = str(value) if value is not None else None,
                ))
            else:
                db.add(CustomerFieldValue(
                    tenant_id           = tenant_id,
                    customer_id         = customer_id,
                    field_definition_id = fd.id,
                    value               = str(value) if value is not None else None,
                    department_id       = dept_id,
                    updated_by          = caller.id,
                ))
                db.add(CustomerAuditLog(
                    tenant_id   = tenant_id,
                    customer_id = customer_id,
                    actor_id    = caller.id,
                    action      = 'field_set',
                    field_key   = key,
                    new_value   = str(value) if value is not None else None,
                ))

        return {}

    async def get_visible_fields(
        self,
        db:          AsyncSession,
        tenant_id:   uuid.UUID,
        customer_id: uuid.UUID,
        caller:      User,
        stage_order: int = 1,
    ) -> list[dict]:
        """
        Return field definitions visible at stage_order, filtered by caller's
        department and role, enriched with the customer's current value.
        """
        caller_role  = (caller.role.name or '').lower() if caller.role else ''
        role_level   = caller.role.level if caller.role else 1
        caller_dept  = caller.staff_profile.department_id if caller.staff_profile else None

        fds = (await db.execute(
            select(FieldDefinition)
            .where(
                FieldDefinition.tenant_id              == tenant_id,
                FieldDefinition.is_deleted             == False,  # noqa: E712
                FieldDefinition.visible_from_stage_order <= stage_order,
            )
            .options(selectinload(FieldDefinition.visibility_rules))
            .order_by(FieldDefinition.field_order)
        )).scalars().all()

        # Role visibility filter
        if role_level < 5:
            fds = [
                fd for fd in fds
                if not fd.roles_can_edit
                or caller_role in [r.lower() for r in fd.roles_can_edit]
            ]

        # Department visibility filter (owner dept or no restriction)
        if caller_dept and role_level < 5:
            fds = [
                fd for fd in fds
                if fd.owner_department_id is None
                or fd.owner_department_id == caller_dept
            ]

        # Load current values for this customer
        fv_rows = (await db.execute(
            select(CustomerFieldValue)
            .where(
                CustomerFieldValue.tenant_id   == tenant_id,
                CustomerFieldValue.customer_id == customer_id,
            )
        )).scalars().all()
        values_by_field = {str(fv.field_definition_id): fv.value for fv in fv_rows}

        results = []
        for fd in fds:
            is_required_here = any(
                vr.is_required_to_advance
                for vr in fd.visibility_rules
                if vr.stage_order == stage_order
                and (caller_dept is None or str(vr.department_id) == str(caller_dept))
            )
            results.append({
                "field_id":                str(fd.id),
                "key":                     fd.key,
                "label":                   fd.label,
                "field_type":              fd.field_type,
                "validation_rules":        fd.validation_rules,
                "is_required":             fd.is_required,
                "is_required_at_stage":    is_required_here,
                "owner_department_id":     str(fd.owner_department_id) if fd.owner_department_id else None,
                "visible_from_stage_order": fd.visible_from_stage_order,
                "roles_can_edit":          fd.roles_can_edit or [],
                "current_value":           values_by_field.get(str(fd.id)),
            })
        return results

    async def confirm_payment_and_create_pipeline(
        self,
        db:                 AsyncSession,
        payment_request_id: uuid.UUID,
        tenant_id:          uuid.UUID,
        confirmed_by_app:   str,
        confirmation_payload: dict,
        caller:             Optional[User],
    ) -> Project:
        """
        Called by the Finance App webhook. Updates payment status and
        bootstraps the project pipeline for the customer.
        """
        from app.modules.projects.models import Project

        pr = (await db.execute(
            select(PaymentRequest)
            .where(
                PaymentRequest.id        == payment_request_id,
                PaymentRequest.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not pr:
            raise ValueError(f"PaymentRequest {payment_request_id} not found.")

        pr.status     = 'paid'
        pr.updated_at = datetime.datetime.utcnow()

        customer = (await db.execute(
            select(Customer).where(Customer.id == pr.customer_id)
        )).scalar_one_or_none()
        if not customer:
            raise ValueError("Customer not found for this payment request.")

        customer.status     = 'active'
        customer.updated_at = datetime.datetime.utcnow()

        # Create project pipeline entry
        from app.modules.projects.auto_generator import _generate_project_ticket_number

        ticket = await _generate_project_ticket_number(db)
        project = Project(
            name             = f"Customer: {customer.first_name} {customer.last_name}",
            description      = f"Auto-generated from payment confirmation via {confirmed_by_app}",
            project_type     = "customer",
            source_app       = confirmed_by_app,
            auto_generated   = True,
            customer_id      = customer.id,
            department_id    = customer.assigned_department_id,
            owner_id         = caller.id if caller else None,
            ticket_number    = ticket,
            tenant_id        = tenant_id,
            pipeline_status  = "not_started",
        )
        db.add(project)
        await db.flush()

        await _bootstrap_pipeline(db, project, customer, caller)

        db.add(CustomerAuditLog(
            tenant_id   = tenant_id,
            customer_id = customer.id,
            actor_id    = caller.id if caller else None,
            action      = 'payment_confirmed_pipeline_created',
            new_value   = f"project={project.id} ticket={ticket}",
        ))

        return project


customer_service = CustomerService()
