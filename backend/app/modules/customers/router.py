# ============================================================
# OPSYN CUSTOMER API — app/modules/customers/router.py
# Registered at prefix /api/v1/customers in main.py
#
# Endpoints:
#   POST   /                  — create customer (atomic: customer + payment)
#   GET    /                  — list customers (filters: status, source_app, date)
#   GET    /{id}              — get customer detail (fields + pipeline state)
#   PATCH  /{id}/fields       — submit/update field values for a stage
#   GET    /{id}/fields       — get visible fields with current values
#   POST   /import            — bulk import via JSON (or CSV via Content-Type)
#   GET    /export            — export CSV (respects role field visibility)
# ============================================================

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.modules.customers.models import (
    Customer, PaymentRequest,
)
from app.modules.customers.service import customer_service
from app.modules.projects.models import Project
from app.modules.staff.models import User

router = APIRouter()

VALID_STATUSES   = {'pending', 'active', 'suspended', 'churned'}
VALID_SOURCE_APPS = {'field_tech', 'hr', 'sales', 'coverage_checker', 'manual'}


# ── Serializers ───────────────────────────────────────────────

def _payment_dict(pr: PaymentRequest) -> dict:
    return {
        "id":                str(pr.id),
        "amount":            float(pr.amount) if pr.amount is not None else 0.0,
        "currency":          pr.currency,
        "payment_link":      pr.payment_link,
        "status":            pr.status,
        "expires_at":        pr.expires_at.isoformat() if pr.expires_at else None,
        "provider_reference": pr.provider_reference,
    }


def _customer_dict(c: Customer, *, include_payment: bool = False, payment: Optional[PaymentRequest] = None) -> dict:
    d: dict = {
        "id":                    str(c.id),
        "tenant_id":             str(c.tenant_id),
        "first_name":            c.first_name,
        "last_name":             c.last_name,
        "full_name":             f"{c.first_name} {c.last_name}",
        "email":                 c.email,
        "phone":                 c.phone,
        "address":               c.address,
        "status":                c.status,
        "source_app":            c.source_app,
        "external_ref_id":       c.external_ref_id,
        "assigned_department_id": str(c.assigned_department_id) if c.assigned_department_id else None,
        "created_by":            str(c.created_by) if c.created_by else None,
        "created_at":            c.created_at.isoformat() if c.created_at else None,
        "updated_at":            c.updated_at.isoformat() if c.updated_at else None,
    }
    if include_payment and payment:
        d["payment"] = _payment_dict(payment)
    return d


# ── Pydantic schemas ──────────────────────────────────────────

class CustomerCreate(BaseModel):
    first_name:             str
    last_name:              str
    email:                  Optional[str] = None
    phone:                  Optional[str] = None
    address:                Optional[str] = None
    source_app:             str           = 'manual'
    external_ref_id:        Optional[str] = None
    assigned_department_id: Optional[uuid.UUID] = None
    amount:                 float         = 0.0
    currency:               str           = 'NGN'

    @field_validator('source_app')
    @classmethod
    def check_source(cls, v: str) -> str:
        if v not in VALID_SOURCE_APPS:
            raise ValueError(f"source_app must be one of: {', '.join(sorted(VALID_SOURCE_APPS))}")
        return v

    @field_validator('first_name', 'last_name')
    @classmethod
    def check_name(cls, v: str) -> str:
        if len(v.strip()) < 1:
            raise ValueError("Name must not be blank.")
        return v.strip()


class FieldSubmission(BaseModel):
    fields:      dict[str, Any]
    stage_order: int = 1


# ══════════════════════════════════════════════════════════════
# POST / — create customer (atomic)
# ══════════════════════════════════════════════════════════════

@router.post("/", status_code=201)
async def create_customer(
    body:   CustomerCreate = ...,
    db:     AsyncSession   = Depends(get_db),
    caller: User           = Depends(get_current_user),
):
    customer, pr = await customer_service.create_customer(
        db                     = db,
        tenant_id              = caller.tenant_id,
        caller                 = caller,
        first_name             = body.first_name,
        last_name              = body.last_name,
        email                  = body.email,
        phone                  = body.phone,
        address                = body.address,
        source_app             = body.source_app,
        external_ref_id        = body.external_ref_id,
        assigned_department_id = body.assigned_department_id,
        amount                 = body.amount,
        currency               = body.currency,
    )
    await db.commit()
    await db.refresh(customer)
    await db.refresh(pr)
    return {
        "success": True,
        "data":    _customer_dict(customer, include_payment=True, payment=pr),
    }


