# ============================================================
# OPSYN APPROVAL — app/modules/approval/service.py
# Network GIS Phase 9: design and BOQ approval, standalone (plan §3.10, D3).
#
#   Design  submit (no validation ERRORs; the current version is frozen and
#           the design locked, UNDER_REVIEW) → ENGINEERING_REVIEW
#           (design.review) → LINE_MANAGER_APPROVAL (design.approve) →
#           APPROVED: that version is the approved one
#   BOQ     only against an APPROVED design version; quantities and street
#           BOQ frozen in the request at submission (revision 1, 2, …) →
#           BOQ_REVIEW (boq.review) → BOQ_APPROVAL (boq.approve)
#   Reject  at any step, with a reason: the item goes back to revision. A
#           rejected design gets a new current version for the changes, so
#           the next submission is a new design version; a rejected BOQ is
#           resubmitted as the next revision
#   Withdraw  the submitter can take a pending request back
#   Reopen    an approved (not deployed) design goes back to editing in a
#           new version; its approval stays in the history
#   Gate    deployment (Phase 10) needs the current version's design
#           approved AND a BOQ approved for that same version
# The person who submitted cannot decide their own request (admins can).
# Reviewers are told through in-app notifications.
# The design's rows follow along the lifecycle (network/lifecycle.py):
# submitted → UNDER_REVIEW, approved → APPROVED (from where deployment
# moves them to CONSTRUCTION), sent back / withdrawn / reopened → DESIGNED.
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.permissions import check_permission
from app.modules.design import audit, versions
from app.modules.design.models import Design

DESIGN_STEPS = (("ENGINEERING_REVIEW", "design.review", "Engineering review"),
                ("LINE_MANAGER_APPROVAL", "design.approve", "Line manager approval"))
BOQ_STEPS = (("BOQ_REVIEW", "boq.review", "BOQ review"), ("BOQ_APPROVAL", "boq.approve", "BOQ approval"))
SUBMITTABLE = ("DRAFT", "GENERATED", "MODIFIED", "REJECTED")


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


async def can(db: AsyncSession, caller: Any, feature_key: str) -> bool:
    """The same decision check_permission() makes for a route, from code."""
    try:
        await check_permission(feature_key)(db=db, caller=caller)
        return True
    except HTTPException:
        return False


async def holders(db: AsyncSession, tid: uuid.UUID, feature_key: str) -> list[uuid.UUID]:
    """Active users of the tenant who hold a feature (admins always do)."""
    return list((await db.execute(text("""
        SELECT DISTINCT u.id FROM users u
        JOIN roles r ON r.id = u.role_id
        LEFT JOIN staff_profiles sp ON sp.user_id = u.id
        WHERE u.tenant_id = :tid AND coalesce(u.is_active, true)
          AND (r.level >= 5
               OR EXISTS (SELECT 1 FROM department_feature_grants g WHERE g.tenant_id = :tid
                          AND g.department_id = sp.department_id AND g.feature_key = :k AND r.level >= g.min_role_level)
               OR EXISTS (SELECT 1 FROM role_feature_overrides o WHERE o.tenant_id = :tid
                          AND o.role_id = u.role_id AND o.feature_key = :k AND o.is_granted))
    """), {"tid": tid, "k": feature_key})).scalars())


async def _notify(db: AsyncSession, tid: uuid.UUID, recipients: list[uuid.UUID], title: str, body: str,
                  design: Design, sender: Any) -> None:
    from app.modules.notifications.service import NotificationService
    svc = NotificationService()
    for rid in {r for r in recipients if r and r != getattr(sender, "id", None)}:
        await svc.create_notification(db, str(rid), "design_approval", title, body,
                                      action_url=f"/network?mode=design&design={design.id}", tenant_id=str(tid),
                                      notification_category="design_approval", sender_id=str(sender.id) if sender else None,
                                      related_project_id=str(design.project_id))


