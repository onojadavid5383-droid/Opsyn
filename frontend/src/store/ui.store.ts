// ============================================================
// OPSYN UI STORE — Zustand
// Global UI state: sidebar, modals, toasts, theme
// ============================================================

import { create } from 'zustand';

export type SidebarKey = 'dashboard' | 'tasks' | 'staff' | 'intel' | 'settings';
export type ModalId = 'new-task' | 'task-detail' | 'quick' | 'new-outage' | 'new-project' | string;

export interface Toast {
  id:      string;
  type:    'success' | 'error' | 'info' | 'warning';
  title:   string;
  message?: string;
}

interface UIState {
  sidebarKey:    SidebarKey;
  activeTaskId:  string | null;
  openModals:    Set<ModalId>;
  toasts:        Toast[];
  taskViewMode:  'kanban' | 'gantt' | 'list' | 'calendar';

  setSidebarKey:   (key: SidebarKey) => void;
  setActiveTask:   (id: string | null) => void;
  openModal:       (id: ModalId) => void;
  closeModal:      (id: ModalId) => void;
  closeAllModals:  () => void;
  isModalOpen:     (id: ModalId) => boolean;
  addToast:        (toast: Omit<Toast, 'id'>) => void;
  removeToast:     (id: string) => void;
  setTaskView:     (mode: UIState['taskViewMode']) => void;
}

export const useUIStore = create<UIState>((set, get) => ({
  sidebarKey:   'dashboard',
  activeTaskId: null,
  openModals:   new Set(),
  toasts:       [],
  taskViewMode: 'kanban',

  setSidebarKey: key => set({ sidebarKey: key }),

  setActiveTask: id => set({ activeTaskId: id }),

  openModal: id => set(s => ({ openModals: new Set([...s.openModals, id]) })),

  closeModal: id => set(s => {
    const next = new Set(s.openModals);
    next.delete(id);
    return { openModals: next };
  }),

  closeAllModals: () => set({ openModals: new Set() }),

  isModalOpen: id => get().openModals.has(id),

  addToast: toast => {
    const id = Math.random().toString(36).slice(2);
    set(s => ({ toasts: [...s.toasts, { ...toast, id }] }));
    setTimeout(() => get().removeToast(id), 4500);
  },

  removeToast: id => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),

  setTaskView: mode => set({ taskViewMode: mode }),
}));
