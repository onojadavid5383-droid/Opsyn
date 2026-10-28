// ============================================================
// OPSYN ACTIVITY TIMELINE — Types
// Blueprint Section 4 — unified immutable chronological feed
// ============================================================

export type TimelineEventType =
  | 'user_comment'
  | 'state_change'
  | 'stage_advance'
  | 'stage_pushback'
  | 'assignment_change'
  | 'block_reason'
  | 'approval_event'
  | 'pipeline_completion'
  | 'smartolt_event';

export type TimelineEntityType = 'task' | 'project' | 'outage' | 'onboarding';

export interface TimelineMention {
  user_id:  string;
  username: string;
}

export interface TimelineMeta {
  from_state?:    string;
  to_state?:      string;
  reason?:        string;
  stage_name?:    string;
  from_stage?:    string;
  to_stage?:      string;
  dept_name?:     string;
  field_name?:    string;
  old_value?:     string;
  new_value?:     string;
  outage_id?:     string;
  olt_reference?: string;
  actor_name?:    string;
  [key: string]:  unknown;
}

export interface TimelineEntry {
  id:          string;
  entity_type: TimelineEntityType;
  entity_id:   string;
  event_type:  TimelineEventType;
  actor_id?:   string | null;
  actor_label: string;
  body:        string;
  meta?:       TimelineMeta;
  parent_id?:  string | null;
  mentions?:   TimelineMention[];
  is_system:   boolean;
  created_at:  string;
  replies?:    TimelineEntry[];
}

export interface AddCommentPayload {
  body:      string;
  mentions?: string[];
  parent_id?: string;
}