async def set_lifecycle(db: AsyncSession, design_id: uuid.UUID, target: str) -> None:
    """Every row of the design's working set to one lifecycle state (one audit summary, not a row each)."""
    await audit.bulk(db)
    for table in ("net_assets", "net_cables", "net_connections"):
        await db.execute(text(f"UPDATE {table} SET lifecycle_status = :s WHERE design_id = :d AND deleted_at IS NULL"),
                         {"s": target, "d": design_id})
    await audit.bulk(db, on=False)


# ── Reading ──────────────────────────────────────────────────

async def _request(db: AsyncSession, tid: uuid.UUID, request_id: str) -> Any:
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise _bad("Approval request not found", status.HTTP_404_NOT_FOUND) from None
    r = (await db.execute(text("SELECT * FROM approval_requests WHERE id = :id AND tenant_id = :tid"),
                          {"id": rid, "tid": tid})).first()
    if r is None:
        raise _bad("Approval request not found", status.HTTP_404_NOT_FOUND)
    return r


async def _names(db: AsyncSession, ids: set[Any]) -> dict[Any, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {r.id: r.label for r in (await db.execute(text("""
        SELECT u.id, coalesce(nullif(trim(sp.first_name || ' ' || sp.last_name), ''), u.username) AS label
        FROM users u LEFT JOIN staff_profiles sp ON sp.user_id = u.id WHERE u.id = ANY(:ids)
    """), {"ids": list(ids)})).all()}


async def request_out(db: AsyncSession, r: Any, caller: Any = None) -> dict[str, Any]:
    steps = (await db.execute(text("SELECT * FROM approval_steps WHERE request_id = :r ORDER BY step_no"), {"r": r.id})).all()
    comments = (await db.execute(text("""
        SELECT id, asset_id, cable_id, target_code, ST_X(geom) AS lng, ST_Y(geom) AS lat, body, author_id, created_at,
               resolved_at, resolved_by
        FROM approval_comments WHERE request_id = :r ORDER BY created_at
    """), {"r": r.id})).all()
    names = await _names(db, {r.submitted_by, *(s.decided_by for s in steps), *(c.author_id for c in comments),
                              *(c.resolved_by for c in comments)})
    pending = next((s for s in steps if s.status == "PENDING"), None)
    out = {
        "id": str(r.id), "subject_type": r.subject_type, "subject_id": str(r.subject_id), "revision": r.revision,
        "status": r.status, "note": r.note, "payload": r.payload, "submitted_by": names.get(r.submitted_by),
        "submitted_at": r.submitted_at.isoformat(), "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "steps": [{"step_no": s.step_no, "key": s.step_key, "label": s.label, "feature_key": s.feature_key,
                   "status": s.status, "decided_by": names.get(s.decided_by),
                   "decided_at": s.decided_at.isoformat() if s.decided_at else None, "comment": s.comment} for s in steps],
        "comments": [{"id": str(c.id), "asset_id": str(c.asset_id) if c.asset_id else None,
                      "cable_id": str(c.cable_id) if c.cable_id else None, "target_code": c.target_code,
                      "lng": c.lng, "lat": c.lat, "body": c.body, "author": names.get(c.author_id),
                      "created_at": c.created_at.isoformat(), "resolved": c.resolved_at is not None,
                      "resolved_by": names.get(c.resolved_by)} for c in comments],
        "pending_step": pending.step_key if pending else None,
    }
    if caller is not None:
        own = r.submitted_by == caller.id and (caller.role.level if getattr(caller, "role", None) else 1) < 5
        out["can_decide"] = bool(pending) and not own and await can(db, caller, pending.feature_key)
        out["can_withdraw"] = r.status == "PENDING" and r.submitted_by == caller.id
    return out


