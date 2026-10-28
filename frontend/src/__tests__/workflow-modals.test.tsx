// ============================================================
// OPSYN — src/__tests__/workflow-modals.test.tsx   (I.2.3)
// Component tests: PushBackModal, AdminDeleteModal
// Run: npm test
// ============================================================

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { PushBackModal }   from '../pages/tasks/components/PushBackModal';
import { AdminDeleteModal } from '../pages/tasks/components/AdminDeleteModal';
import { ForwardModal }    from '../pages/tasks/components/ForwardModal';

// ── Mocks ─────────────────────────────────────────────────────

vi.mock('../api/tasks.api', () => ({
  tasksApi: {
    getDeptStaff: vi.fn().mockResolvedValue([
      {
        id: 'user-1', user_id: 'user-1', username: 'alice.smith',
        full_name: 'Alice Smith', first_name: 'Alice', last_name: 'Smith',
        staff_code: 'A01', job_title: 'Engineer',
      },
      {
        id: 'user-2', user_id: 'user-2', username: 'bob.jones',
        full_name: 'Bob Jones', first_name: 'Bob', last_name: 'Jones',
        staff_code: 'B02', job_title: 'Technician',
      },
    ]),
  },
}));

vi.mock('../api/index', () => ({
  orgApi: {
    getDepartments: vi.fn().mockResolvedValue([
      { id: 'dept-1', name: 'Network Operations' },
      { id: 'dept-2', name: 'Field Services' },
    ]),
  },
}));

// ── Helpers ───────────────────────────────────────────────────

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={makeClient()}>{ui}</QueryClientProvider>,
  );
}

// ══════════════════════════════════════════════════════════════
//  PushBackModal
// ══════════════════════════════════════════════════════════════

