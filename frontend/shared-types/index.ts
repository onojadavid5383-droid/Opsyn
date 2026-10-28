// ============================================================
// OPSYN SHARED TYPES — Frontend ↔ Backend Contract
// All API responses conform to these types
// ============================================================

// ── API Wrappers ────────────────────────────────────────────
export interface APIResponse<T> {
  data: T;
  message?: string;
  success: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  total_pages: number;
}

export interface ErrorDetail {
  field?: string;
  message: string;
  code: string;
}

export interface APIError {
  detail: ErrorDetail[] | string;
  status_code: number;
}

// ── Auth ────────────────────────────────────────────────────
export interface AuthUser {
  id: string;
  username: string;
  email: string;
  role: Role;
  role_level: number;
  is_active: boolean;
  staff_profile?: StaffProfileSummary;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// ── Roles & Permissions ─────────────────────────────────────
export interface Role {
  id: string;
  name: string;
  level: number;
  is_system_role: boolean;
  description?: string;
}

export type RoleName =
  | 'Admin'
  | 'Manager'
  | 'Team Lead'
  | 'NOC Operator'
  | 'MEC Reviewer'
  | 'Executive Viewer'
  | 'Staff';

export interface Permission {
  id: string;
  key: string;
  description?: string;
}

export interface UserScope {
  id: string;
  user_id: string;
  scope_type: 'department' | 'team' | 'region' | 'system';
  scope_reference_id: string;
  granted_by: string;
  created_at: string;
}

export interface UserRoleHistory {
  id: string;
  old_role?: Role;
  new_role: Role;
  changed_by: string;
  changed_at: string;
}

// ── Organisation ────────────────────────────────────────────
export interface Department {
  id: string;
  name: string;
  head_user_id?: string;
  parent_id?: string;
  staff_count?: number;
  team_count?: number;
}

export interface Team {
  id: string;
  name: string;
  department_id: string;
  department?: Department;
  lead_user_id?: string;
  member_count?: number;
}

export interface Region {
  id: string;
  name: string;
  code: string;
  parent_id?: string;
}

// ── Staff ────────────────────────────────────────────────────
export type StaffStatus = 'active' | 'inactive' | 'suspended' | 'on_leave';
export type EmploymentType = 'permanent' | 'contract' | 'intern';

export interface StaffProfileSummary {
  id: string;
  staff_code: string;
  first_name: string;
  last_name: string;
  full_name: string;
  job_title?: string;
}

export interface StaffProfile {
  id: string;
  user_id: string;
  staff_code: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone?: string;
  job_title?: string;
  skill_category?: string;
  specialization?: string;
  employment_type: EmploymentType;
  region?: Region;
  department: Department;
  team?: Team;
  manager?: StaffProfileSummary;
  approval_authority_level: number;
  olt_domain?: string;
  work_location?: string;
  outage_responsibility?: string;
  mec_responsibility?: string;
  status: StaffStatus;
  notes?: string;
  joined_at?: string;
  end_date?: string;
  created_at: string;
  updated_at: string;
  // Joined from users
  username: string;
  email: string;
  role: Role;
  last_login_at?: string;
  scopes?: UserScope[];
  role_history?: UserRoleHistory[];
}

export interface CreateStaffRequest {
  // Tab 1: Basic Info
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
  username: string;
  staff_code?: string;
  invite_method: 'email' | 'password';
  temporary_password?: string;
  // Tab 2: Organisation
  department_id: string;
  team_id?: string;
  manager_user_id?: string;
  role_id: string;
  job_title?: string;   // Optional[str] = None on the backend
  employment_type: EmploymentType;
  // Tab 3: Access
  permission_profile?: string;
  scope_level: 'department' | 'team' | 'region' | 'system';
  allowed_dashboards: string[];
  // Tab 4: Operational
  region_id?: string;
  olt_domain?: string;
  project_unit?: string;
  outage_responsibility?: string;
  mec_responsibility?: string;
  approval_authority_level: number;
  work_location?: string;
  specialization?: string;
  notes?: string;
  // Tab 5: Status
  status: StaffStatus;
  joined_at?: string;
  end_date?: string;
}

// ── Tasks ────────────────────────────────────────────────────
export type TaskPriority = 'critical' | 'high' | 'medium' | 'low';
export type TaskStatus =
  | 'new' | 'assigned' | 'in_progress' | 'review' | 'blocked' | 'done' | 'archived';
export type DeadlineBucket =
  | 'pending_approval' | 'completed' | 'overdue' | 'today' | 'this_week' | 'next_week' | 'no_deadline' | 'backlog';
export type CommentType = 'NORMAL' | 'SYSTEM' | 'ACTION' | 'APPROVAL' | 'BLOCKER';
export type ApprovalAction = 'approved' | 'rejected' | 'pending';

export interface TaskDependency {
  id: string;
  task_id: string;
  depends_on_task_id: string;
  depends_on_task?: { id: string; title: string; status: TaskStatus; assignee?: StaffProfileSummary };
  created_at: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  priority: TaskPriority;
  status: TaskStatus;
  previous_state?: string;
  state_changed_at?: string;
  deadline?: string;
  deadline_bucket: DeadlineBucket;
  pipeline_id?: string;
  stage_id?: string;
  department?: Department;
  department_id?: string;
  project_id?: string;
  assignee_user_id?: string;
  assignee?: StaffProfileSummary;
  responsible_user?: StaffProfileSummary;
  created_by: string;
  tags: string[];
  comment_count: number;
  dependencies?: TaskDependency[];
  ticket_number?: string;
  block_reason?: string;
  estimated_hours?: number;
  created_at: string;
  updated_at: string;
}

export interface TaskComment {
  id: string;
  task_id: string;
  author: StaffProfileSummary;
  body: string;
  type: CommentType;
  mentions: string[];
  parent_id?: string;
  replies?: TaskComment[];
  approval_action?: ApprovalAction;
  is_resolved?: boolean;
  created_at: string;
  updated_at?: string;
}

export interface AddCommentRequest {
  body: string;
  type?: CommentType;
  mentions?: string[];
  parent_id?: string;
}

export interface TransitionRequest {
  to_status: TaskStatus;
  to_stage_id?: string;
  comment?: AddCommentRequest;
}

export interface TaskBoard {
  pending_approval: Task[];
  completed: Task[];
  overdue: Task[];
  today: Task[];
  this_week: Task[];
  next_week: Task[];
  no_deadline: Task[];
  backlog: Task[];
  total: number;
}

export interface TaskStatusBoard {
  new: Task[];
  assigned: Task[];
  in_progress: Task[];
  review: Task[];
  blocked: Task[];
  done: Task[];
  archived: Task[];
  total: number;
}

export interface CreateTaskRequest {
  title: string;
  description?: string;
  priority: TaskPriority;
  status?: TaskStatus;
  deadline?: string;
  department_id?: string;
  project_id?: string;
  assignee_user_id?: string;
  responsible_user_id?: string;
  pipeline_id?: string;
  stage_id?: string;
  dependent_task_ids?: string[];
  tags?: string[];
  estimated_hours?: number;
  task_scope?: 'internal' | 'external';
  source_app?: string;
  archive_refs?: string[];
}

// ── Projects ─────────────────────────────────────────────────
export type ProjectStatus = 'active' | 'completed' | 'paused';
export type ProjectType =
  | 'internal' | 'external' | 'cable_upgrade' | 'olt_installation' | 'procurement'
  | 'infrastructure' | 'software' | 'operations' | 'security';

export interface Project {
  id: string;
  name: string;
  description?: string;
  status: ProjectStatus;
  project_type: ProjectType;
  ticket_number?: string;
  owner_id?: string;
  department_id?: string;
  department?: Department;
  completion_pct: number;
  due_date?: string;
  pipeline_status?: string;
  current_stage_id?: string;
  members?: StaffProfileSummary[];
  task_count?: number;
  completed_task_count?: number;
  created_at: string;
}

// Pipeline types
export interface PipelineTemplateStage {
  id: string;
  templateId: string;
  stageOrder: number;
  stageName: string;
  departmentId: string;
  departmentName: string;
  isRequired: boolean;
  isParallel: boolean;
  parallelGateStageOrder: number | null;
  expectedDurationDays: number | null;
}

export interface PipelineTemplate {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  stages: PipelineTemplateStage[];
  createdAt: string;
}

export type PipelineStageStatus =
  | 'pending'
  | 'active'
  | 'approved'
  | 'pushed_back'
  | 'skipped'
  | 'gate_waiting';

export type PipelineStatus =
  | 'not_started'
  | 'active'
  | 'stalled'
  | 'completed'
  | 'cancelled';

export interface StageComment {
  id: string;
  stageId: string;
  authorUserId: string;
  authorName: string;
  body: string;
  commentType: 'progress' | 'issue' | 'note' | 'approval_note' | 'pushback_reason' | 'gate_confirmation';
  createdAt: string;
  attachments?: Array<{ filename: string; url?: string }>;
}

export interface ProjectPipelineStage {
  id: string;
  projectId: string;
  stageOrder: number;
  stageName: string;
  departmentId: string;
  departmentName: string;
  status: PipelineStageStatus;
  assignedToUserId: string | null;
  enteredAt: string | null;
  exitedAt: string | null;
  pushedBackReason: string | null;
  durationDays: number | null;
  comments: StageComment[];
}

export interface ProjectPipelineResponse {
  projectId: string;
  projectName: string;
  pipelineTemplateId: string;
  pipelineTemplateName: string;
  pipelineStatus: PipelineStatus;
  currentStage: ProjectPipelineStage | null;
  allStages: ProjectPipelineStage[];
  canAdvance: boolean;
  canPushBack: boolean;
}

// ── Outage ────────────────────────────────────────────────────
export type OutageSeverity = 'critical' | 'high' | 'warning' | 'low';
export type OutageStatus = 'active' | 'monitoring' | 'in_resolution' | 'resolved';

export interface OutageIncident {
  id: string;
  reference: string;
  title: string;
  description?: string;
  severity: OutageSeverity;
  status: OutageStatus;
  olt_reference?: string;
  /** Flat id -- the API does not embed the region object. */
  region_id?: string | null;
  source?: string;
  affected_subscribers?: number;
  sla_deadline?: string | null;
  breached_sla?: boolean;
  linked_task_id?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

// ── Onboarding ────────────────────────────────────────────────
export type ApprovalStatus = 'pending' | 'approved' | 'rejected';

export interface OnboardingRequest {
  id: string;
  requested_by: StaffProfileSummary;
  proposed_first_name: string;
  proposed_last_name: string;
  proposed_email: string;
  proposed_role: Role;
  department: Department;
  team?: Team;
  justification?: string;
  approval_status: ApprovalStatus;
  approved_by?: StaffProfileSummary;
  approved_at?: string;
  provisioned_user_id?: string;
  created_at: string;
}

// ── Notifications ─────────────────────────────────────────────
export type NotificationType =
  | 'onboarding_pending'
  | 'onboarding_approved'
  | 'onboarding_rejected'
  | 'outage_critical'
  | 'outage_warning'
  | 'outage_resolved'
  | 'role_changed'
  | 'staff_created'
  | 'staff_deactivated'
  | 'task_assigned'
  | 'task_overdue';

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  body?: string;
  is_read: boolean;
  action_url?: string;
  created_at: string;
}

// ── Audit ─────────────────────────────────────────────────────
export interface AuditLog {
  id: string;
  actor: StaffProfileSummary;
  action: string;
  target_type: string;
  target_id?: string;
  before_state?: Record<string, unknown>;
  after_state?: Record<string, unknown>;
  ip_address?: string;
  created_at: string;
}

// ── Forms ─────────────────────────────────────────────────────
export type FormFieldType =
  | 'text' | 'textarea' | 'number' | 'dropdown'
  | 'date' | 'phone' | 'email' | 'boolean' | 'file' | 'coordinates';

export type FormContext = 'lead' | 'task' | 'project' | 'onboarding';

export type DependencyOperator = 'eq' | 'neq' | 'gt' | 'lt' | 'contains' | 'is_empty' | 'is_not_empty';
export type DependencyAction  = 'show' | 'hide' | 'require';

export interface FormFieldDependency {
  id:                 string;
  source_field_key:   string;
  target_field_key:   string;
  condition_operator: DependencyOperator;
  condition_value:    string | null;
  action:             DependencyAction;
}

export interface FormField {
  id:               string;
  field_key:        string;
  field_type:       FormFieldType;
  label:            string;
  placeholder?:     string;
  help_text?:       string;
  required:         boolean;
  field_order:      number;
  options?:         Array<{ label: string; value: string }> | null;
  validation_rules?: Record<string, unknown> | null;
  created_at:       string;
}

export interface FormSchema {
  id:           string;
  context:      FormContext;
  version:      number;
  is_published: boolean;
  title:        string;
  description?: string;
  created_by?:  string;
  created_at:   string;
  updated_at:   string;
  fields:       FormField[];
  dependencies: FormFieldDependency[];
}

export interface FormSubmission {
  id:             string;
  schema_id:      string;
  submitted_by?:  string;
  submitted_data: Record<string, unknown>;
  submitted_at:   string;
}

export type FormData = Record<string, unknown>;

// ── Reports ───────────────────────────────────────────────────
export interface ReportSummary {
  staff_added: number;
  staff_departed: number;
  staff_total: number;
  staff_active: number;
  outages_resolved: number;
  avg_mttr_hours: number;
  tasks_completed: number;
  task_completion_rate: number;
  dept_breakdown: { department: string; count: number }[];
  monthly_staff_changes: { month: string; added: number; departed: number }[];
  monthly_mttr: { month: string; hours: number }[];
}


// ============================================================
// MERGED FROM THE FORMER ROOT shared-types/index.ts
//
// The repository previously carried two divergent copies of this
// contract. The root copy was orphaned -- nothing imported it --
// but it held the only definitions for the Infrastructure, Shift,
// SmartOLT, Automation and Pipeline types below. They are merged
// here verbatim; no pre-existing definition in this file was
// changed. The root copy has been deleted.
// ============================================================

export type TaskTriggerType = 'manual' | 'automation' | 'comment' | 'system' | 'dependency';

// ── Pipelines & Stages ─────────────────────────────────────────
export interface Pipeline {
  id: string;
  name: string;
  description?: string;
  stages: Stage[];
  department_id?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Stage {
  id: string;
  pipeline_id: string;
  name: string;
  order: number;
  allowed_statuses: TaskStatus[];
  is_terminal: boolean;
  is_entry: boolean;
  created_at: string;
}

// ── Task Dependency & Summary ──────────────────────────────────
export interface TaskSummary {
  id: string;
  title: string;
  status: TaskStatus;
  assignee?: StaffProfileSummary;
}

// ── Automation ────────────────────────────────────────────────
export type AutomationTrigger =
  | 'status_changed'
  | 'deadline_passed'
  | 'dependency_completed'
  | 'comment_added'
  | 'sla_breached';

export type AutomationAction =
  | 'move_to_status'
  | 'move_to_pipeline'
  | 'move_to_stage'
  | 'assign_user'
  | 'notify_user'
  | 'add_system_comment';

export interface AutomationCondition {
  field: string;
  operator: 'eq' | 'neq' | 'lt' | 'gt' | 'contains' | 'is_empty';
  value: unknown;
}

export interface AutomationRule {
  id: string;
  name: string;
  description?: string;
  pipeline_id?: string;
  trigger: AutomationTrigger;
  conditions: AutomationCondition[];
  action: AutomationAction;
  action_params: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

// ── Task Audit ────────────────────────────────────────────────
export interface TaskAuditEntry {
  id: string;
  task_id: string;
  actor?: StaffProfileSummary;
  from_status?: TaskStatus;
  to_status?: TaskStatus;
  from_pipeline_id?: string;
  to_pipeline_id?: string;
  from_stage_id?: string;
  to_stage_id?: string;
  trigger_type: TaskTriggerType;
  comment_id?: string;
  note?: string;
  created_at: string;
}

export interface OutageTimelineEntry {
  id: string;
  event_type: string;
  actor_id?: string;
  body: string;
  meta?: Record<string, unknown>;
  created_at: string;
}

export interface SmartOLTConfig {
  id: string;
  api_url: string;
  polling_enabled: boolean;
  polling_interval_secs: number;
  severity_thresholds?: { warning: number; high: number; critical: number };
  has_api_key: boolean;
  has_webhook_secret: boolean;
  updated_at?: string;
}

export interface SmartOLTOltMap {
  id: string;
  smartolt_olt_id: string;
  olt_name?: string;
  region_id?: string;
  latitude?: number;
  longitude?: number;
  is_active: boolean;
  last_synced_at?: string;
}

// ── Infrastructure (S4.1) ──────────────────────────────────────
export interface InfraPort {
  id: string;
  node_id: string;
  port_number: string;
  port_type: string;
  total_capacity: number;
  used_capacity: number;
  utilisation_pct: number;
  status: 'active' | 'down' | string;
  last_synced_at?: string;
  created_at: string;
}

export interface InfraSubscriber {
  id: string;
  customer_id: string;
  site_id?: string;
  node_id?: string;
  port_id?: string;
  service_type: string;
  status: 'active' | 'suspended' | 'churned' | string;
  address?: string;
  latitude?: number;
  longitude?: number;
}

export interface InfraCapacityAlert {
  id: string;
  site_id?: string;
  node_id?: string;
  alert_type: string;
  severity: 'critical' | 'high' | 'warning' | 'low';
  threshold_pct: number;
  current_pct: number;
  message?: string;
  is_resolved: boolean;
  resolved_at?: string;
  linked_task_id?: string;
  created_at: string;
}

export interface InfraMonitoringConfig {
  id: string;
  entity_type: string;
  entity_id: string;
  warn_threshold_pct: number;
  critical_threshold_pct: number;
  check_interval_minutes: number;
  alert_channels: string[];
  assigned_role_level: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface InfraAlertRule {
  id: string;
  name: string;
  condition_field: string;
  operator: 'gt' | 'lt' | 'gte' | 'lte' | 'eq';
  threshold_value: number;
  severity: 'critical' | 'high' | 'warning' | 'low';
  action_type: 'notify' | 'create_task' | 'email' | string;
  action_params: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
}

export interface InfraMapSite {
  id: string;
  name: string;
  site_type: string;
  latitude?: number;
  longitude?: number;
  status: string;
  region_id?: string;
  is_monitored: boolean;
  has_alert: boolean;
}

export interface InfraMapNode {
  id: string;
  name: string;
  node_type: string;
  site_id?: string;
  ip_address?: string;
  status: string;
  utilisation: { used: number; total: number; pct: number };
  has_alert: boolean;
}

export interface InfraMapRoute {
  id: string;
  from_node_id: string;
  to_node_id: string;
  cable_type?: string;
  status: string;
  length_km?: number;
  capacity_gbps?: number;
}

export interface InfraMapCabinet {
  id: string;
  cabinet_id: string;
  latitude: number;
  longitude: number;
  capacity: number;
  number_tray?: number;
  custom_data?: Record<string, unknown>;
}

export interface InfraMapOLT {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  location_description?: string;
  number_of_odf?: number;
  custom_data?: Record<string, unknown>;
}

export interface InfraMapSplitter {
  id: string;
  box_id: string;
  latitude: number;
  longitude: number;
  splitter_level: string;
  splitter_type: string;
  input_ports: number;
  output_ports: number;
  number_customer?: number;
  /** Topology for path trace — upstream splitter and cabinet (null if not linked) */
  parent_splitter_id?: string | null;
  cabinet_id?: string | null;
  custom_data?: Record<string, unknown>;
}

export interface InfraMapData {
  sites: InfraMapSite[];
  nodes: InfraMapNode[];
  routes: InfraMapRoute[];
  cabinets: InfraMapCabinet[];
  olts: InfraMapOLT[];
  splitters: InfraMapSplitter[];
}

export interface InfraUtilisationPoint {
  site_id: string;
  name: string;
  latitude?: number;
  longitude?: number;
  used: number;
  total: number;
  utilisation_pct: number;
}

// ── Shifts ─────────────────────────────────────────────────────
export interface Shift {
  id: string;
  name: string;
  shift_type: 'day' | 'night' | 'oncall' | string;
  start_time: string;
  end_time: string;
  color: string;
  created_at?: string;
}

export interface ShiftAssignment {
  id: string;
  shift_id: string;
  user_id: string;
  date: string;
  status: 'scheduled' | 'confirmed' | 'cancelled' | 'swapped';
  notes?: string;
  shift?: Shift;
  user?: { id: string; name: string; email: string };
  created_at?: string;
}

export interface ShiftSwapRequest {
  id: string;
  from_assignment_id: string;
  to_user_id: string;
  reason?: string;
  status: 'pending' | 'approved' | 'rejected';
  responded_by?: string;
  responded_at?: string;
  created_at?: string;
}

// ── Outage Notification Rules ──────────────────────────────────
export interface OutageNotificationRule {
  id: string;
  name: string;
  min_severity: 'critical' | 'high' | 'warning' | 'low';
  min_subscribers: number;
  channels: ('sms' | 'email' | 'whatsapp')[];
  message_template?: string;
  is_auto: boolean;
  is_active: boolean;
  created_at?: string;
}

// ── Command Center trends (GET /reports/trends) ────────────────
export type TrendMetric =
  | 'outages_opened' | 'outages_resolved' | 'mttr_hours'
  | 'tasks_created'  | 'tasks_completed'  | 'customers_added'
  | 'node_availability_pct' | 'port_utilisation_pct';

export type TrendBucket = 'hour' | 'day' | 'week';

export interface TrendPoint {
  /** Bucket start, ISO 8601 UTC */
  t: string;
  /** null = no data for this bucket (ratios/averages); counts are zero-filled */
  value: number | null;
}

export interface TrendSeries {
  metric:   TrendMetric;
  unit:     'count' | 'hours' | 'percent';
  bucket:   TrendBucket;
  days:     number;
  points:   TrendPoint[];
  /** false when the window holds no real data — render an empty state, not a flat line */
  has_data: boolean;
  /** Present for outages_opened: per-severity counts aligned to `points` */
  breakdown_by?: 'severity';
  breakdown?:    Record<string, number[]>;
}

// ── Network GIS (Phase 1) ──────────────────────────────────────
// Mirrors backend app/modules/network/{lifecycle,asset_types,schemas}.py
// and app/modules/gis/layer_registry.py field for field. Change both sides
// together. Geometry is GeoJSON in EPSG:4326, coordinates [lng, lat].

export type NetLifecycleStatus =
  | 'DRAFT' | 'PLANNED' | 'DESIGNED' | 'UNDER_REVIEW' | 'APPROVED'
  | 'CONSTRUCTION' | 'INSTALLED' | 'TESTING' | 'VERIFIED'
  | 'ACTIVE' | 'FAULTY' | 'RETIRED' | 'REJECTED';

export type NetAssetType =
  | 'POP' | 'SITE' | 'OLT' | 'ROOM' | 'RACK' | 'ROUTER' | 'SWITCH' | 'WDM' | 'ODF'
  | 'CABINET' | 'FDT' | 'FAT' | 'SPLITTER' | 'CLOSURE' | 'ENCLOSURE'
  | 'POLE' | 'MANHOLE' | 'HANDHOLE'
  | 'ONU' | 'CUSTOMER_ENDPOINT';

export type NetCableCategory =
  | 'FEEDER' | 'PICKUP' | 'CLOSURE_FDT' | 'DISTRIBUTION' | 'BOX_TO_BOX' | 'DROP' | 'INTERNAL';

export type NetTier = 'core' | 'distribution' | 'civil' | 'customer';
export type NetCreationMethod = 'AUTO' | 'MANUAL' | 'IMPORTED' | 'FIELD';

/** GET /network/search, GET /network/assets items */
export interface NetAssetSummary {
  id:               string;
  asset_code:       string;
  asset_type:       NetAssetType;
  name:             string | null;
  lifecycle_status: NetLifecycleStatus;
  lng:              number;
  lat:              number;
}

export interface NetAssetRef {
  id:         string;
  asset_code: string;
  asset_type: NetAssetType;
  name:       string | null;
}

/** GET/PATCH/POST /network/assets/{id} */
export interface NetAsset {
  id:                  string;
  asset_code:          string;
  asset_type:          NetAssetType;
  name:                string | null;
  description:         string | null;
  lifecycle_status:    NetLifecycleStatus;
  creation_method:     NetCreationMethod;
  geometry:            { type: 'Point'; coordinates: [number, number] } | { type: string; coordinates: unknown };
  lng:                 number;
  lat:                 number;
  attributes:          Record<string, unknown>;
  capacity:            number | null;
  used_capacity:       number | null;
  parent:              NetAssetRef | null;
  children_count:      number;
  project_id:          string | null;
  design_id:           string | null;
  lineage_id:          string;
  source_table:        string | null;
  allowed_transitions: NetLifecycleStatus[];
  created_at:          string;
  updated_at:          string;
}

export interface NetAssetPage {
  items:       NetAssetSummary[];
  total:       number;
  page:        number;
  size:        number;
  total_pages: number;
}

/** POST /network/assets/sync-uploaded */
export interface NetBackfillResult {
  mirrored: Record<'olts' | 'cabinets' | 'splitter_boxes', number>;
  skipped:  { source_table: string; asset_code: string }[];
}

export interface GisLayer {
  key:          NetAssetType | NetCableCategory;
  label:        string;
  kind:         'asset' | 'cable';
  tier:         NetTier | 'cables';
  min_zoom:     number;
  count:        number;
  source_layer: string;
}

export interface GisLayerGroup {
  key:    NetTier | 'cables';
  label:  string;
  kind:   'asset' | 'cable';
  layers: GisLayer[];
}

/** GET /gis/layers */
export interface GisLayerRegistry {
  /** Changes on every live-network write; part of the tile URL */
  revision: string;
  tiles: {
    group:         string;
    /** Relative to the API base URL */
    url_template:  string;
    min_zoom:      number;
    max_zoom:      number;
    source_layers: { assets: string; cables: string };
  };
  contained_min_zoom: number;
  live_states:        NetLifecycleStatus[];
  lifecycle_states:   NetLifecycleStatus[];
  groups:             GisLayerGroup[];
}

/** GET /gis/bounds — bbox is [minLng, minLat, maxLng, maxLat], null when empty */
export interface GisBounds {
  bbox:          [number, number, number, number] | null;
  feature_count: number;
}

// ── Network GIS (Phase 2) — catalogue, cables, uploads ─────────
// Mirrors app/modules/network/{catalogue,attributes,schemas}.py and
// GET /infrastructure/upload-types.

export type NetFieldKind = 'text' | 'int' | 'number' | 'bool' | 'enum';

export interface NetFieldSpec {
  key:     string;
  label:   string;
  kind:    NetFieldKind;
  unit:    string | null;
  options: string[];
  min:     number | null;
  help:    string | null;
}

export interface NetCatalogueAssetType {
  code:           NetAssetType;
  label:          string;
  tier:           NetTier;
  min_zoom:       number;
  code_prefix:    string;
  code_example:   string;
  /** What `capacity` counts for this type; null = not used */
  capacity_label: string | null;
  attributes:     NetFieldSpec[];
}

export interface NetCatalogueCableCategory {
  code:         NetCableCategory;
  label:        string;
  min_zoom:     number;
  code_prefix:  string;
  code_example: string;
  attributes:   NetFieldSpec[];
}

export type NetRouteMethod = 'ROAD_GRAPH' | 'MANUAL_GEOMETRY' | 'IMPORTED' | 'DIRECT';

/** GET /network/catalogue */
export interface NetCatalogue {
  tiers:              { key: NetTier; label: string }[];
  asset_types:        NetCatalogueAssetType[];
  cable_categories:   NetCatalogueCableCategory[];
  lifecycle_states:   NetLifecycleStatus[];
  live_states:        NetLifecycleStatus[];
  transitions:        Record<NetLifecycleStatus, NetLifecycleStatus[]>;
  creation_methods:   NetCreationMethod[];
  route_methods:      NetRouteMethod[];
  installation_types: string[];
  connection_types:   NetConnectionType[];
  fiber_statuses:     NetFibreStatus[];
  utilisation_thresholds: { warning: number; critical: number };
}

/** GET /network/cables items */
export interface NetCableSummary {
  id:               string;
  asset_code:       string;
  cable_category:   NetCableCategory;
  name:             string | null;
  lifecycle_status: NetLifecycleStatus;
  length_m:         number | null;
  fiber_count:      number | null;
}

/** GET/PATCH /network/cables/{id} */
export interface NetCable {
  id:                  string;
  asset_code:          string;
  cable_category:      NetCableCategory;
  name:                string | null;
  description:         string | null;
  lifecycle_status:    NetLifecycleStatus;
  creation_method:     NetCreationMethod;
  route_method:        NetRouteMethod;
  installation_type:   string | null;
  fiber_count:         number | null;
  /** Metres, computed by the database from the geometry */
  length_m:            number | null;
  geometry:            { type: 'LineString'; coordinates: [number, number][] };
  midpoint:            [number, number];
  /** [minLng, minLat, maxLng, maxLat] */
  bbox:                [number, number, number, number];
  source:              NetAssetRef | null;
  dest:                NetAssetRef | null;
  attributes:          Record<string, unknown>;
  project_id:          string | null;
  design_id:           string | null;
  lineage_id:          string;
  source_table:        string | null;
  allowed_transitions: NetLifecycleStatus[];
  created_at:          string;
  updated_at:          string;
}

export interface NetCablePage {
  items:       NetCableSummary[];
  total:       number;
  page:        number;
  size:        number;
  total_pages: number;
}

/** GET /infrastructure/upload-types */
export interface UploadTypeSpec {
  key:              string;
  label:            string;
  description:      string;
  /** register = the original OLT / cabinet / splitter tables; network = net_* */
  group:            'register' | 'network';
  kind:             'asset' | 'cable';
  asset_type:       string | null;
  formats:          ('xlsx' | 'geojson')[];
  required_columns: string[];
  optional_columns: string[];
  geojson_geometry: 'Point' | 'LineString' | null;
}

// ── Network GIS (Phase 3) — topology, trace, utilisation, fibres ─
// Mirrors app/modules/network/{schemas,topology}.py.

export type NetConnectionType = 'FEED' | 'SPLIT' | 'SPLICE' | 'PATCH' | 'DROP' | 'UPLINK';

export interface NetCableRef {
  id:             string;
  asset_code:     string;
  cable_category: NetCableCategory;
  length_m:       number | null;
}

/** One side of an asset's connections; `peer` is the asset at the other end. */
export interface NetConnection {
  id:               string;
  connection_type:  NetConnectionType;
  lifecycle_status: NetLifecycleStatus;
  /** Where a derived link comes from ('net_cables', 'attr:…'); null = made by hand */
  derived_from:     string | null;
  peer:             NetAssetRef;
  via_cable:        NetCableRef | null;
}

/** GET /network/assets/{id}/connections — upstream feeds this asset, downstream is fed by it */
export interface NetAssetConnections {
  upstream:   NetConnection[];
  downstream: NetConnection[];
}

export interface NetTraceAsset {
  id:               string;
  asset_code:       string;
  asset_type:       NetAssetType;
  name:             string | null;
  lifecycle_status: NetLifecycleStatus;
  lng:              number;
  lat:              number;
}

export interface NetTraceHop {
  asset:           NetTraceAsset;
  depth:           number;
  from_id:         string | null;
  connection_type: NetConnectionType | null;
  via_cable:       NetCableRef | null;
}

export type NetTraceDirection = 'upstream' | 'downstream';

/** GET /network/assets/{id}/trace */
export interface NetTrace {
  direction:      NetTraceDirection;
  start_id:       string;
  hops:           NetTraceHop[];
  /** upstream: asset ids start → root along one path; downstream: [] */
  path_ids:       string[];
  root:           NetTraceAsset | null;
  reached_root:   boolean;
  path_length_m:  number | null;
  counts_by_type: Partial<Record<NetAssetType, number>>;
  customers:      number;
  truncated:      boolean;
  geometry:       { type: 'FeatureCollection'; features: unknown[] };
}

export type NetUtilisationState = 'ok' | 'warning' | 'critical' | 'full' | 'unknown';
export type NetUtilisationBasis = 'ports' | 'fat_ports' | 'connections' | 'recorded' | 'none';

/** GET /network/assets/{id}/utilisation */
export interface NetUtilisation {
  capacity:       number | null;
  used:           number | null;
  available:      number | null;
  pct:            number | null;
  state:          NetUtilisationState;
  basis:          NetUtilisationBasis;
  capacity_label: string | null;
}

export type NetFibreStatus = 'FREE' | 'USED' | 'RESERVED' | 'FAULTY' | 'DARK';

/** GET /network/cables/{id}/fibers (TIA-598 colours) */
export interface NetFibre {
  fiber_no:        number;
  tube_no:         number;
  position:        number;
  colour:          string;
  colour_hex:      string;
  tube_colour:     string;
  tube_colour_hex: string;
  status:          NetFibreStatus;
  recorded:        boolean;
}

// ── Network GIS (Phase 4) — designs ────────────────────────────
// Mirrors app/modules/design/{schemas,service,boq_service,validation_service}.py.

export type DesignStatus =
  | 'DRAFT' | 'GENERATED' | 'MODIFIED' | 'VALIDATING' | 'UNDER_REVIEW' | 'APPROVED'
  | 'REJECTED' | 'SUPERSEDED' | 'DEPLOYED';

export type DesignInputLayerKey = 'road' | 'homepass' | 'pole' | 'building' | 'pickup' | 'existing_structure';

export interface DesignVersionRef {
  id:              string;
  version_no:      number;
  label:           string | null;
  creation_method: string;
  created_at:      string;
}

/** GET /designs/{id}, GET /projects/{id}/designs items */
export interface Design {
  id:              string;
  project_id:      string;
  project_name:    string | null;
  name:            string;
  description:     string | null;
  status:          DesignStatus;
  boundary:        { type: 'MultiPolygon'; coordinates: unknown } | null;
  /** [minLng, minLat, maxLng, maxLat] of boundary, inputs and working set */
  bbox:            [number, number, number, number] | null;
  engine_config:   Record<string, unknown>;
  current_version: DesignVersionRef | null;
  input_counts:    Record<DesignInputLayerKey, number>;
  created_at:      string;
  updated_at:      string;
}

/** GET /designs/{id}/inputs items */
export interface DesignInputLayer {
  layer_key:     DesignInputLayerKey;
  label:         string;
  feature_count: number;
  last_upload:   { filename: string | null; uploaded_at: string; mode: 'replace' | 'append'; feature_count: number } | null;
}

/** POST /designs/{id}/inputs/{layer} — nothing is written when rejected */
export interface DesignInputUploadResult {
  status:        'saved' | 'rejected';
  layer_key:     DesignInputLayerKey;
  feature_count: number;
  errors:        { row: number; field: string; error: string }[];
  warnings:      string[];
  upload_id:     string | null;
}

/** GET /designs/{id}/summary */
export interface DesignSummary {
  homepasses:   number;
  customers:    number;
  fdt:          number;
  fat:          number;
  splitters:    number;
  closures:     number;
  poles:        number;
  cable_km:     number;
  errors:       number;
  warnings:     number;
  validated_at: string | null;
}

export interface DesignBoqQuantity {
  group:        'Devices' | 'Cable';
  item:         string;
  code:         string;
  quantity:     number;
  unit:         'each' | 'm';
  pieces?:      number;
  fiber_count?: number | null;
}

/** GET /designs/{id}/boq — streets are the FTTx engine's own BOQ rows */
export interface DesignBoq {
  quantities:           DesignBoqQuantity[];
  streets:              Record<string, string | number | null>[];
  street_boq_available: boolean;
  notes:                string[];
  engine_findings:      { severity: string; category: string; message: string }[];
}

export type DesignIssueSeverity = 'ERROR' | 'WARNING' | 'INFO';

export interface DesignIssue {
  id:         string;
  severity:   DesignIssueSeverity;
  code:       string;
  rule:       string | null;
  message:    string;
  asset_id:   string | null;
  cable_id:   string | null;
  geometry:   { type: string; coordinates: unknown } | null;
  metadata:   Record<string, unknown>;
  created_at: string;
}

/** POST /designs/{id}/validate, GET /designs/{id}/validation */
export interface DesignValidation {
  issues:  DesignIssue[];
  summary: { errors: number; warnings: number; info: number; validated_at?: string };
  /** Phase 5: the FTTx engine's own findings, for an auto-designed version */
  engine_findings?: { severity: string; category: string; message: string }[];
}

/** POST /designs/{id}/route */
export interface DesignRoute {
  geometry:        { type: 'LineString'; coordinates: [number, number][] };
  length_m:        number;
  straight_line_m: number;
  route_method:    'ROAD_GRAPH';
  from_code:       string | null;
  to_code:         string | null;
}

// ── Network GIS (Phase 5) — auto design ───────────────────────
// Mirrors app/modules/design/auto_design.py.

export type DesignRunStatus = 'draft' | 'layers_pending' | 'ready' | 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';

/** result_summary.design once a run's output is in the design */
export interface DesignRunApplied {
  version_no: number;
  counts:     Record<string, number>;
  warnings:   string[];
  validation: { errors: number; warnings: number; info: number; validated_at?: string };
}

/** GET /designs/{id}/generate/status (null: never run); POST …/generate adds notes */
export interface DesignGenerateStatus {
  run_id:           string;
  status:           DesignRunStatus;
  progress_pct:     number;
  progress_message: string | null;
  error_message:    string | null;
  result_summary:   (Record<string, unknown> & { design?: DesignRunApplied; fdt_count?: number; fat_count?: number }) | null;
  design_version:   { id: string; version_no: number } | null;
  created_at:       string | null;
  started_at:       string | null;
  completed_at:     string | null;
  /** Only on POST: what the input adapter left out or added */
  notes?:           string[];
}

/** GET /designs/{id}/importable-runs */
export interface ImportableRun {
  id:                string;
  name:              string | null;
  completed_at:      string | null;
  from_this_design:  boolean;
  fdt_count:         number | null;
  fat_count:         number | null;
  homepass_count:    number | null;
  deployment_type:   string | null;
  pon_architecture:  string | null;
}

/** POST /designs/{id}/import-run */
export interface DesignImportResult extends DesignRunApplied {
  inputs_copied: string[];
}

/** The engine's own findings from the run that produced the current version */
export interface EngineFinding { severity: string; category: string; message: string }

// ── Network GIS (Phase 6) — manual design ─────────────────────
// Mirrors app/modules/design/{operations,snap}.py.

export type DesignOpKind =
  | 'ADD_ASSET' | 'MOVE_ASSET' | 'DELETE_ASSET' | 'UPDATE_ATTRS' | 'DRAW_CABLE' | 'DELETE_CABLE'
  | 'EDIT_CABLE_GEOM' | 'SPLIT_CABLE' | 'EXTEND_CABLE' | 'CONNECT' | 'DISCONNECT';

/** One end of a drawn / extended cable */
export type DesignCableEnd = { asset_id: string } | { lng: number; lat: number };

/** POST /designs/{id}/operations — op plus its own fields (see operations.py) */
export type DesignOperationBody = { op: DesignOpKind } & Record<string, unknown>;

export interface DesignOpHistory {
  can_undo:   boolean;
  can_redo:   boolean;
  undo_label: string | null;
  redo_label: string | null;
  applied:    number;
}

/** A cable recalculated after its device moved (Phase 7) */
export interface DesignRerouted {
  id: string; code: string; category: string; route_method: string; before_m: number; after_m: number; note?: string;
}

/** A BOQ line an edit changed (Phase 7) */
export interface DesignBoqChange {
  item: string; code: string; unit: 'each' | 'm'; group: 'Devices' | 'Cable'; before: number; after: number; change: number;
}

/** What an edit changed: the client patches its cache from this (Phase 7) */
export interface DesignDelta {
  boq:      DesignBoqChange[];
  issues:   { new: { severity: string; code: string; message: string }[]; resolved: { severity: string; code: string; message: string }[] };
  features: GeoJSON.Feature[];
  removed:  { assets: string[]; cables: string[] };
}

/** Every operation, undo and redo answers with this */
export interface DesignOpResult {
  operation: { seq: number; op: DesignOpKind; label: string; asset_id?: string | null; cable_id?: string;
               asset_code?: string; length_m?: number; route_method?: string; cables_followed?: number; removed_cables?: number;
               rerouted?: DesignRerouted[] };
  history:    DesignOpHistory;
  summary:    DesignSummary;
  validation: { errors: number; warnings: number; info: number; validated_at?: string };
  delta:      DesignDelta;
}

/** GET /designs/{id}/operations */
export interface DesignOpLog extends DesignOpHistory {
  operations: { seq: number; op: DesignOpKind; label: string; created_at: string; undone: boolean }[];
}

export type DesignSnapKind = 'asset' | 'pole_input' | 'homepass' | 'pickup' | 'live_asset' | 'vertex' | 'road' | 'boundary';

export interface DesignSnapCandidate {
  kind: DesignSnapKind; id: string; code: string; sub: string; lng: number; lat: number; distance_m: number;
}

/** POST /designs/{id}/snap */
export type DesignSnap =
  | ({ snapped: true; candidates: DesignSnapCandidate[] } & DesignSnapCandidate)
  | { snapped: false; lng: number; lat: number; kind: null; candidates: [] };

// ── Network GIS (Phase 8) — versions and audit ───────────────
// Mirrors app/modules/design/{versions,audit}.py.

/** GET /designs/{id}/versions items (newest first) */
export interface DesignVersionInfo {
  id:                string;
  version_no:        number;
  label:             string | null;
  creation_method:   'INITIAL' | 'AUTO' | 'MANUAL' | 'IMPORTED' | 'RESTORED';
  created_at:        string;
  created_by:        string | null;
  is_current:        boolean;
  /** Frozen = its snapshot is kept; it never changes again */
  frozen:            boolean;
  frozen_at:         string | null;
  parent_version_id: string | null;
  counts:            (Record<string, number> & { assets?: number; cables?: number; inputs?: number; cable_m?: number }) | null;
  validation:        { errors?: number; warnings?: number; validated_at?: string } | null;
}

export interface DesignMove { kind: 'asset'; code: string; type: string; id: string; from: [number, number]; to: [number, number]; distance_m: number }

export interface DesignChange {
  kind: 'asset' | 'cable'; code: string; id: string; fields: string[];
  before: Record<string, unknown>; after: Record<string, unknown>;
  length_before_m?: number | null; length_after_m?: number | null; geometry_before?: GeoJSON.Geometry;
}

/** GET /designs/{id}/compare?from=&to= */
export interface DesignCompare {
  from: number; to: number;
  added: GeoJSON.Feature[]; removed: GeoJSON.Feature[]; moved: DesignMove[]; changed: DesignChange[];
  counts: { added: number; removed: number; moved: number; changed: number };
}

/** POST /designs/{id}/versions/{no}/restore */
export interface DesignRestoreResult {
  version_no: number; restored_from: number; kept_as: number | null; inputs_restored: boolean;
  validation: { errors: number; warnings: number; info: number };
}

/** One entry of the network audit trail (network_audit_log + infrastructure_audit_log) */
export interface AuditEntry {
  id: string; entity_type: string; entity_id: string | null; entity_code: string | null; action: string;
  actor: string; occurred_at: string; changed_fields: string[];
  old: Record<string, unknown> | null; new: Record<string, unknown> | null; source: 'network' | 'infrastructure';
}

// ── Network GIS (Phase 9) — design and BOQ approval ──────────
// Mirrors app/modules/approval/service.py.

export type ApprovalSubject = 'DESIGN_VERSION' | 'BOQ';
export type DesignApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'WITHDRAWN';

export interface ApprovalStep {
  step_no: number; key: string; label: string; feature_key: string;
  status: 'WAITING' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED';
  decided_by: string | null; decided_at: string | null; comment: string | null;
}

export interface ApprovalComment {
  id: string; asset_id: string | null; cable_id: string | null; target_code: string | null;
  lng: number | null; lat: number | null; body: string; author: string | null; created_at: string;
  resolved: boolean; resolved_by: string | null;
}

export interface ApprovalRequest {
  id: string; subject_type: ApprovalSubject; subject_id: string; revision: number; status: DesignApprovalStatus;
  note: string | null; submitted_by: string | null; submitted_at: string; decided_at: string | null;
  /** Design: the validation summary and counts at submission. BOQ: the frozen quantities and street rows */
  payload: Record<string, unknown> & { quantities?: DesignBoqQuantity[]; version_no?: number;
                                       validation?: { errors: number; warnings: number } };
  steps: ApprovalStep[]; comments: ApprovalComment[]; pending_step: string | null;
  can_decide?: boolean; can_withdraw?: boolean;
}

/** What deployment (Phase 10) needs, for the current version */
export interface ApprovalGate {
  design: DesignApprovalStatus | null; boq: DesignApprovalStatus | null;
  design_approved: boolean; boq_approved: boolean; can_deploy: boolean; reasons: string[];
}

/** GET /designs/{id}/approvals */
export interface ApprovalOverview {
  requests: ApprovalRequest[]; gate: ApprovalGate; can_submit_design: boolean; can_submit_boq: boolean;
}

/** GET /approvals/{id}/boq-diff */
export interface BoqDiff {
  revision: number; previous_revision: number | null; quantities: DesignBoqQuantity[]; changes: DesignBoqChange[];
}

// ── Deployment (Network GIS Phase 10) ────────────────────────

export type DeploymentAction = 'install' | 'test' | 'verify' | 'fail';
export interface DeploymentItem { kind: 'asset' | 'cable'; id: string }

export interface DeploymentRecord {
  status: 'IN_PROGRESS' | 'PROMOTED'; started_at: string; note: string | null; promoted_at: string | null;
  summary: { assets: number; cables: number; cable_m: number; version_no: number } | null;
}

/** Design length vs as-built (cables), or how far a device moved from its designed spot */
export interface DeploymentVariance {
  kind: 'asset' | 'cable'; id: string; code: string;
  design_m: number | null; asbuilt_m: number | null; moved_m: number | null;
  difference_m?: number; difference_pct?: number;
}

/** GET /designs/{id}/deployment */
export interface DeploymentProgress {
  deployment: DeploymentRecord | null;
  gate: ApprovalGate;
  items: number; states: Partial<Record<NetLifecycleStatus, number>>;
  installed: number; verified: number; installed_pct: number; verified_pct: number;
  fats: { total: number; installed: number; verified: number };
  cable_m: { planned: number; installed: number };
  per_fdt: { fdt: string; state: NetLifecycleStatus; fats: number; installed: number; verified: number }[];
  variance: DeploymentVariance[];
  ready_to_promote: boolean; not_verified: number;
}

/** POST /designs/{id}/deployment/progress */
export interface DeploymentAdvanceResult {
  changed: { code: string; from: NetLifecycleStatus; to: NetLifecycleStatus }[];
  refused: { code: string; state: NetLifecycleStatus; reason: string }[];
  progress: DeploymentProgress;
}

/** POST /designs/{id}/promote */
export interface PromoteResult {
  promoted: { assets: number; cables: number; cable_m: number; version_no: number };
  design_status: DesignStatus;
}
