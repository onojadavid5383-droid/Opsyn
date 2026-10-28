// ============================================================
// OPSYN WORKFLOW TYPES — src/types/workflow.types.ts
// Shared TypeScript types for the Workflow Builder feature
// ============================================================

export interface DeptWorkflow {
  id: string;
  name: string;
  description: string | null;
  triggerDeptId: string | null;
  triggerDeptName: string | null;
  isActive: boolean;
  isDraft: boolean;
  version: number;
  createdBy: string | null;
  publishedAt: string | null;
  createdAt: string;
  updatedAt: string;
  edgeCount?: number;
}

export interface WorkflowEdge {
  id: string;
  workflowId: string;
  fromDeptId: string | null;
  fromDeptName: string | null;
  toDeptId: string;
  toDeptName: string;
  edgeOrder: number;
  label: string | null;
  isParallel: boolean;
  parallelGroupId: string | null;
  gateRequiresGroup: string | null;
  canPushBack: boolean;
  expectedDays: number | null;
  createdAt: string;
}

export interface WorkflowGraph {
  workflow: DeptWorkflow;
  edges: WorkflowEdge[];
}

export interface WorkflowValidationResult {
  isValid: boolean;
  errors: string[];
}

export interface CreateWorkflowPayload {
  name: string;
  description?: string;
  trigger_dept_id?: string;
}

export interface AddEdgePayload {
  from_dept_id?: string | null;
  to_dept_id: string;
  edge_order: number;
  label?: string;
  is_parallel?: boolean;
  parallel_group_id?: string;
  gate_requires_group?: string;
  can_push_back?: boolean;
  expected_days?: number;
}

export interface UpdateEdgePayload {
  label?: string;
  is_parallel?: boolean;
  parallel_group_id?: string | null;
  gate_requires_group?: string | null;
  can_push_back?: boolean;
  expected_days?: number | null;
  edge_order?: number;
}
