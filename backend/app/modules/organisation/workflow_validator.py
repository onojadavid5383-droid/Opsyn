# ============================================================
# OPSYN WORKFLOW VALIDATOR — app/modules/organisation/workflow_validator.py
# Pure Python — no DB access, no FastAPI imports.
# Graph validation for department workflow edge definitions.
# ============================================================
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict, deque
from typing import Optional


@dataclass
class EdgeData:
    from_dept_id:        Optional[str]  # None means entry-point edge
    to_dept_id:          str
    edge_order:          int
    parallel_group_id:   Optional[str]
    gate_requires_group: Optional[str]
    id:                  str


@dataclass
class WorkflowValidationResult:
    is_valid: bool
    errors:   list[str] = field(default_factory=list)


# ── Internal sentinel for the virtual "start" node ────────────────────────────
_START = "__START__"


def _graph_from_edges(edges: list[EdgeData]) -> dict[str, list[str]]:
    """
    Build an adjacency list.
    Edges whose from_dept_id is None originate from the _START sentinel.
    """
    graph: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        src = e.from_dept_id if e.from_dept_id is not None else _START
        graph[src].append(e.to_dept_id)
    return graph


# ── 1. Entry departments ──────────────────────────────────────────────────────
def find_entry_departments(edges: list[EdgeData]) -> list[str]:
    """
    Departments that are entry points: appear as to_dept_id on an edge where
    from_dept_id is None, OR never appear as from_dept_id at all.
    """
    from_set  = {e.from_dept_id for e in edges if e.from_dept_id is not None}
    to_set    = {e.to_dept_id for e in edges}

    # Explicit entry-point edges (from_dept_id is None)
    explicit_entries = {e.to_dept_id for e in edges if e.from_dept_id is None}

    # Departments that appear only as destinations (never as source)
    implicit_entries = to_set - from_set

    return list(explicit_entries | implicit_entries)


# ── 2. Terminal departments ───────────────────────────────────────────────────
def find_terminal_departments(edges: list[EdgeData]) -> list[str]:
    """
    Departments that appear only as from_dept_id (never as to_dept_id).
    These are sink nodes — nothing follows them.
    """
    from_set = {e.from_dept_id for e in edges if e.from_dept_id is not None}
    to_set   = {e.to_dept_id   for e in edges}
    return list(from_set - to_set)


# ── 3. Cycle detection ────────────────────────────────────────────────────────
def detect_cycle(edges: list[EdgeData]) -> bool:
    """
    DFS-based cycle detection on the directed graph.
    Returns True if a cycle exists.
    from_dept_id=None is treated as originating from the _START virtual node.
    """
    graph   = _graph_from_edges(edges)
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs(node: str) -> bool:
        visited.add(node)
        in_stack.add(node)
        for neighbour in graph.get(node, []):
            if neighbour not in visited:
                if _dfs(neighbour):
                    return True
            elif neighbour in in_stack:
                return True
        in_stack.discard(node)
        return False

    all_nodes: set[str] = {_START}
    for e in edges:
        if e.from_dept_id:
            all_nodes.add(e.from_dept_id)
        all_nodes.add(e.to_dept_id)

    for node in all_nodes:
        if node not in visited:
            if _dfs(node):
                return True
    return False


# ── 4. Reachability ───────────────────────────────────────────────────────────
def find_reachable_departments(
    edges: list[EdgeData], entry_dept_ids: list[str]
) -> set[str]:
    """
    BFS from all entry departments through the directed graph.
    Returns the set of all reachable department IDs (not including _START).
    """
    graph    = _graph_from_edges(edges)
    reachable: set[str] = set(entry_dept_ids)
    queue    = deque(entry_dept_ids)

    # Also seed from _START (entry-point edges whose from=None)
    for neighbour in graph.get(_START, []):
        if neighbour not in reachable:
            reachable.add(neighbour)
            queue.append(neighbour)

    while queue:
        current = queue.popleft()
        for neighbour in graph.get(current, []):
            if neighbour not in reachable:
                reachable.add(neighbour)
                queue.append(neighbour)

    return reachable