# ══════════════════════════════════════════════════════════════
# GET / — list customers (with filters)
# ══════════════════════════════════════════════════════════════

@router.get("/")
async def list_customers(
    status:     Optional[str]  = Query(None),
    source_app: Optional[str]  = Query(None),
    date_from:  Optional[date] = Query(None),
    date_to:    Optional[date] = Query(None),
    department_id: Optional[uuid.UUID] = Query(None),
    page:       int            = Query(1, ge=1),
    page_size:  int            = Query(50, ge=1, le=200),
    db:         AsyncSession   = Depends(get_db),
    caller:     User           = Depends(get_current_user),
):
    filters = [
        Customer.tenant_id  == caller.tenant_id,
        Customer.is_deleted == False,  # noqa: E712
    ]
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
        filters.append(Customer.status == status)
    if source_app:
        filters.append(Customer.source_app == source_app)
    if date_from:
        filters.append(Customer.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(Customer.created_at <= datetime.combine(date_to, datetime.max.time()))
    if department_id:
        filters.append(Customer.assigned_department_id == department_id)

    offset = (page - 1) * page_size
    rows = (await db.execute(
        select(Customer)
        .where(and_(*filters))
        .order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )).scalars().all()

    return {
        "success": True,
        "page":    page,
        "data":    [_customer_dict(c) for c in rows],
    }


# ══════════════════════════════════════════════════════════════
# GET /{id} — customer detail with payment + pipeline summary
# ══════════════════════════════════════════════════════════════

@router.get("/{customer_id}")
async def get_customer(
    customer_id: uuid.UUID   = Path(...),
    db:          AsyncSession = Depends(get_db),
    caller:      User         = Depends(get_current_user),
):
    customer = (await db.execute(
        select(Customer)
        .where(
            Customer.id        == customer_id,
            Customer.tenant_id == caller.tenant_id,
            Customer.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not customer:
        raise HTTPException(404, "Customer not found.")

    # Latest payment request
    pr = (await db.execute(
        select(PaymentRequest)
        .where(
            PaymentRequest.customer_id == customer_id,
            PaymentRequest.tenant_id   == caller.tenant_id,
        )
        .order_by(PaymentRequest.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    # Linked project(s)
    projects = (await db.execute(
        select(Project.id, Project.ticket_number, Project.pipeline_status, Project.name)
        .where(
            Project.customer_id == customer_id,
            Project.tenant_id   == caller.tenant_id,
        )
        .limit(5)
    )).all()

    data = _customer_dict(customer, include_payment=True, payment=pr)
    data["projects"] = [
        {
            "id":              str(p.id),
            "ticket_number":   p.ticket_number,
            "pipeline_status": p.pipeline_status,
            "name":            p.name,
        }
        for p in projects
    ]
    return {"success": True, "data": data}


# ══════════════════════════════════════════════════════════════
# PATCH /{id}/fields — submit field values for a stage
# ══════════════════════════════════════════════════════════════

@router.patch("/{customer_id}/fields")
async def submit_fields(
    customer_id: uuid.UUID      = Path(...),
    body:        FieldSubmission = ...,
    db:          AsyncSession    = Depends(get_db),
    caller:      User            = Depends(get_current_user),
):
    # Confirm customer exists and belongs to tenant
    customer = (await db.execute(
        select(Customer.id)
        .where(
            Customer.id        == customer_id,
            Customer.tenant_id == caller.tenant_id,
            Customer.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not customer:
        raise HTTPException(404, "Customer not found.")

    errors = await customer_service.submit_field_values(
        db          = db,
        tenant_id   = caller.tenant_id,
        customer_id = customer_id,
        caller      = caller,
        stage_order = body.stage_order,
        submitted   = body.fields,
    )
    if errors:
        raise HTTPException(422, detail={"field_errors": errors})

    await db.commit()
    return {"success": True, "message": f"{len(body.fields)} field(s) saved."}


# ══════════════════════════════════════════════════════════════
# GET /{id}/fields — visible fields with current values
# ══════════════════════════════════════════════════════════════

@router.get("/{customer_id}/fields")
async def get_customer_fields(
    customer_id: uuid.UUID   = Path(...),
    stage_order: int         = Query(1, ge=1),
    db:          AsyncSession = Depends(get_db),
    caller:      User         = Depends(get_current_user),
):
    exists = (await db.execute(
        select(Customer.id)
        .where(
            Customer.id        == customer_id,
            Customer.tenant_id == caller.tenant_id,
            Customer.is_deleted == False,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not exists:
        raise HTTPException(404, "Customer not found.")

    fields = await customer_service.get_visible_fields(
        db          = db,
        tenant_id   = caller.tenant_id,
        customer_id = customer_id,
        caller      = caller,
        stage_order = stage_order,
    )
    return {"success": True, "data": fields}


# ══════════════════════════════════════════════════════════════
# POST /import — bulk import (JSON)
# ══════════════════════════════════════════════════════════════

class ImportRow(BaseModel):
    first_name:             str
    last_name:              str
    email:                  Optional[str] = None
    phone:                  Optional[str] = None
    address:                Optional[str] = None
    source_app:             str           = 'manual'
    external_ref_id:        Optional[str] = None
    assigned_department_id: Optional[uuid.UUID] = None
    amount:                 float         = 0.0
    currency:               str           = 'NGN'


class ImportRequest(BaseModel):
    rows: list[ImportRow]


@router.post("/import", status_code=200)
async def import_customers(
    body:   ImportRequest = ...,
    db:     AsyncSession  = Depends(get_db),
    caller: User          = Depends(get_current_user),
):
    if not body.rows:
        raise HTTPException(400, "No rows provided.")

    results = []
    for idx, row in enumerate(body.rows):
        try:
            customer, pr = await customer_service.create_customer(
                db                     = db,
                tenant_id              = caller.tenant_id,
                caller                 = caller,
                first_name             = row.first_name,
                last_name              = row.last_name,
                email                  = row.email,
                phone                  = row.phone,
                address                = row.address,
                source_app             = row.source_app,
                external_ref_id        = row.external_ref_id,
                assigned_department_id = row.assigned_department_id,
                amount                 = row.amount,
                currency               = row.currency,
            )
            results.append({"row": idx + 1, "status": "created", "customer_id": str(customer.id)})
        except Exception as exc:
            results.append({"row": idx + 1, "status": "error", "error": str(exc)})
            await db.rollback()

    await db.commit()
    created = sum(1 for r in results if r["status"] == "created")
    return {
        "success":     True,
        "total":       len(body.rows),
        "created":     created,
        "errors":      len(body.rows) - created,
        "row_results": results,
    }


# ══════════════════════════════════════════════════════════════
# GET /export — export CSV (role-respecting)
# ══════════════════════════════════════════════════════════════

@router.get("/export")
async def export_customers(
    status:     Optional[str]  = Query(None),
    source_app: Optional[str]  = Query(None),
    db:         AsyncSession   = Depends(get_db),
    caller:     User           = Depends(get_current_user),
):
    role_level = caller.role.level if caller.role else 1

    filters = [
        Customer.tenant_id  == caller.tenant_id,
        Customer.is_deleted == False,  # noqa: E712
    ]
    if status:
        filters.append(Customer.status == status)
    if source_app:
        filters.append(Customer.source_app == source_app)

    rows = (await db.execute(
        select(Customer)
        .where(and_(*filters))
        .order_by(Customer.created_at.desc())
        .limit(10000)
    )).scalars().all()

    # Base columns always exported
    columns = ["id", "first_name", "last_name", "status", "source_app", "created_at"]
    # Sensitive columns only for managers+ (role level >= 3)
    if role_level >= 3:
        columns += ["email", "phone", "address", "external_ref_id"]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for c in rows:
        writer.writerow({
            "id":             str(c.id),
            "first_name":     c.first_name,
            "last_name":      c.last_name,
            "status":         c.status,
            "source_app":     c.source_app,
            "created_at":     c.created_at.isoformat() if c.created_at else "",
            "email":          c.email or "",
            "phone":          c.phone or "",
            "address":        c.address or "",
            "external_ref_id": c.external_ref_id or "",
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=customers.csv"},
    )