async def gate(db: AsyncSession, tid: uuid.UUID, design: Design) -> dict[str, Any]:
    """What deployment (Phase 10) needs, for the design's current version."""
    rows = (await db.execute(text("""
        SELECT subject_type, status FROM approval_requests
        WHERE design_id = :d AND tenant_id = :tid AND subject_id = :v ORDER BY revision DESC, submitted_at DESC
    """), {"d": design.id, "tid": tid, "v": design.current_version_id})).all()
    latest = {}
    for r in rows:
        latest.setdefault(r.subject_type, r.status)
    design_ok = design.status in ("APPROVED", "DEPLOYED") and latest.get("DESIGN_VERSION") == "APPROVED"
    boq_ok = latest.get("BOQ") == "APPROVED"
    reasons = []
    if not design_ok:
        reasons.append("The design version is not approved" + (" (it is under review)" if latest.get("DESIGN_VERSION") == "PENDING" else ""))
    if not boq_ok:
        reasons.append("Its BOQ is not approved" + (" (it is under review)" if latest.get("BOQ") == "PENDING" else ""))
    return {"design": latest.get("DESIGN_VERSION"), "boq": latest.get("BOQ"), "design_approved": design_ok,
            "boq_approved": boq_ok, "can_deploy": design_ok and boq_ok, "reasons": reasons}


async def list_for_design(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT * FROM approval_requests WHERE design_id = :d AND tenant_id = :tid
        ORDER BY submitted_at DESC, revision DESC
    """), {"d": design.id, "tid": tid})).all()
    return {"requests": [await request_out(db, r, caller) for r in rows], "gate": await gate(db, tid, design),
            "can_submit_design": design.status in SUBMITTABLE,
            "can_submit_boq": design.status == "APPROVED" and not any(
                r.subject_type == "BOQ" and r.status in ("PENDING", "APPROVED") and r.subject_id == design.current_version_id
                for r in rows)}


# ── Submitting ───────────────────────────────────────────────

async def _create(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, subject_type: str, subject_id: Any,
                  revision: int, note: str | None, payload: dict[str, Any], steps: tuple) -> Any:
    rid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO approval_requests (id, tenant_id, design_id, subject_type, subject_id, revision, note, payload, submitted_by)
        VALUES (:id, :tid, :d, :st, :sid, :rev, :note, CAST(:p AS jsonb), :by)
    """), {"id": rid, "tid": tid, "d": design.id, "st": subject_type, "sid": subject_id, "rev": revision,
           "note": (note or "").strip() or None, "p": json.dumps(payload, default=str), "by": caller.id})
    for i, (key, feature, label) in enumerate(steps, start=1):
        await db.execute(text("""
            INSERT INTO approval_steps (tenant_id, request_id, step_no, step_key, label, feature_key, status)
            VALUES (:tid, :r, :n, :k, :l, :f, :s)
        """), {"tid": tid, "r": rid, "n": i, "k": key, "l": label, "f": feature, "s": "PENDING" if i == 1 else "WAITING"})
    return (await db.execute(text("SELECT * FROM approval_requests WHERE id = :id"), {"id": rid})).one()


async def submit_design(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, note: str | None) -> dict[str, Any]:
    from app.modules.design import validation_service
    if design.status not in SUBMITTABLE:
        raise _bad(f"A design that is {design.status.replace('_', ' ').lower()} can't be submitted", status.HTTP_409_CONFLICT)
    size = (await db.execute(text("SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL"),
                             {"d": design.id})).scalar_one()
    if not size:
        raise _bad("There is nothing to review yet: the design has no devices")
    result = await validation_service.validate(db, tid, design)
    if result["summary"]["errors"]:
        n = result["summary"]["errors"]
        raise _bad(f"The design has {n} {'error' if n == 1 else 'errors'}; fix {'it' if n == 1 else 'them'} before submitting "
                   "(see Issues)")
    v = await versions.freeze(db, design)
    if v.label is None:
        v.label = "Submitted for review"
    req = await _create(db, tid, caller, design, "DESIGN_VERSION", v.id, v.version_no, note,
                        {"validation": result["summary"], "counts": v.snapshot_counts}, DESIGN_STEPS)
    design.status = "UNDER_REVIEW"
    design.updated_at = _now()
    await set_lifecycle(db, design.id, "UNDER_REVIEW")
    await db.flush()
    await audit.summary(db, tid, design.id, "submitted", caller, None, {"version_no": v.version_no, "note": note})
    await _notify(db, tid, await holders(db, tid, "design.review"), f"Design to review: {design.name}",
                  f"Version {v.version_no} of {design.name} waits for engineering review.", design, caller)
    return await request_out(db, req, caller)


