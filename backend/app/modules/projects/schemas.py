# ============================================================
# OPSYN PROJECTS SCHEMAS — app/modules/projects/schemas.py
# Pydantic v2 request / response models
# ============================================================

from __future__ import annotations
import uuid
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime


# Pipeline Template schemas
class PipelineTemplateStageCreate(BaseModel):
    stage_order: int
    stage_name: str
    department_id: uuid.UUID
    is_required: bool = True
    is_parallel: bool = False
    parallel_gate_stage_order: Optional[int] = None
    expected_duration_days: Optional[int] = None


class PipelineTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    stages: List[PipelineTemplateStageCreate]


class PipelineTemplateStageResponse(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    stage_order: int
    stage_name: str
    department_id: uuid.UUID
    department_name: str
    is_required: bool
    is_parallel: bool
    parallel_gate_stage_order: Optional[int]
    expected_duration_days: Optional[int]

    model_config = {"from_attributes": True}


class PipelineTemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    is_active: bool
    stages: List[PipelineTemplateStageResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


# Pipeline Stage schemas
class ProjectPipelineStageResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    stage_order: int
    stage_name: str
    department_id: uuid.UUID
    department_name: str  # joined
    status: str
    assigned_to_user_id: Optional[uuid.UUID]
    entered_at: Optional[datetime]
    exited_at: Optional[datetime]
    pushed_back_reason: Optional[str]
    duration_days: Optional[float]  # computed: exited_at - entered_at
    comments: List["ProjectStageCommentResponse"]  # included in detail view

    model_config = {"from_attributes": True}


# Pipeline action schemas
class AdvanceStageRequest(BaseModel):
    comment: Optional[str] = None  # optional advance note


class PushBackRequest(BaseModel):
    reason: str  # REQUIRED — cannot push back without a reason
    comment: Optional[str] = None


# Stage comment schemas
class StageCommentCreate(BaseModel):
    body: str
    comment_type: str = "progress"  # progress | issue | approval_note | gate_confirmation


class ProjectStageCommentResponse(BaseModel):
    id: uuid.UUID
    stage_id: uuid.UUID
    author_user_id: uuid.UUID
    author_name: str  # joined
    body: str
    comment_type: str
    created_at: datetime

    model_config = {"from_attributes": True}


# Full pipeline view
class ProjectPipelineResponse(BaseModel):
    project_id: uuid.UUID
    project_name: str
    pipeline_template_id: Optional[uuid.UUID] = None
    pipeline_template_name: Optional[str] = None
    pipeline_status: str
    current_stage: Optional[ProjectPipelineStageResponse]
    all_stages: List[ProjectPipelineStageResponse]  # full history
    can_advance: bool   # computed for caller
    can_push_back: bool # computed for caller
    # Phase 4: approval gate and field completion state for current active stage
    current_stage_approval:    Optional[dict] = None
    stage_requires_approval:   bool = False
    missing_required_fields:   List[str] = []

    model_config = {"from_attributes": True}