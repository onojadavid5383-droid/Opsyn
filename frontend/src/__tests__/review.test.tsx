// ============================================================
// Network GIS Phase 9 — review and approval on the client: the deployment
// gate, submitting (validation first; errors block), deciding (only when
// allowed; sending back needs a reason), withdrawing, comments pinned on
// the map, and the BOQ revision with its changes. Mocked design API.
// ============================================================

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import type { ApprovalOverview, ApprovalRequest, Design } from '@shared';

vi.mock('../api/design.api', () => ({
  designApi: {
    approvals: vi.fn(), submitDesign: vi.fn(), submitBoq: vi.fn(), reopen: vi.fn(), decide: vi.fn(), withdraw: vi.fn(),
    comment: vi.fn(), resolveComment: vi.fn(), boqDiff: vi.fn(), validate: vi.fn(),
  },
}));

import { designApi } from '../api/design.api';
import { ReviewDrawer } from '../features/network-map/design/ReviewDrawer';
import { useDesignMapStore } from '../features/network-map/design/designStore';

const api = vi.mocked(designApi);

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const design = (status: Design['status']) => ({
  id: 'd1', project_id: 'p1', project_name: 'P', name: 'Toyin', description: null, status, boundary: null, bbox: null,
  engine_config: {}, current_version: { id: 'v2', version_no: 2, label: null, creation_method: 'MANUAL', created_at: '' },
  input_counts: { road: 5, homepass: 4, pole: 0, building: 0, pickup: 0, existing_structure: 0 }, created_at: '', updated_at: '',
}) as Design;

const step = (no: number, key: string, label: string, feature: string, status: ApprovalRequest['steps'][number]['status'], over = {}) =>
  ({ step_no: no, key, label, feature_key: feature, status, decided_by: null, decided_at: null, comment: null, ...over });

const req = (over: Partial<ApprovalRequest> = {}): ApprovalRequest => ({
  id: 'r1', subject_type: 'DESIGN_VERSION', subject_id: 'v2', revision: 2, status: 'PENDING', note: 'Ready', submitted_by: 'Ngozi',
  submitted_at: new Date().toISOString(), decided_at: null, payload: { validation: { errors: 0, warnings: 1 } },
  steps: [step(1, 'ENGINEERING_REVIEW', 'Engineering review', 'design.review', 'PENDING'),
          step(2, 'LINE_MANAGER_APPROVAL', 'Line manager approval', 'design.approve', 'WAITING')],
  comments: [], pending_step: 'ENGINEERING_REVIEW', can_decide: true, can_withdraw: false, ...over,
});

const overview = (over: Partial<ApprovalOverview> = {}): ApprovalOverview => ({
  requests: [], can_submit_design: false, can_submit_boq: false,
  gate: { design: null, boq: null, design_approved: false, boq_approved: false, can_deploy: false, reasons: [] }, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  useDesignMapStore.setState({ commentPick: false, commentTarget: null });
});