async def submit_boq(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, note: str | None) -> dict[str, Any]:
    from app.modules.design import boq_service
    g = await gate(db, tid, design)
    if not g["design_approved"]:
        raise _bad("A BOQ can only be submitted for an approved design version", status.HTTP_409_CONFLICT)
    if g["boq"] in ("PENDING", "APPROVED"):
        raise _bad(f"This version's BOQ is already {g['boq'].lower()}", status.HTTP_409_CONFLICT)
    boq = await boq_service.compute_boq(db, tid, design)
    revision = (await db.execute(text("""
        SELECT coalesce(max(revision), 0) + 1 FROM approval_requests WHERE design_id = :d AND subject_type = 'BOQ'
    """), {"d": design.id})).scalar_one()
    version_no = (await versions.current(db, design)).version_no
    req = await _create(db, tid, caller, design, "BOQ", design.current_version_id, revision, note,
                        {"version_no": version_no, "quantities": boq["quantities"], "streets": boq["streets"],
                         "notes": boq["notes"], "frozen_at": _now().isoformat()}, BOQ_STEPS)
    await audit.summary(db, tid, design.id, "boq_submitted", caller, None, {"revision": revision, "version_no": version_no})
    await _notify(db, tid, await holders(db, tid, "boq.review"), f"BOQ to review: {design.name}",
                  f"BOQ revision {revision} of {design.name} (version {version_no}) waits for review.", design, caller)
    return await request_out(db, req, caller)


# ── Deciding ─────────────────────────────────────────────────

async def decide(db: AsyncSession, tid: uuid.UUID, caller: Any, request_id: str, decision: str,
                 comment: str | None) -> dict[str, Any]:
    r = await _request(db, tid, request_id)
    if r.status != "PENDING":
        raise _bad(f"This request is already {r.status.lower()}", status.HTTP_409_CONFLICT)
    step = (await db.execute(text("SELECT * FROM approval_steps WHERE request_id = :r AND status = 'PENDING'"),
                             {"r": r.id})).one()
    if not await can(db, caller, step.feature_key):
        raise _bad(f"{step.label} needs the '{step.feature_key}' permission", status.HTTP_403_FORBIDDEN)
    admin = (caller.role.level if getattr(caller, "role", None) else 1) >= 5
    if r.submitted_by == caller.id and not admin:
        raise _bad("You submitted this, so someone else has to decide it", status.HTTP_403_FORBIDDEN)
    decision = decision.upper()
    if decision not in ("APPROVE", "REJECT"):
        raise _bad("decision must be APPROVE or REJECT")
    comment = (comment or "").strip() or None
    if decision == "REJECT" and not comment:
        raise _bad("Say why it is sent back")

    design = await db.get(Design, r.design_id)
    await db.execute(text("""
        UPDATE approval_steps SET status = :s, decided_by = :by, decided_at = clock_timestamp(), comment = :c WHERE id = :id
    """), {"s": "APPROVED" if decision == "APPROVE" else "REJECTED", "by": caller.id, "c": comment, "id": step.id})
    what = "Design" if r.subject_type == "DESIGN_VERSION" else f"BOQ revision {r.revision}"

    if decision == "REJECT":
        await db.execute(text("UPDATE approval_steps SET status = 'CANCELLED' WHERE request_id = :r AND status = 'WAITING'"),
                         {"r": r.id})
        await db.execute(text("UPDATE approval_requests SET status = 'REJECTED', decided_at = clock_timestamp() WHERE id = :r"), {"r": r.id})
        if r.subject_type == "DESIGN_VERSION":
            # Back to revision in a NEW version: the reviewed one stays exactly as reviewed
            design.status = "REJECTED"
            await set_lifecycle(db, design.id, "DESIGNED")
            parent = await versions.current(db, design)
            await versions.start(db, tid, design, "MANUAL", None, parent, caller)
        await _notify(db, tid, [r.submitted_by], f"{what} sent back: {design.name}", f"{step.label}: {comment}", design, caller)
    else:
        nxt = (await db.execute(text("""
            SELECT * FROM approval_steps WHERE request_id = :r AND step_no = :n
        """), {"r": r.id, "n": step.step_no + 1})).first()
        if nxt is not None:
            await db.execute(text("UPDATE approval_steps SET status = 'PENDING' WHERE id = :id"), {"id": nxt.id})
            await db.execute(text("UPDATE approval_requests SET current_step = :n WHERE id = :r"), {"n": nxt.step_no, "r": r.id})
            await _notify(db, tid, await holders(db, tid, nxt.feature_key), f"{what} to approve: {design.name}",
                          f"{step.label} passed; it now waits for {nxt.label.lower()}.", design, caller)
        else:
            await db.execute(text("UPDATE approval_requests SET status = 'APPROVED', decided_at = clock_timestamp() WHERE id = :r"),
                             {"r": r.id})
            if r.subject_type == "DESIGN_VERSION":
                design.status = "APPROVED"
                await set_lifecycle(db, design.id, "APPROVED")
            await _notify(db, tid, [r.submitted_by], f"{what} approved: {design.name}",
                          f"{what} of {design.name} is approved.", design, caller)
    design.updated_at = _now()
    await db.flush()
    await audit.summary(db, tid, design.id, f"{'approved' if decision == 'APPROVE' else 'rejected'}_{step.step_key.lower()}",
                        caller, None, {"request": str(r.id), "subject": r.subject_type, "comment": comment})
    return await request_out(db, await _request(db, tid, str(r.id)), caller)


