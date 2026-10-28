// ============================================================
// OPSYN — src/__tests__/DeptInboxPage.test.tsx   (I.2.2)
// Component tests for DeptInboxPage
// Run: npm test
// ============================================================

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import DeptInboxPage from '../pages/tasks/DeptInboxPage';

// ── Mocks ─────────────────────────────────────────────────────
// IMPORTANT: vi.mock factories are hoisted — do NOT reference module-scope
// const declarations inside them. Inline all mock data.

vi.mock('../api/tasks.api', () => ({
  tasksApi: {
    getDeptInbox: vi.fn().mockResolvedValue({
      items: [
        {
          id:             'task-1',
          title:          'Investigate fiber cut in Zone 4',
          ticket_number:  'TSK-2026-0100',
          priority:       'high',
          status:         'new',
          pipeline_stage: 'backlog',
          task_scope:     'external',
          created_at:     '2026-05-16T10:00:00Z',
          deadline:       null,
          description:    'Urgent investigation required.',
          created_by_name: 'Ops Manager',
        },
      ],
      total: 1, page: 1, pages: 1,
    }),
    getDeptStaff: vi.fn().mockResolvedValue([
      { id: 'u1', user_id: 'u1', username: 'alice.tech', full_name: 'Alice Tech',
        staff_code: 'A01', job_title: 'Technician' },
      { id: 'u2', user_id: 'u2', username: 'bob.tech',   full_name: 'Bob Tech',
        staff_code: 'B02', job_title: 'Engineer' },
    ]),
    assign: vi.fn().mockResolvedValue({ id: 'task-1', status: 'assigned' }),
  },
}));

vi.mock('../store/auth.store', () => ({
  useAuthStore: (sel: (s: any) => any) => sel({
    user:         { id: 'u-manager', username: 'dept.manager' },
    isAuth:       true,
    _hasHydrated: true,
    roleLevel:    4,
  }),
}));

vi.mock('../store/ui.store', () => ({
  useUIStore: () => ({
    addToast: vi.fn(),
    toasts:   [],
  }),
}));

// ── Helpers ───────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <DeptInboxPage />
    </QueryClientProvider>,
  );
}

// ══════════════════════════════════════════════════════════════
//  Rendering
// ══════════════════════════════════════════════════════════════

describe('DeptInboxPage — rendering', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('renders the page header', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/department inbox/i)).toBeTruthy();
    });
  });

  it('renders task items from the inbox after loading', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Investigate fiber cut in Zone 4')).toBeTruthy();
    });
  });

  it('renders the ticket number badge', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('TSK-2026-0100')).toBeTruthy();
    });
  });

  it('shows creator attribution', async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('Ops Manager')).toBeTruthy();
    });
  });
});

// ══════════════════════════════════════════════════════════════
//  Assign modal
// ══════════════════════════════════════════════════════════════

describe('DeptInboxPage — assign modal', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('opens assign modal when "Assign to Staff" button is clicked', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => {
      expect(screen.getByText(/assign task to staff/i)).toBeTruthy();
    });
  });

  it('shows the task title in the assign modal', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => {
      const matches = screen.getAllByText(/investigate fiber cut in zone 4/i);
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  it('confirm button is disabled until a staff member is selected', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => screen.getByText(/assign task to staff/i));
    // The "Assign" button in the modal footer — last button with name "Assign"
    const assignBtns = screen.getAllByRole('button', { name: /^assign$/i });
    const modalAssign = assignBtns[assignBtns.length - 1];
    expect((modalAssign as HTMLButtonElement).disabled).toBe(true);
  });

  it('staff members appear in the select dropdown', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => screen.getByText(/assign task to staff/i));
    // Select is a listbox (Phase 4): open it and read its options
    await userEvent.click(screen.getByRole('combobox'));
    const options = (await screen.findAllByRole('option')).map(o => o.textContent ?? '');
    expect(options.some(o => o.includes('Alice Tech'))).toBe(true);
    expect(options.some(o => o.includes('Bob Tech'))).toBe(true);
  });

  it('selecting a staff member enables the Assign button', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => screen.getByText(/assign task to staff/i));
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByRole('option', { name: /Alice Tech/ }));
    await waitFor(() => {
      const assignBtns = screen.getAllByRole('button', { name: /^assign$/i });
      const modalAssign = assignBtns[assignBtns.length - 1];
      expect((modalAssign as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('closes modal on Cancel click', async () => {
    renderPage();
    await waitFor(() => screen.getByText('Investigate fiber cut in Zone 4'));
    await userEvent.click(screen.getByRole('button', { name: /assign to staff/i }));
    await waitFor(() => screen.getByText(/assign task to staff/i));
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => {
      expect(screen.queryByText(/assign task to staff/i)).toBeNull();
    });
  });
});

// ══════════════════════════════════════════════════════════════
//  Empty state
// ══════════════════════════════════════════════════════════════

describe('DeptInboxPage — empty state', () => {
  it('shows empty state when inbox has no items', async () => {
    const { tasksApi } = await import('../api/tasks.api');
    (tasksApi.getDeptInbox as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [], total: 0, page: 1, pages: 0,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/inbox clear/i)).toBeTruthy();
    });
  });
});
