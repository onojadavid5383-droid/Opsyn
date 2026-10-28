// ============================================================
// OPSYN — Form Builder API client
// src/api/form-builder.api.ts
// Calls /api/v1/form-builder/* (Phase 3 & 4 backend)
//
// All responses are { success: boolean; data: T } — use .data.data
// ============================================================

import client from './client';

// ── Narrow APIResponse wrapper (matches backend envelope) ─────
type AR<T> = { success: boolean; data: T };

// ── Types ─────────────────────────────────────────────────────

export interface FieldTypeInfo {
  key:              string;
  label:            string;
  category:         string;
  has_options:      boolean;
  validation_rules: string[];
}

export interface FormSchema {
  id:              string;
  tenant_id:       string;
  name:            string;
  machine_name:    string;
  description:     string | null;
  module:          string;
  status:          'draft' | 'published' | 'archived';
  current_version: number;
  icon:            string | null;
  color:           string | null;
  created_by:      string | null;
  created_at:      string;
  updated_at:      string;
}

export interface FieldDefinition {
  id:                  string;
  schema_id:           string;
  tenant_id:           string;
  field_key:           string;
  label:               string;
  placeholder:         string | null;
  help_text:           string | null;
  field_type:          string;
  display_order:       number;
  is_required:         boolean;
  is_unique:           boolean;
  is_readonly:         boolean;
  is_hidden:           boolean;
  default_value:       unknown;
  validation_rules:    Record<string, unknown>;
  options:             string[] | null;
  conditional_logic:   unknown;
  role_visibility:     string[] | null;
  role_editable:       string[] | null;
  stage_visible_from:  number | null;
  stage_required_at:   number | null;
  department_owner:    string | null;
  width:               string;
  section_group:       string | null;
  schema_version_id:   string | null;
  created_by:          string | null;
  created_at:          string;
  updated_at:          string;
}

export interface FormSchemaVersion {
  id:             string;
  schema_id:      string;
  tenant_id:      string;
  version_number: number;
  published_at:   string | null;
  published_by:   string | null;
  field_snapshot: FieldDefinition[];
  changelog:      string | null;
  is_current:     boolean;
  created_at:     string;
}

// List endpoint returns data array at root level alongside pagination metadata
export interface SchemaListResult {
  schemas: FormSchema[];
  total:   number;
  page:    number;
  limit:   number;
}

// ── Submission types ──────────────────────────────────────────

export interface ValidationError {
  field_key:   string;
  field_label: string;
  error_code:  string;
  message:     string;
}

export interface ValidationWarning {
  field_key: string;
  message:   string;
}

export interface ValidationResult {
  is_valid:                boolean;
  errors:                  ValidationError[];
  warnings:                ValidationWarning[];
  missing_required_fields: string[];
  coerced_data:            Record<string, unknown>;
}

export interface FormSubmission {
  id:                string;
  tenant_id:         string;
  schema_id:         string;
  schema_version_id: string | null;
  entity_type:       string;
  entity_id:         string | null;
  association_id:    string | null;
  submitted_by:      string | null;
  submitted_at:      string;
  status:            'draft' | 'submitted' | 'approved' | 'rejected';
  data:              Record<string, unknown>;
  draft_data:        Record<string, unknown> | null;
  approved_by:       string | null;
  approved_at:       string | null;
  rejection_reason:  string | null;
  is_deleted:        boolean;
  created_at:        string;
  updated_at:        string;
}

export interface RendererConfig {
  schema:      FormSchema;
  version:     FormSchemaVersion | null;
  fields:      FieldDefinition[];
  field_types: FieldTypeInfo[];
}

export interface FormAssociation {
  id:                   string;
  tenant_id:            string;
  schema_id:            string;
  schema_version_id:    string | null;
  context_type:         string;
  context_id:           string | null;
  context_label:        string;
  is_mandatory:         boolean;
  display_order:        number;
  trigger_event:        string | null;
  auto_populate_fields: Record<string, unknown> | null;
  created_by:           string | null;
  created_at:           string;
  updated_at:           string;
}

