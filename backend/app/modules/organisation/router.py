# ============================================================
# OPSYN ORGANISATION MODULE — app/modules/organisation/router.py
# Standalone router for departments, teams, regions
# Imports service from all_modules to avoid circular deps
# ============================================================

from app.modules.all_modules import router_org as router

__all__ = ["router"]
