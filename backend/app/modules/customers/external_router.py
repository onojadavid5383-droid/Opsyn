# ============================================================
# OPSYN EXTERNAL WEBHOOK ROUTER — app/modules/customers/external_router.py
# Registered at prefix /api/v1/external in main.py
# No JWT auth — authenticated via HMAC-SHA256 signature.
#
# Endpoints:
#   POST /tasks           — inbound external task + customer data (idempotent)
#   POST /payment-confirm — Finance App confirms payment → pipeline created
# ============================================================

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.customers.models import (
    ExternalTaskLog, PaymentConfirmation,
)
from app.modules.customers.service import customer_service
from app.modules.webhooks.models import WebhookApiKey

router = APIRouter()


# ── HMAC helpers ──────────────────────────────────────────────

def _verify_hmac(secret: str, raw_body: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature in sha256=<hex> format."""
    expected = "sha256=" + hmac_lib.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    try:
        return hmac_lib.compare_digest(expected, signature)
    except Exception:
        return False


async def _resolve_tenant_and_verify(
    db:        AsyncSession,
    tenant_id: uuid.UUID,
    app_name:  str,
    raw_body:  bytes,
    signature: str,
) -> None:
    """
    Look up the active WebhookApiKey for this tenant + app_name and
    verify the HMAC signature. Raises HTTP 401 on failure.
    """
    key_row = (await db.execute(
        select(WebhookApiKey).where(
            WebhookApiKey.tenant_id == tenant_id,
            WebhookApiKey.app_name  == app_name,
            WebhookApiKey.is_active.is_(True),
        )
    )).scalar_one_or_none()

    if not key_row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No active webhook key for this app.")

    if not _verify_hmac(key_row.key_value, raw_body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature.")


async def _log_external_event(
    db:              AsyncSession,
    tenant_id:       uuid.UUID,
    source_app:      str,
    payload:         dict,
    external_ref_id: Optional[str],
) -> ExternalTaskLog:
    """
    Write an ExternalTaskLog row BEFORE any processing.
    Checks idempotency: returns existing log if external_ref_id already seen.
    """
    if external_ref_id:
        existing = (await db.execute(
            select(ExternalTaskLog).where(
                ExternalTaskLog.tenant_id       == tenant_id,
                ExternalTaskLog.external_ref_id == external_ref_id,
            )
        )).scalar_one_or_none()
        if existing:
            return existing  # idempotent duplicate

    log = ExternalTaskLog(
        tenant_id       = tenant_id,
        source_app      = source_app,
        payload         = payload,
        status          = 'received',
        external_ref_id = external_ref_id,
    )
    db.add(log)
    await db.flush()
    return log


# ══════════════════════════════════════════════════════════════
# POST /tasks — external task + customer data (idempotent)
# ══════════════════════════════════════════════════════════════

@router.post("/tasks", status_code=200)
async def receive_external_task(
    request:     Request,
    x_webhook_tenant:    str = Header(..., alias="X-Webhook-Tenant"),
    x_webhook_app:       str = Header(..., alias="X-Webhook-App"),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_ref:       Optional[str] = Header(None, alias="X-Webhook-Ref"),
    db: AsyncSession = Depends(get_db),
):
    """
    Idempotent inbound webhook. External apps (Field Tech, HR, Sales) submit
    customer + optional task data. Duplicate X-Webhook-Ref values return 200
    with the existing record — no duplicate rows created.

    Expected payload:
    {
        "first_name": "...", "last_name": "...",
        "email": "...", "phone": "...",
        "amount": 15000, "currency": "NGN",
        "department_id": "<uuid>",   // optional
        "task_title": "...",         // optional — creates a linked task
        "task_description": "..."
    }
    """
    raw_body = await request.body()
    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload.")

    try:
        tenant_id = uuid.UUID(x_webhook_tenant)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Webhook-Tenant header.")

    # Verify HMAC before any DB write
    await _resolve_tenant_and_verify(db, tenant_id, x_webhook_app, raw_body, x_webhook_signature)

    # Idempotency check — log first, check if duplicate
    log = await _log_external_event(db, tenant_id, x_webhook_app, payload, x_webhook_ref)

    # If duplicate (log already existed and had a customer_id recorded), return existing
    if log.status in ('success', 'processing'):
        await db.commit()
        return {
            "success":   True,
            "idempotent": True,
            "log_id":    str(log.id),
        }

    log.status = 'processing'

    try:
        dept_id: Optional[uuid.UUID] = None
        if payload.get('department_id'):
            try:
                dept_id = uuid.UUID(str(payload['department_id']))
            except ValueError:
                pass

        customer, pr = await customer_service.create_customer(
            db                     = db,
            tenant_id              = tenant_id,
            caller                 = None,
            first_name             = payload.get('first_name', 'Unknown'),
            last_name              = payload.get('last_name', 'Unknown'),
            email                  = payload.get('email'),
            phone                  = payload.get('phone'),
            address                = payload.get('address'),
            source_app             = x_webhook_app,
            external_ref_id        = x_webhook_ref,
            assigned_department_id = dept_id,
            amount                 = float(payload.get('amount', 0.0)),
            currency               = payload.get('currency', 'NGN'),
        )

        log.status = 'success'
        import datetime
        log.processed_at = datetime.datetime.utcnow()

        await db.commit()
        return {
            "success":     True,
            "idempotent":  False,
            "customer_id": str(customer.id),
            "payment_link": pr.payment_link,
            "log_id":      str(log.id),
        }

    except Exception as exc:
        log.status = 'failed'
        log.error  = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Processing failed: {exc}")


# ══════════════════════════════════════════════════════════════
# POST /payment-confirm — Finance App confirms payment
# ══════════════════════════════════════════════════════════════

@router.post("/payment-confirm", status_code=200)
async def confirm_payment(
    request:     Request,
    x_webhook_tenant:    str = Header(..., alias="X-Webhook-Tenant"),
    x_webhook_app:       str = Header(..., alias="X-Webhook-App"),
    x_webhook_signature: str = Header(..., alias="X-Webhook-Signature"),
    x_webhook_ref:       Optional[str] = Header(None, alias="X-Webhook-Ref"),
    db: AsyncSession = Depends(get_db),
):
    """
    Finance App fires this webhook after payment is collected.
    Validates HMAC, updates payment_request to 'paid', customer to 'active',
    and creates a project pipeline entry.

    Expected payload:
    {
        "payment_request_id": "<uuid>",
        "amount_paid": 15000,
        "reference": "FIN-TXN-12345"
    }
    """
    raw_body = await request.body()
    try:
        payload: dict[str, Any] = json.loads(raw_body)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload.")

    try:
        tenant_id = uuid.UUID(x_webhook_tenant)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Webhook-Tenant header.")

    # Verify HMAC before any processing
    await _resolve_tenant_and_verify(db, tenant_id, x_webhook_app, raw_body, x_webhook_signature)

    # Idempotency check
    log = await _log_external_event(db, tenant_id, x_webhook_app, payload, x_webhook_ref)
    if log.status in ('success', 'processing'):
        await db.commit()
        return {"success": True, "idempotent": True, "log_id": str(log.id)}

    log.status = 'processing'

    try:
        pr_id_raw = payload.get('payment_request_id')
        if not pr_id_raw:
            raise ValueError("payload.payment_request_id is required.")
        payment_request_id = uuid.UUID(str(pr_id_raw))

        # Write confirmation record
        db.add(PaymentConfirmation(
            tenant_id            = tenant_id,
            payment_request_id   = payment_request_id,
            confirmed_by_app     = x_webhook_app,
            confirmation_payload = payload,
        ))
        await db.flush()

        project = await customer_service.confirm_payment_and_create_pipeline(
            db                   = db,
            payment_request_id   = payment_request_id,
            tenant_id            = tenant_id,
            confirmed_by_app     = x_webhook_app,
            confirmation_payload = payload,
            caller               = None,
        )

        log.status = 'success'
        import datetime
        log.processed_at = datetime.datetime.utcnow()

        await db.commit()
        return {
            "success":    True,
            "idempotent": False,
            "project_id": str(project.id),
            "ticket":     project.ticket_number,
            "log_id":     str(log.id),
        }

    except ValueError as exc:
        log.status = 'failed'
        log.error  = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except Exception as exc:
        log.status = 'failed'
        log.error  = str(exc)
        await db.commit()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Processing failed: {exc}")