# ── 5. Parallel group validation ──────────────────────────────────────────────
def validate_parallel_groups(edges: list[EdgeData]) -> list[str]:
    """
    All edges sharing the same parallel_group_id must share the same from_dept_id.
    """
    errors: list[str] = []
    group_sources: dict[str, set[str | None]] = defaultdict(set)

    for e in edges:
        if e.parallel_group_id:
            group_sources[e.parallel_group_id].add(e.from_dept_id)

    for group_id, sources in group_sources.items():
        if len(sources) > 1:
            errors.append(
                f"Parallel group '{group_id}' has edges with different "
                f"from_dept_id values: {sources}. All must share the same source."
            )
    return errors


# ── 6. Gate reference validation ─────────────────────────────────────────────
def validate_gate_references(edges: list[EdgeData]) -> list[str]:
    """
    If gate_requires_group is set on an edge, that group must exist as a
    parallel_group_id elsewhere in the edge list.
    """
    errors: list[str] = []
    existing_groups = {e.parallel_group_id for e in edges if e.parallel_group_id}

    for e in edges:
        if e.gate_requires_group and e.gate_requires_group not in existing_groups:
            errors.append(
                f"Edge '{e.id}' references gate_requires_group "
                f"'{e.gate_requires_group}' which does not exist as a "
                f"parallel_group_id in this workflow."
            )
    return errors


# ── 7. Master validation ──────────────────────────────────────────────────────
def validate_workflow(edges: list[EdgeData]) -> WorkflowValidationResult:
    """
    Runs all validation rules and returns a WorkflowValidationResult.

    Rules:
      1. At least one entry-point edge (from_dept_id is None)
      2. At least one terminal node
      3. No cycles
      4. Parallel groups well-formed
      5. Gate references valid
      6. All departments reachable from entry points
      7. No duplicate (from_dept_id, to_dept_id) pairs
    """
    errors: list[str] = []

    # Rule 1 — at least one entry point
    entry_edges = [e for e in edges if e.from_dept_id is None]
    if not entry_edges:
        errors.append(
            "Rule 1: The workflow has no entry point. "
            "At least one edge must have from_dept_id=None."
        )

    # Rule 2 — at least one terminal node
    terminals = find_terminal_departments(edges)
    if not terminals:
        errors.append(
            "Rule 2: The workflow has no terminal node. "
            "At least one department must be a sink (never used as from_dept_id)."
        )

    # Rule 3 — no cycles
    if detect_cycle(edges):
        errors.append("Rule 3: The workflow graph contains a cycle.")

    # Rule 4 — parallel groups well-formed
    errors.extend(validate_parallel_groups(edges))

    # Rule 5 — gate references valid
    errors.extend(validate_gate_references(edges))

    # Rule 6 — all departments reachable from entry
    all_dept_ids: set[str] = set()
    for e in edges:
        if e.from_dept_id:
            all_dept_ids.add(e.from_dept_id)
        all_dept_ids.add(e.to_dept_id)

    entry_dept_ids = [e.to_dept_id for e in entry_edges]
    reachable      = find_reachable_departments(edges, entry_dept_ids)
    unreachable    = all_dept_ids - reachable
    if unreachable:
        errors.append(
            f"Rule 6: The following departments are not reachable from "
            f"entry points: {unreachable}."
        )

    # Rule 7 — no duplicate edges
    seen_pairs: set[tuple[str | None, str]] = set()
    for e in edges:
        pair = (e.from_dept_id, e.to_dept_id)
        if pair in seen_pairs:
            errors.append(
                f"Rule 7: Duplicate edge detected — "
                f"from_dept_id={e.from_dept_id!r} -> to_dept_id={e.to_dept_id!r}."
            )
        seen_pairs.add(pair)

    return WorkflowValidationResult(is_valid=len(errors) == 0, errors=errors)