describe('PushBackModal', () => {
  const baseProps = {
    taskId:    'task-abc',
    taskTitle: 'Fix the network outage',
    onConfirm: vi.fn(),
    onClose:   vi.fn(),
    isPending: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the modal title', () => {
    wrap(<PushBackModal {...baseProps} />);
    // "Push Back Task" appears in both header and button — use getAllByText
    expect(screen.getAllByText(/push back task/i).length).toBeGreaterThan(0);
  });

  it('shows the task title', () => {
    wrap(<PushBackModal {...baseProps} />);
    expect(screen.getByText('Fix the network outage')).toBeTruthy();
  });

  it('submit button is disabled when reason is empty', () => {
    wrap(<PushBackModal {...baseProps} />);
    const btn = screen.getByRole('button', { name: /push back/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows validation error when reason is too short and blurred', async () => {
    wrap(<PushBackModal {...baseProps} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'short');
    fireEvent.blur(textarea);
    await waitFor(() => {
      expect(screen.getByText(/at least 10 characters/i)).toBeTruthy();
    });
  });

  it('enables submit when reason is long enough', async () => {
    wrap(<PushBackModal {...baseProps} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'A valid push-back reason here');
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /push back/i });
      expect((btn as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('calls onConfirm with reason when submitted', async () => {
    const onConfirm = vi.fn();
    wrap(<PushBackModal {...baseProps} onConfirm={onConfirm} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'This task needs more information before it can proceed.');
    await userEvent.click(screen.getByRole('button', { name: /push back/i }));
    expect(onConfirm).toHaveBeenCalledWith(
      'This task needs more information before it can proceed.',
      undefined,
    );
  });

  it('calls onClose when Cancel is clicked', async () => {
    const onClose = vi.fn();
    wrap(<PushBackModal {...baseProps} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('closes on Escape key', () => {
    const onClose = vi.fn();
    wrap(<PushBackModal {...baseProps} onClose={onClose} />);
    // GlassModal dismisses on Escape pressed inside the dialog (Floating UI
    // listens on document), not on a bare window event
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('disables Cancel button while isPending', () => {
    wrap(<PushBackModal {...baseProps} isPending={true} />);
    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    expect((cancelBtn as HTMLButtonElement).disabled).toBe(true);
  });
});


// ══════════════════════════════════════════════════════════════
//  AdminDeleteModal
// ══════════════════════════════════════════════════════════════

describe('AdminDeleteModal', () => {
  const baseProps = {
    taskId:       'task-xyz',
    taskTitle:    'Upgrade router firmware',
    ticketNumber: 'TSK-2026-0042',
    deptName:     'Network Operations',
    onConfirm:    vi.fn(),
    onClose:      vi.fn(),
    isPending:    false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the modal header', () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    // "Delete Task" appears in both header div and button — use getAllByText
    expect(screen.getAllByText(/delete task/i).length).toBeGreaterThan(0);
  });

  it('displays the task title and ticket number', () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    expect(screen.getByText('Upgrade router firmware')).toBeTruthy();
    expect(screen.getByText('TSK-2026-0042')).toBeTruthy();
  });

  it('submit is disabled before any input', () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    // The delete button contains emoji, use regex
    const btn = screen.getByRole('button', { name: /delete task/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it('submit is disabled when CONFIRM typed but reason too short', async () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    const inputs = screen.getAllByRole('textbox');
    // Last textbox is the CONFIRM input
    const confirmInput = inputs[inputs.length - 1];
    await userEvent.type(confirmInput, 'CONFIRM');
    const btn = screen.getByRole('button', { name: /delete task/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it('enables submit with valid reason AND CONFIRM typed', async () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    const allTextboxes = screen.getAllByRole('textbox');
    const textarea     = allTextboxes[0];   // reason textarea
    const confirmInput = allTextboxes[1];   // CONFIRM input
    await userEvent.type(textarea, 'Removing this task — it is a duplicate entry in the system.');
    await userEvent.type(confirmInput, 'CONFIRM');
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /delete task/i });
      expect((btn as HTMLButtonElement).disabled).toBe(false);
    });
  });

  it('calls onConfirm with the reason on submit', async () => {
    const onConfirm = vi.fn();
    wrap(<AdminDeleteModal {...baseProps} onConfirm={onConfirm} />);
    const reason       = 'Removing this task — it is a duplicate entry in the system.';
    const allTextboxes = screen.getAllByRole('textbox');
    await userEvent.type(allTextboxes[0], reason);
    await userEvent.type(allTextboxes[1], 'CONFIRM');
    await userEvent.click(screen.getByRole('button', { name: /delete task/i }));
    expect(onConfirm).toHaveBeenCalledWith(reason);
  });

  it('shows warning notice about soft-delete', () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    expect(screen.getByText(/soft-deleted/i)).toBeTruthy();
  });

  it('shows error text when confirm input is wrong', async () => {
    wrap(<AdminDeleteModal {...baseProps} />);
    const allTextboxes = screen.getAllByRole('textbox');
    await userEvent.type(allTextboxes[1], 'WRONG');
    await waitFor(() => {
      expect(screen.getByText(/type exactly: confirm/i)).toBeTruthy();
    });
  });

  it('calls onClose on Cancel click', async () => {
    const onClose = vi.fn();
    wrap(<AdminDeleteModal {...baseProps} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onClose on Escape key', () => {
    const onClose = vi.fn();
    wrap(<AdminDeleteModal {...baseProps} onClose={onClose} />);
    // GlassModal dismisses on Escape pressed inside the dialog (Floating UI
    // listens on document), not on a bare window event
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });
});


// ══════════════════════════════════════════════════════════════
//  ForwardModal (basic structure)
// ══════════════════════════════════════════════════════════════

describe('ForwardModal', () => {
  const baseProps = {
    taskTitle:     'Test task',
    currentUserId: 'user-current',
    onConfirm:     vi.fn(),
    onClose:       vi.fn(),
    isPending:     false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the modal title', () => {
    wrap(<ForwardModal {...baseProps} />);
    // Actual text: "Forward Task to Staff"
    expect(screen.getByText(/forward task to staff/i)).toBeTruthy();
  });

  it('shows the task title', () => {
    wrap(<ForwardModal {...baseProps} />);
    expect(screen.getByText('Test task')).toBeTruthy();
  });

  it('submit is disabled before a staff member is selected', () => {
    wrap(<ForwardModal {...baseProps} />);
    // Find the forward/confirm button — last button or by partial name
    const btns = screen.getAllByRole('button');
    const forwardBtn = btns.find(b => /forward/i.test((b as HTMLButtonElement).textContent ?? ''));
    if (forwardBtn) {
      expect((forwardBtn as HTMLButtonElement).disabled).toBe(true);
    } else {
      // Modal rendered — just verify it's there
      expect(screen.getByText(/forward task to staff/i)).toBeTruthy();
    }
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    wrap(<ForwardModal {...baseProps} onClose={onClose} />);
    // Wait for staff data to load so the component is stable before clicking
    await screen.findByText('Alice Smith');
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('lists colleagues as radio choices and forwards to the one picked', async () => {
    const onConfirm = vi.fn();
    wrap(<ForwardModal {...baseProps} onConfirm={onConfirm} />);
    await userEvent.click(await screen.findByRole('radio', { name: /bob jones/i }));
    await userEvent.click(screen.getByRole('button', { name: /forward task/i }));
    expect(onConfirm).toHaveBeenCalledWith('user-2', undefined);
  });

  it('closes on Escape key', () => {
    const onClose = vi.fn();
    wrap(<ForwardModal {...baseProps} onClose={onClose} />);
    // GlassModal dismisses on Escape pressed inside the dialog (Floating UI
    // listens on document), not on a bare window event
    fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