export interface ContextSchema {
  association: FormAssociation;
  schema: {
    id:              string;
    name:            string;
    machine_name:    string;
    module:          string;
    status:          string;
    current_version: number;
    is_mandatory:    boolean;
    trigger_event:   string | null;
  };
}

// ── Dynamic schema migrations ─────────────────────────────────
//
// Runtime DDL. Nothing here is generated as an Alembic file: the backend
// executes the plan transactionally and records it in
// schema_migration_history. Preview persists the plan as `pending`; apply
// runs the SQL stored on that row, so what runs is what was reviewed.

/** Must match ck_schema_migration_history_status on the backend. */
export type MigrationStatus =
  | 'pending' | 'in_progress' | 'applied' | 'failed' | 'rolled_back';

export type MigrationChangeType =
  | 'create_table' | 'add_column' | 'alter_column'
  | 'drop_column' | 'add_index' | 'add_constraint';

export interface MigrationFieldChange {
  action:    'add' | 'modify' | 'delete';
  field_key: string;
  from_type: string | null;
  to_type:   string;
  options:   string[] | null;
  warning:   string | null;
}

/** List rows omit the SQL; only the detail endpoint returns it. */
export interface SchemaMigration {
  id:                     string;
  schema_id:              string;
  migration_name:         string;
  plan_hash:              string;
  change_type:            MigrationChangeType;
  status:                 MigrationStatus;
  table_name:             string | null;
  is_destructive:         boolean;
  field_changes:          MigrationFieldChange[];
  applied_by:             string | null;
  applied_at:             string | null;
  rolled_back_at:         string | null;
  error_message:          string | null;
  execution_duration_ms:  number | null;
  created_at:             string | null;
  /** Detail view only, and nullable: the backend withholds them from list
   *  responses, and a destructive plan can have no rollback SQL at all. */
  forward_sql?:           string | null;
  rollback_sql?:          string | null;
}

/** The preview response. Warnings must be shown, not swallowed. */
export interface MigrationPlan {
  migration_id:       string;
  schema_id:          string;
  migration_name:     string;
  change_type:        MigrationChangeType;
  table_name:         string;
  forward_sql:        string;
  rollback_sql:       string;
  field_changes:      MigrationFieldChange[];
  affected_rows:      number;
  estimated_duration: string;
  reversible:         boolean;
  is_destructive:     boolean;
  warnings:           string[];
}

export interface MigrationListResult {
  migrations: SchemaMigration[];
  total:      number;
  page:       number;
  limit:      number;
}

/**
 * The history endpoint's envelope: the page metadata sits alongside `data`,
 * not inside it, so it needs its own shape rather than `AR<T[]>`.
 */
type MigrationListEnvelope = AR<SchemaMigration[]> & {
  total: number;
  page:  number;
  limit: number;
};

export interface MigrationPreviewRequest {
  changes: Array<{
    action:       'add' | 'modify' | 'delete';
    field_id:     string;
    from_type?:   string;
    from_options?: string[];
  }>;
}

// ── API module ─────────────────────────────────────────────────

