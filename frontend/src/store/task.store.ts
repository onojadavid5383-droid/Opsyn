// ============================================================
// OPSYN TASK STORE — Zustand
// Task filter state & selected task management
// ============================================================

import { create } from 'zustand';
import type { TaskPriority, TaskStatus, DeadlineBucket } from '@shared';

export interface TaskFilters {
  search:          string;
  priority:        TaskPriority | '';
  status:          TaskStatus | '';
  deadline_bucket: DeadlineBucket | '';
  dept_id:         string;
  assignee_id:     string;
}

const DEFAULT_FILTERS: TaskFilters = {
  search:          '',
  priority:        '',
  status:          '',
  deadline_bucket: '',
  dept_id:         '',
  assignee_id:     '',
};

interface TaskState {
  selectedTaskId: string | null;
  filters:        TaskFilters;

  setSelectedTask: (id: string | null) => void;
  setFilters:      (patch: Partial<TaskFilters>) => void;
  clearFilters:    () => void;
}

export const useTaskStore = create<TaskState>((set) => ({
  selectedTaskId: null,
  filters:        { ...DEFAULT_FILTERS },

  setSelectedTask: (id) => set({ selectedTaskId: id }),

  setFilters: (patch) =>
    set((s) => ({ filters: { ...s.filters, ...patch } })),

  clearFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),
}));