describe('ReviewDrawer', () => {
  it('checks the design before it can be submitted; errors block it', async () => {
    api.approvals.mockResolvedValue(overview({ can_submit_design: true }));
    api.validate.mockResolvedValue({ issues: [], summary: { errors: 2, warnings: 0, info: 0 } });
    const onIssues = vi.fn();
    wrap(<ReviewDrawer design={design('MODIFIED')} onClose={() => {}} onIssues={onIssues} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Check the design first' }));
    expect(await screen.findByText('2 errors stop the submission.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Submit version/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'See the issues' }));
    expect(onIssues).toHaveBeenCalled();
  });

  it('submits a clean design with a note', async () => {
    api.approvals.mockResolvedValue(overview({ can_submit_design: true }));
    api.validate.mockResolvedValue({ issues: [], summary: { errors: 0, warnings: 3, info: 0 } });
    api.submitDesign.mockResolvedValue(req());
    wrap(<ReviewDrawer design={design('MODIFIED')} onClose={() => {}} onIssues={() => {}} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Check the design first' }));
    expect(await screen.findByText('No errors; 3 warnings the reviewer will see.')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Note for the reviewer (optional)'), 'FAT moved closer');
    await userEvent.click(screen.getByRole('button', { name: 'Submit version 2' }));
    await waitFor(() => expect(api.submitDesign).toHaveBeenCalledWith('d1', 'FAT moved closer'));
  });

  it('lets a permitted reviewer pass the step, and sending back needs a reason', async () => {
    api.approvals.mockResolvedValue(overview({ requests: [req()] }));
    api.decide.mockResolvedValue(req());
    wrap(<ReviewDrawer design={design('UNDER_REVIEW')} onClose={() => {}} onIssues={() => {}} />);
    const section = await screen.findByRole('region', { name: 'Design version 2 review' });
    expect(within(section).getByText('waiting')).toBeInTheDocument();
    await userEvent.click(within(section).getByRole('button', { name: 'Pass engineering review' }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith('r1', 'APPROVE', null));
    await userEvent.click(within(section).getByRole('button', { name: 'Send back…' }));
    const send = within(section).getByRole('button', { name: 'Send back' });
    expect(send).toBeDisabled();
    await userEvent.type(within(section).getByLabelText('Why is it sent back?'), 'Wrong pole');
    await userEvent.click(send);
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith('r1', 'REJECT', 'Wrong pole'));
  });

  it('tells someone who may not decide who is needed, and lets the submitter withdraw', async () => {
    api.approvals.mockResolvedValue(overview({ requests: [req({ can_decide: false, can_withdraw: true })] }));
    api.withdraw.mockResolvedValue(req({ status: 'WITHDRAWN' }));
    wrap(<ReviewDrawer design={design('UNDER_REVIEW')} onClose={() => {}} onIssues={() => {}} />);
    expect(await screen.findByText(/someone who can do the engineering review \(design.review\)/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Pass/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw this submission' }));
    await waitFor(() => expect(api.withdraw).toHaveBeenCalledWith('r1'));
  });

  it('comments, pinned to what was clicked on the map', async () => {
    api.approvals.mockResolvedValue(overview({ requests: [req({ comments: [
      { id: 'c1', asset_id: 'a', cable_id: null, target_code: 'FAT-0002', lng: 3.4, lat: 6.6, body: 'Check the pole', author: 'Ada',
        created_at: new Date().toISOString(), resolved: false, resolved_by: null }] })] }));
    api.comment.mockResolvedValue(req());
    api.resolveComment.mockResolvedValue(req());
    wrap(<ReviewDrawer design={design('UNDER_REVIEW')} onClose={() => {}} onIssues={() => {}} />);
    expect(await screen.findByText('FAT-0002')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(api.resolveComment).toHaveBeenCalledWith('c1', true));
    await userEvent.click(screen.getByRole('button', { name: 'Pin on the map' }));
    expect(useDesignMapStore.getState().commentPick).toBe(true);
    useDesignMapStore.getState().setCommentTarget({ kind: 'cable', id: 'cab1', code: 'B2B-0003' });
    expect(await screen.findByText('B2B-0003')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Add a comment'), 'Too long');
    await userEvent.click(screen.getByRole('button', { name: 'Comment' }));
    await waitFor(() => expect(api.comment).toHaveBeenCalledWith('r1', { body: 'Too long', cable_id: 'cab1' }));
  });

  it('shows the gate, submits the BOQ of an approved design and compares revisions', async () => {
    const boq = req({ id: 'b2', subject_type: 'BOQ', revision: 2, payload: { version_no: 2, quantities: [
      { group: 'Devices', item: 'FAT', code: 'FAT', quantity: 3, unit: 'each' },
      { group: 'Cable', item: 'Box to box cable', code: 'BOX_TO_BOX', quantity: 412.5, unit: 'm' }] },
      steps: [step(1, 'BOQ_REVIEW', 'BOQ review', 'boq.review', 'PENDING'), step(2, 'BOQ_APPROVAL', 'BOQ approval', 'boq.approve', 'WAITING')] });
    api.approvals.mockResolvedValue(overview({ requests: [boq], can_submit_boq: true,
      gate: { design: 'APPROVED', boq: 'PENDING', design_approved: true, boq_approved: false, can_deploy: false, reasons: [] } }));
    api.boqDiff.mockResolvedValue({ revision: 2, previous_revision: 1, quantities: [], changes: [
      { item: 'FAT', code: 'FAT', unit: 'each', group: 'Devices', before: 2, after: 3, change: 1 }] });
    api.submitBoq.mockResolvedValue(boq);
    wrap(<ReviewDrawer design={design('APPROVED')} onClose={() => {}} onIssues={() => {}} />);
    const gate = await screen.findByRole('list', { name: 'What deployment needs' });
    expect(within(gate).getByText('Design approved').closest('li')).toHaveAttribute('data-ok', 'true');
    expect(within(gate).getByText('Not ready to deploy')).toBeInTheDocument();
    const rev = screen.getByRole('region', { name: 'BOQ revision 2 review' });
    await userEvent.click(within(rev).getByText(/Quantities \(2 lines\)/));
    expect(await within(rev).findByText('+1')).toBeInTheDocument();
    expect(within(rev).getByText('412.5 m')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Submit the BOQ/ }));
    await waitFor(() => expect(api.submitBoq).toHaveBeenCalledWith('d1', null));
  });
});