async def withdraw(db: AsyncSession, tid: uuid.UUID, caller: Any, request_id: str) -> dict[str, Any]:
    r = await _request(db, tid, request_id)
    if r.status != "PENDING":
        raise _bad(f"This request is already {r.status.lower()}", status.HTTP_409_CONFLICT)
    if r.submitted_by != caller.id:
        raise _bad("Only the person who submitted it can withdraw it", status.HTTP_403_FORBIDDEN)
    await db.execute(text("UPDATE approval_steps SET status = 'CANCELLED' WHERE request_id = :r AND status IN ('WAITING', 'PENDING')"),
                     {"r": r.id})
    await db.execute(text("UPDATE approval_requests SET status = 'WITHDRAWN', decided_at = clock_timestamp() WHERE id = :r"), {"r": r.id})
    design = await db.get(Design, r.design_id)
    if r.subject_type == "DESIGN_VERSION":
        design.status = "MODIFIED"
        await set_lifecycle(db, design.id, "DESIGNED")
        await versions.start(db, tid, design, "MANUAL", None, await versions.current(db, design), caller)
    await db.flush()
    await audit.summary(db, tid, design.id, "withdrawn", caller, None, {"request": str(r.id), "subject": r.subject_type})
    return await request_out(db, await _request(db, tid, str(r.id)), caller)


async def reopen(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design) -> dict[str, Any]:
    if design.status != "APPROVED":
        raise _bad("Only an approved design can be reopened", status.HTTP_409_CONFLICT)
    if (await db.execute(text("SELECT 1 FROM deployments WHERE design_id = :d AND status = 'IN_PROGRESS'"),
                         {"d": design.id})).first():
        raise _bad("This design is being deployed; it can't be reopened", status.HTTP_409_CONFLICT)
    design.status = "MODIFIED"
    await set_lifecycle(db, design.id, "DESIGNED")
    v = await versions.start(db, tid, design, "MANUAL", None, await versions.current(db, design), caller)
    await db.flush()
    await audit.summary(db, tid, design.id, "reopened", caller, None, {"version_no": v.version_no})
    return {"status": design.status, "version_no": v.version_no}


