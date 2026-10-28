# OPSYN reports MODULE — router.py
# Mounted at /reports. Combines the legacy report endpoints (still defined in
# all_modules.py) with the Command Center trends endpoint.
from fastapi import APIRouter

from app.modules.all_modules import router_reports
from app.modules.reports.trends import router as trends_router

router = APIRouter()
router.include_router(router_reports)
router.include_router(trends_router)

__all__ = ["router"]
