// ============================================================
// OPSYN NOTIFICATION STORE — Zustand
// Client-side cache for notifications + unread count
// Drives badge indicators and inbox page without re-fetching
// ============================================================

import { create } from 'zustand';
import type { Notification } from '@shared';

interface NotificationState {
  items:        Notification[];
  unreadCount:  number;

  // Bulk setter — called after React Query fetches the list
  setNotifications:      (items: Notification[]) => void;
  // Direct count setter — called after React Query fetches unread count
  setUnreadCount:        (count: number) => void;
  // Optimistic updates for instant UI feedback before server confirms
  markReadOptimistic:    (id: string) => void;
  markAllReadOptimistic: () => void;
  // Prepend a new item (for future real-time WebSocket delivery)
  addItem:               (item: Notification) => void;
  // Full reset on logout
  reset:                 () => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  items:       [],
  unreadCount: 0,

  setNotifications: (items) =>
    set({
      items,
      unreadCount: items.filter(n => !n.is_read).length,
    }),

  setUnreadCount: (count) =>
    set({ unreadCount: count }),

  markReadOptimistic: (id) =>
    set(s => {
      const wasUnread = s.items.find(n => n.id === id && !n.is_read);
      return {
        items:       s.items.map(n => n.id === id ? { ...n, is_read: true } : n),
        unreadCount: wasUnread ? Math.max(0, s.unreadCount - 1) : s.unreadCount,
      };
    }),

  markAllReadOptimistic: () =>
    set(s => ({
      items:       s.items.map(n => ({ ...n, is_read: true })),
      unreadCount: 0,
    })),

  addItem: (item) =>
    set(s => ({
      items:       [item, ...s.items],
      unreadCount: item.is_read ? s.unreadCount : s.unreadCount + 1,
    })),

  reset: () =>
    set({ items: [], unreadCount: 0 }),
}));

// ── Selectors ─────────────────────────────────────────────────
export const selectNotifications = (s: NotificationState) => s.items;
export const selectUnreadCount   = (s: NotificationState) => s.unreadCount;
