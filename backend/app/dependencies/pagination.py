# ============================================================
# OPSYN PAGINATION DEPENDENCY — app/dependencies/pagination.py
# Reusable pagination, filter, and sort parameters
# ============================================================

from fastapi import Query
from typing import Literal


class PaginationParams:
    """
    FastAPI dependency for standard pagination parameters.
    Usage: params: PaginationParams = Depends(PaginationParams)
    """
    def __init__(
        self,
        page: int  = Query(1,    ge=1,        description="Page number (1-indexed)"),
        size: int  = Query(20,   ge=1, le=200, description="Items per page"),
        sort: str  = Query("created_at",       description="Sort field"),
        order: Literal["asc", "desc"] = Query("desc", description="Sort direction"),
    ):
        self.page  = page
        self.size  = size
        self.sort  = sort
        self.order = order

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class CommonFilters:
    """
    FastAPI dependency for common cross-domain filters.
    Usage: filters: CommonFilters = Depends(CommonFilters)
    """
    def __init__(
        self,
        dept_id:   str | None = Query(None, description="Filter by department ID"),
        role_id:   str | None = Query(None, description="Filter by role ID"),
        status:    str | None = Query(None, description="Filter by status"),
        region_id: str | None = Query(None, description="Filter by region ID"),
        search:    str | None = Query(None, description="Full-text search term"),
    ):
        self.dept_id   = dept_id
        self.role_id   = role_id
        self.status    = status
        self.region_id = region_id
        self.search    = search


def paginate_response(items: list, total: int, params: PaginationParams) -> dict:
    """Build a standard paginated response envelope."""
    return {
        "items":       items,
        "total":       total,
        "page":        params.page,
        "size":        params.size,
        "total_pages": max(1, -(-total // params.size)),
    }


__all__ = ["PaginationParams", "CommonFilters", "paginate_response"]
