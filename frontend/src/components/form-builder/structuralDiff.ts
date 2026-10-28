// ============================================================
// OPSYN — Structural change diff
// src/components/form-builder/structuralDiff.ts
//
// Compares a schema's live fields against the snapshot taken at its last
// publish, and reports the differences that need DDL.
//
// Only field_type and options are considered. Everything else the builder
// edits -- label, placeholder, help_text, is_required, visibility, width --
// lives in the metadata tables and needs no migration, so including them here
// would make cosmetic edits look like schema changes and push people to run
// pointless DDL.
// ============================================================

import type { FieldDefinition } from '../../api/form-builder.api';

export type StructuralAction = 'add' | 'modify' | 'delete';

export interface StructuralChange {
  action:     StructuralAction;
  field_id:   string;
  field_key:  string;
  label:      string;
  from_type?:   string;
  from_options?: string[];
}

function sameOptions(a: string[] | null, b: string[] | null): boolean {
  if (a === null || a === undefined) return b === null || b === undefined || b.length === 0;
  if (b === null || b === undefined) return a.length === 0;
  if (a.length !== b.length) return false;
  return a.every((v, i) => v === b[i]);
}

/**
 * Structural changes needed to bring `table` in line with `current` fields.
 *
 * `snapshot` is the last published version's field_snapshot, or null when the
 * schema has never been published. With no baseline every field is an add,
 * which is what the first publish implies.
 *
 * Deletions are matched by field id, not by key: deleting a field soft-deletes
 * the row but leaves its id, so the id recorded in the snapshot still resolves
 * and can be planned as a DROP COLUMN after the fact.
 */
export function diffStructuralChanges(
  current:  FieldDefinition[],
  snapshot: FieldDefinition[] | null | undefined,
): StructuralChange[] {
  const live = new Map(current.map(f => [f.id, f]));

  if (!snapshot || snapshot.length === 0) {
    return current.map(f => ({
      action:    'add',
      field_id:  f.id,
      field_key: f.field_key,
      label:     f.label,
    }));
  }

  const base = new Map(snapshot.map(f => [f.id, f]));
  const changes: StructuralChange[] = [];

  for (const field of current) {
    const before = base.get(field.id);
    if (!before) {
      changes.push({
        action:    'add',
        field_id:  field.id,
        field_key: field.field_key,
        label:     field.label,
      });
      continue;
    }
    const typeChanged = before.field_type !== field.field_type;
    const optionsChanged = !sameOptions(before.options, field.options);
    if (typeChanged || optionsChanged) {
      changes.push({
        action:       'modify',
        field_id:     field.id,
        field_key:    field.field_key,
        label:        field.label,
        from_type:    before.field_type,
        from_options: before.options ?? undefined,
      });
    }
  }

  for (const gone of snapshot) {
    if (!live.has(gone.id)) {
      changes.push({
        action:    'delete',
        field_id:  gone.id,
        field_key: gone.field_key,
        label:     gone.label,
      });
    }
  }

  return changes;
}

/** Shape the API's previewMigration endpoint expects. */
export function toPreviewRequest(changes: StructuralChange[]) {
  return {
    changes: changes.map(c => ({
      action:     c.action,
      field_id:   c.field_id,
      from_type:  c.from_type,
      from_options: c.from_options,
    })),
  };
}