export const formBuilderApi = {

  // ── Dynamic schema migrations ────────────────────────────────

  /**
   * Plan field changes and persist the plan as `pending`.
   *
   * Nothing executes here. The response carries the exact forward and
   * rollback SQL plus any warnings, and its migration_id is what apply()
   * consumes.
   */
  previewMigration: (
    schemaId: string,
    body: MigrationPreviewRequest,
  ): Promise<MigrationPlan> =>
    client
      .post<AR<MigrationPlan>>(
        `/form-builder/schemas/${schemaId}/migrations/preview`,
        body,
      )
      .then(r => r.data.data),

  /** Execute a stored pending plan. Rejects 409 if already applied. */
  applyMigration: (migrationId: string): Promise<{
    migration_id:          string;
    table_name:            string;
    columns_added:         string[];
    execution_duration_ms: number;
    applied_at:            string | null;
  }> =>
    client
      .post<AR<{
        migration_id:          string;
        table_name:            string;
        columns_added:         string[];
        execution_duration_ms: number;
        applied_at:            string | null;
      }>>(`/form-builder/migrations/${migrationId}/apply`)
      .then(r => r.data.data),

  /**
   * Revert an applied migration.
   *
   * Refuses migrations flagged `is_destructive` at plan time: the rollback SQL
   * restores a column's shape but not the values that were in it. The UI hides
   * the action for those rows rather than offering one that must 400.
   */
  rollbackMigration: (migrationId: string): Promise<{
    migration_id:   string;
    rolled_back_at: string | null;
  }> =>
    client
      .post<AR<{ migration_id: string; rolled_back_at: string | null }>>(
        `/form-builder/migrations/${migrationId}/rollback`,
      )
      .then(r => r.data.data),

  getMigrations: (params: {
    schema_id: string;
    status?:   MigrationStatus;
    page?:     number;
    limit?:    number;
  }): Promise<MigrationListResult> =>
    client
      .get<MigrationListEnvelope>(
        `/form-builder/schemas/${params.schema_id}/migrations`,
        {
          params: {
            status: params.status || undefined,
            page:   params.page   ?? 1,
            limit:  params.limit  ?? 50,
          },
        },
      )
      .then(r => ({
        migrations: r.data.data ?? [],
        total:      r.data.total ?? 0,
        page:       r.data.page  ?? 1,
        limit:      r.data.limit ?? 50,
      })),

  /** Detail view, including the forward and rollback SQL. */
  getMigration: (migrationId: string): Promise<SchemaMigration> =>
    client
      .get<AR<SchemaMigration>>(`/form-builder/migrations/${migrationId}`)
      .then(r => r.data.data),

  // Field type catalogue (static, cache forever)
  getFieldTypes: (): Promise<FieldTypeInfo[]> =>
    client.get<AR<FieldTypeInfo[]>>('/form-builder/field-types')
      .then(r => r.data.data),

  // ── Schema CRUD ────────────────────────────────────────────

  getSchemas: (params?: {
    module?:  string;
    status?:  string;
    search?:  string;
    page?:    number;
    limit?:   number;
  }): Promise<SchemaListResult> =>
    client.get('/form-builder/schemas', { params })
      .then(r => ({
        schemas: (r.data.data   ?? []) as FormSchema[],
        total:   (r.data.total  ?? 0)  as number,
        page:    (r.data.page   ?? 1)  as number,
        limit:   (r.data.limit  ?? 20) as number,
      })),

  createSchema: (data: {
    name:         string;
    machine_name: string;
    module:       string;
    description?: string;
    icon?:        string;
    color?:       string;
  }): Promise<FormSchema> =>
    client.post<AR<FormSchema>>('/form-builder/schemas', data)
      .then(r => r.data.data),

  getSchema: (id: string): Promise<FormSchema> =>
    client.get<AR<FormSchema>>(`/form-builder/schemas/${id}`)
      .then(r => r.data.data),

  updateSchema: (
    id:   string,
    data: Partial<{ name: string; description: string; icon: string; color: string; module: string }>,
  ): Promise<FormSchema> =>
    client.put<AR<FormSchema>>(`/form-builder/schemas/${id}`, data)
      .then(r => r.data.data),

  deleteSchema: (id: string): Promise<void> =>
    client.delete(`/form-builder/schemas/${id}`).then(() => undefined),

  publishSchema: (id: string, changelog?: string): Promise<FormSchemaVersion> =>
    client.post<AR<FormSchemaVersion>>(
      `/form-builder/schemas/${id}/publish`,
      { changelog: changelog ?? null },
    ).then(r => r.data.data),

  archiveSchema: (id: string): Promise<FormSchema> =>
    client.post<AR<FormSchema>>(`/form-builder/schemas/${id}/archive`)
      .then(r => r.data.data),

  // ── Version history ────────────────────────────────────────

  getSchemaVersions: (id: string): Promise<FormSchemaVersion[]> =>
    client.get<AR<FormSchemaVersion[]>>(`/form-builder/schemas/${id}/versions`)
      .then(r => r.data.data),

  getSchemaVersion: (id: string, versionId: string): Promise<FormSchemaVersion> =>
    client.get<AR<FormSchemaVersion>>(
      `/form-builder/schemas/${id}/versions/${versionId}`,
    ).then(r => r.data.data),

  // ── Field CRUD ─────────────────────────────────────────────

  getFields: (schemaId: string): Promise<FieldDefinition[]> =>
    client.get<AR<FieldDefinition[]>>(
      `/form-builder/schemas/${schemaId}/fields`,
    ).then(r => r.data.data),

  createField: (
    schemaId: string,
    data: {
      field_key:   string;
      label:       string;
      field_type:  string;
      [k: string]: unknown;
    },
  ): Promise<FieldDefinition> =>
    client.post<AR<FieldDefinition>>(
      `/form-builder/schemas/${schemaId}/fields`, data,
    ).then(r => r.data.data),

  updateField: (
    schemaId: string,
    fieldId:  string,
    data: {
      label?:              string;
      placeholder?:        string | null;
      help_text?:          string | null;
      is_required?:        boolean;
      is_unique?:          boolean;
      is_readonly?:        boolean;
      is_hidden?:          boolean;
      default_value?:      string | null;
      validation_rules?:   Record<string, unknown>;
      options?:            string[];
      width?:              string;
      section_group?:      string | null;
      conditional_logic?:  unknown;
      role_visibility?:    string[];
      role_editable?:      string[];
      stage_visible_from?: number | null;
      stage_required_at?:  number | null;
    },
  ): Promise<FieldDefinition> =>
    client.put<AR<FieldDefinition>>(
      `/form-builder/schemas/${schemaId}/fields/${fieldId}`, data,
    ).then(r => r.data.data),

  deleteField: (schemaId: string, fieldId: string): Promise<void> =>
    client.delete(
      `/form-builder/schemas/${schemaId}/fields/${fieldId}`,
    ).then(() => undefined),

  // order = list of field UUIDs in the desired display order
  reorderFields: (schemaId: string, order: string[]): Promise<FieldDefinition[]> =>
    client.patch<AR<FieldDefinition[]>>(
      `/form-builder/schemas/${schemaId}/fields/reorder`, { order },
    ).then(r => r.data.data),

  // ── Renderer config ────────────────────────────────────────

  getRendererConfig: (schemaId: string): Promise<RendererConfig> =>
    client.get<AR<RendererConfig>>(
      `/form-builder/schemas/${schemaId}/renderer-config`,
    ).then(r => r.data.data),

  // ── Submissions ────────────────────────────────────────────

  validateSubmission: (data: {
    schema_id:             string;
    data:                  Record<string, unknown>;
    pipeline_stage_order?: number;
    is_draft?:             boolean;
  }): Promise<ValidationResult> =>
    client.post<AR<ValidationResult>>(
      '/form-builder/submissions/validate', data,
    ).then(r => r.data.data),

  saveDraft: (data: {
    schema_id:             string;
    entity_type:           string;
    entity_id?:            string;
    association_id?:       string;
    data:                  Record<string, unknown>;
    draft_id?:             string;
    pipeline_stage_order?: number;
  }): Promise<FormSubmission> =>
    client.post<AR<FormSubmission>>(
      '/form-builder/submissions/draft', data,
    ).then(r => r.data.data),

  getLatestDraft: (params: {
    schema_id: string; entity_type: string; entity_id?: string; association_id?: string;
  }): Promise<FormSubmission | null> =>
    client.get<AR<FormSubmission | null>>('/form-builder/submissions/draft/latest', { params })
      .then(r => r.data.data),

  submitForm: (data: {
    schema_id:             string;
    entity_type:           string;
    entity_id?:            string;
    association_id?:       string;
    data:                  Record<string, unknown>;
    draft_id?:             string;
    pipeline_stage_order?: number;
  }): Promise<FormSubmission> =>
    client.post<AR<FormSubmission>>(
      '/form-builder/submissions', data,
    ).then(r => r.data.data),

  getSubmissions: (params?: {
    schema_id?:   string;
    entity_type?: string;
    entity_id?:   string;
    status?:      string;
    page?:        number;
    limit?:       number;
  }): Promise<{ submissions: FormSubmission[]; total: number; page: number }> =>
    client.get('/form-builder/submissions', { params })
      .then(r => ({
        submissions: (r.data.data  ?? []) as FormSubmission[],
        total:       (r.data.total ?? 0)  as number,
        page:        (r.data.page  ?? 1)  as number,
      })),

  getSubmission: (id: string): Promise<FormSubmission> =>
    client.get<AR<FormSubmission>>(`/form-builder/submissions/${id}`)
      .then(r => r.data.data),

  approveSubmission: (id: string): Promise<FormSubmission> =>
    client.patch<AR<FormSubmission>>(`/form-builder/submissions/${id}/approve`)
      .then(r => r.data.data),

  rejectSubmission: (id: string, reason: string): Promise<FormSubmission> =>
    client.patch<AR<FormSubmission>>(
      `/form-builder/submissions/${id}/reject`, { reason },
    ).then(r => r.data.data),

  exportSubmission: (id: string): Promise<Blob> =>
    client.get(`/form-builder/submissions/${id}/export`, { responseType: 'blob' }).then(r => r.data),

  exportSubmissions: (schemaId: string): Promise<Blob> =>
    client.get('/form-builder/submissions/export', { params: { schema_id: schemaId }, responseType: 'blob' }).then(r => r.data),

  // ── Associations ───────────────────────────────────────────

  getAssociations: (params?: {
    schema_id?:    string;
    context_type?: string;
    page?:         number;
    limit?:        number;
  }): Promise<{ associations: FormAssociation[]; total: number; page: number }> =>
    client.get('/form-builder/associations', { params })
      .then(r => ({
        associations: (r.data.data  ?? []) as FormAssociation[],
        total:        (r.data.total ?? 0)  as number,
        page:         (r.data.page  ?? 1)  as number,
      })),

  createAssociation: (data: {
    schema_id:             string;
    context_type:          string;
    context_id?:           string;
    context_label:         string;
    is_mandatory?:         boolean;
    display_order?:        number;
    trigger_event?:        string | null;
    auto_populate_fields?: Record<string, unknown>;
  }): Promise<FormAssociation> =>
    client.post<AR<FormAssociation>>('/form-builder/associations', data)
      .then(r => r.data.data),

  updateAssociation: (
    id:   string,
    data: {
      context_label?:        string;
      is_mandatory?:         boolean;
      display_order?:        number;
      trigger_event?:        string | null;
      auto_populate_fields?: Record<string, unknown>;
    },
  ): Promise<FormAssociation> =>
    client.put<AR<FormAssociation>>(`/form-builder/associations/${id}`, data)
      .then(r => r.data.data),

  deleteAssociation: (id: string): Promise<void> =>
    client.delete(`/form-builder/associations/${id}`).then(() => undefined),

  // ── Context lookup ─────────────────────────────────────────

  getContextSchemas: (
    contextType: string,
    contextId:   string,
  ): Promise<ContextSchema[]> =>
    client.get<AR<ContextSchema[]>>(
      `/form-builder/context/${contextType}/${contextId}/schemas`,
    ).then(r => r.data.data),
};
