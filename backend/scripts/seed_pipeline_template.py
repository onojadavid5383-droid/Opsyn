#!/usr/bin/env python3
# ============================================================
# OPSYN PIPELINE TEMPLATE SEED SCRIPT — scripts/seed_pipeline_template.py
# Creates the FTTx Customer Expansion pipeline template
# Usage: python -m scripts.seed_pipeline_template
# ============================================================

import asyncio
import uuid
from sqlalchemy import select

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import AsyncSessionLocal
from app.modules.projects.models import PipelineTemplate, PipelineTemplateStage
from app.modules.organisation.models import Department


async def seed_pipeline_template():
    async with AsyncSessionLocal() as db:
        # Check if template already exists
        existing = await db.execute(
            select(PipelineTemplate).where(PipelineTemplate.name == "FTTx Customer Expansion")
        )
        if existing.scalar_one_or_none():
            print("Pipeline template already exists")
            return

        # Get department IDs
        dept_names = [
            "Sales",
            "Finance",
            "Planning / FTTx Design",
            "Projects / Engineering",
            "Field Technicians",
            "CMP / Core Networking",
            "Onboarding"
        ]

        depts = await db.execute(
            select(Department).where(Department.name.in_(dept_names))
        )
        dept_map = {d.name: d.id for d in depts.scalars().all()}

        missing = [name for name in dept_names if name not in dept_map]
        if missing:
            print(f"Missing departments: {missing}")
            return

        # Create template
        template = PipelineTemplate(
            name="FTTx Customer Expansion",
            description="Standard pipeline for new FTTx customer connections requiring network expansion",
            is_active=True,
            created_by=uuid.uuid4()  # TODO: Use actual admin user ID
        )
        db.add(template)
        await db.flush()

        # Create stages
        stages_data = [
            {"order": 1, "name": "Sales Request", "dept": "Sales", "parallel": False, "gate": None},
            {"order": 2, "name": "Finance — Payment Confirmation", "dept": "Finance", "parallel": True, "gate": 3},
            {"order": 3, "name": "FTTx Network Design", "dept": "Planning / FTTx Design", "parallel": False, "gate": None},
            {"order": 4, "name": "Infrastructure Deployment", "dept": "Projects / Engineering", "parallel": False, "gate": None},
            {"order": 5, "name": "Customer Premises Connection", "dept": "Field Technicians", "parallel": False, "gate": None},
            {"order": 6, "name": "Core Network Integration", "dept": "CMP / Core Networking", "parallel": False, "gate": None},
            {"order": 7, "name": "Customer Onboarding", "dept": "Onboarding", "parallel": False, "gate": None},
        ]

        for stage_data in stages_data:
            stage = PipelineTemplateStage(
                template_id=template.id,
                stage_order=stage_data["order"],
                stage_name=stage_data["name"],
                department_id=dept_map[stage_data["dept"]],
                is_required=True,
                is_parallel=stage_data["parallel"],
                parallel_gate_stage_order=stage_data["gate"]
            )
            db.add(stage)

        await db.commit()
        print("Pipeline template seeded successfully")


if __name__ == "__main__":
    asyncio.run(seed_pipeline_template())