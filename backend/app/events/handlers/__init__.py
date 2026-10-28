# ============================================================
# OPSYN EVENT HANDLERS — app/events/handlers/__init__.py
# Domain event handler classes — triggered by event_bus.emit()
# Non-blocking: failures are logged, not re-raised
# ============================================================

import logging
log = logging.getLogger("opsyn.events")


# ── staff.created ─────────────────────────────────────────────
async def _handle_staff_created(payload: dict) -> None:
    user_id       = payload.get("user_id", "")
    email         = payload.get("email", "")
    invite_method = payload.get("invite_method", "email")
    invite_token  = payload.get("invite_token")

    log.info("event.staff_created user_id=%s email=%s", user_id, email)

    if invite_method == "email" and invite_token:
        try:
            from app.modules.notifications.service import send_invite_email
            send_invite_email.delay(user_id=user_id, email=email, invite_token=invite_token)
        except Exception as exc:
            log.error("invite_email_dispatch_failed: %s", exc)


class staff_created:
    handle = staticmethod(_handle_staff_created)


# ── staff.role_changed ────────────────────────────────────────
async def _handle_role_changed(payload: dict) -> None:
    user_id  = payload.get("user_id", "")
    new_role = payload.get("new_role_name", "unknown")
    log.info("event.role_changed user_id=%s new_role=%s", user_id, new_role)


class role_changed:
    handle = staticmethod(_handle_role_changed)


# ── outage.logged ─────────────────────────────────────────────
async def _handle_outage_logged(payload: dict) -> None:
    incident_id = payload.get("incident_id", "")
    severity    = payload.get("severity", "warning")
    title       = payload.get("title", "")
    log.info("event.outage_logged id=%s severity=%s", incident_id, severity)

    if severity == "critical":
        try:
            from app.modules.notifications.service import send_outage_alert
            send_outage_alert.delay(incident_id=incident_id, title=title, severity=severity)
        except Exception as exc:
            log.error("outage_alert_dispatch_failed: %s", exc)


class outage_logged:
    handle = staticmethod(_handle_outage_logged)


# ── onboarding.approved ───────────────────────────────────────
async def _handle_onboarding_approved(payload: dict) -> None:
    email          = payload.get("email", "")
    candidate_name = payload.get("candidate_name", "")
    invite_url     = payload.get("invite_url", "")
    user_id        = payload.get("user_id", "")

    log.info("event.onboarding_approved user_id=%s email=%s", user_id, email)

    if not email or not invite_url:
        log.warning("onboarding_approved_missing_fields user_id=%s", user_id)
        return

    try:
        from app.modules.notifications.service import send_onboarding_approved_email
        send_onboarding_approved_email.delay(
            email=email,
            candidate_name=candidate_name,
            invite_url=invite_url,
        )
    except Exception as exc:
        log.error("onboarding_approved_email_dispatch_failed user_id=%s error=%s", user_id, exc)


class onboarding_approved:
    handle = staticmethod(_handle_onboarding_approved)


__all__ = ["staff_created", "role_changed", "outage_logged", "onboarding_approved"]
