// ============================================================
// PUSH BACK MODAL — S2.2.5 enriched
// Reason field (text, required ≥ 10 characters). Confirm disabled until met.
// ============================================================

import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';
import type { ProjectPipelineStage } from '@shared';
import { GlassModal } from '../glass';
import { Button, Textarea } from '../ui';
import s from './StageDialog.module.css';

interface PushBackModalProps {
  isOpen:        boolean;
  onClose:       () => void;
  onSubmit:      (reason: string, comment?: string) => Promise<void>;
  currentStage?: ProjectPipelineStage;
  prevStage?:    ProjectPipelineStage;
}

const MIN_REASON = 10;

export function PushBackModal({ isOpen, onClose, onSubmit, currentStage, prevStage }: PushBackModalProps) {
  const [reason, setReason] = useState('');
  const [comment, setComment] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const trimmed = reason.trim();
  const canSubmit = trimmed.length >= MIN_REASON;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setIsSubmitting(true);
    try {
      await onSubmit(trimmed, comment.trim() || undefined);
      setReason('');
      setComment('');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <GlassModal
      open={isOpen}
      onClose={onClose}
      size="sm"
      title="Push back stage"
      description="The project goes back to the previous stage. Give a clear reason."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
          <Button variant="danger-solid" onClick={handleSubmit} disabled={!canSubmit} loading={isSubmitting}
            leftIcon={<ArrowLeft size={14} aria-hidden="true" />}>
            Push back
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.route}>
          <div className={s.stage} data-role="from">
            <div className={s.stageRole}>Current stage</div>
            <div className={s.stageName}>{currentStage?.stageName ?? '—'}</div>
            <div className={s.stageMeta}>{currentStage?.departmentName}</div>
          </div>
          <ArrowLeft size={16} className={s.arrow} aria-hidden="true" />
          <div className={s.stage} data-role="back">
            <div className={s.stageRole}>Returns to</div>
            <div className={s.stageName}>{prevStage?.stageName ?? 'Previous stage'}</div>
            <div className={s.stageMeta}>{prevStage?.departmentName}</div>
          </div>
        </div>
        <Textarea
          label="Reason"
          required
          value={reason}
          onChange={setReason}
          placeholder="Specifically, why is this stage going back?"
          rows={3}
          hint={`At least ${MIN_REASON} characters (${trimmed.length}/${MIN_REASON})`}
          style={{ marginBottom: 0 }}
        />
        <Textarea label="Additional notes (optional)" value={comment} onChange={setComment} placeholder="Supporting context or the corrective action needed" rows={2} style={{ marginBottom: 0 }} />
      </div>
    </GlassModal>
  );
}