# ── Comments ─────────────────────────────────────────────────

async def add_comment(db: AsyncSession, tid: uuid.UUID, caller: Any, request_id: str, body: str,
                      asset_id: str | None, cable_id: str | None, lng: float | None, lat: float | None) -> dict[str, Any]:
    r = await _request(db, tid, request_id)
    body = (body or "").strip()
    if not body:
        raise _bad("Write the comment")
    code, geom = None, None
    if asset_id or cable_id:
        table = "net_assets" if asset_id else "net_cables"
        t = (await db.execute(text(f"""
            SELECT asset_code, ST_AsText(ST_PointOnSurface(geom)) AS p FROM {table} WHERE id = :id AND design_id = :d
        """), {"id": uuid.UUID(asset_id or cable_id), "d": r.design_id})).first()
        if t is None:
            raise _bad("That is not part of this design", status.HTTP_404_NOT_FOUND)
        code, geom = t.asset_code, t.p
    elif lng is not None and lat is not None:
        geom = f"POINT({float(lng)} {float(lat)})"
    await db.execute(text("""
        INSERT INTO approval_comments (tenant_id, request_id, design_id, asset_id, cable_id, target_code, geom, body, author_id)
        VALUES (:tid, :r, :d, :a, :c, :code, CASE WHEN CAST(:g AS text) IS NULL THEN NULL ELSE ST_GeomFromText(:g, 4326) END,
                :b, :by)
    """), {"tid": tid, "r": r.id, "d": r.design_id, "a": uuid.UUID(asset_id) if asset_id else None,
           "c": uuid.UUID(cable_id) if cable_id else None, "code": code, "g": geom, "b": body, "by": caller.id})
    design = await db.get(Design, r.design_id)
    await _notify(db, tid, [r.submitted_by], f"Review comment on {design.name}",
                  f"{code + ': ' if code else ''}{body[:160]}", design, caller)
    return await request_out(db, r, caller)


async def resolve_comment(db: AsyncSession, tid: uuid.UUID, caller: Any, comment_id: str, resolved: bool) -> dict[str, Any]:
    c = (await db.execute(text("SELECT request_id FROM approval_comments WHERE id = :id AND tenant_id = :tid"),
                          {"id": uuid.UUID(comment_id), "tid": tid})).first()
    if c is None:
        raise _bad("Comment not found", status.HTTP_404_NOT_FOUND)
    await db.execute(text("""
        UPDATE approval_comments SET resolved_at = CASE WHEN :res THEN now() END, resolved_by = CASE WHEN :res THEN CAST(:by AS uuid) END
        WHERE id = :id
    """), {"res": resolved, "by": str(caller.id), "id": uuid.UUID(comment_id)})
    return await request_out(db, await _request(db, tid, str(c.request_id)), caller)


# ── BOQ revision diff ────────────────────────────────────────

def _qmap(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f"{q['group']}|{q['item']}": q for q in payload.get("quantities") or []}


async def boq_diff(db: AsyncSession, tid: uuid.UUID, request_id: str) -> dict[str, Any]:
    """This BOQ revision's quantities against the previous revision's."""
    from app.modules.design.recalc import boq_delta
    r = await _request(db, tid, request_id)
    if r.subject_type != "BOQ":
        raise _bad("Only a BOQ has revisions to compare")
    prev = (await db.execute(text("""
        SELECT revision, payload FROM approval_requests
        WHERE design_id = :d AND subject_type = 'BOQ' AND revision < :rev ORDER BY revision DESC LIMIT 1
    """), {"d": r.design_id, "rev": r.revision})).first()
    return {"revision": r.revision, "previous_revision": prev.revision if prev else None,
            "quantities": r.payload.get("quantities") or [],
            "changes": boq_delta(_qmap(prev.payload), _qmap(r.payload)) if prev else []}
