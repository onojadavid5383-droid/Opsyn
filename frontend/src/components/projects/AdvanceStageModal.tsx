// ============================================================
// ADVANCE STAGE MODAL — S2.2.5 enriched
// Shows from/to stage with department + expected days.
// Final stage: confirmation language + required checkbox.
// ============================================================

import { ArrowRight } from 'lucide-react';
import { useState } from 'react';
import type { ProjectPipelineStage } from '@shared';
import { GlassModal } from '../glass';
import { Button, Textarea } from '../ui';
import s from './StageDialog.module.css';

interface AdvanceStageModalProps {
  isOpen:        boolean;
  onClose:       () => void;
  onSubmit:      (comment?: string) => Promise<void>;
  currentStage?: ProjectPipelineStage;
  nextStage?:    ProjectPipelineStage;
}

function StageCard({ stage, role, label }: { stage?: ProjectPipelineStage; role: 'from' | 'to'; label: string }) {
  const days = (stage as { expectedDurationDays?: number } | undefined)?.expectedDurationDays;
  return (
    <div className={s.stage} data-role={role}>
      <div className={s.stageRole}>{label}</div>
      <div className={s.stageName}>{stage?.stageName ?? '—'}</div>
      <div className={s.stageMeta}>{stage?.departmentName}{days ? ` · est. ${days} days` : ''}</div>
    </div>
  );
}

export function AdvanceStageModal({ isOpen, onClose, onSubmit, currentStage, nextStage }: AdvanceStageModalProps) {
  const [comment, setComment] = useState('');
  const [finalConfirm, setFinalConfirm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isFinalStage = !nextStage;
  const canConfirm = isFinalStage ? finalConfirm : true;

  const handleSubmit = async () => {
    if (isFinalStage && !finalConfirm) return;
    setIsSubmitting(true);
    try {
      await onSubmit(comment.trim() || undefined);
      setComment('');
      setFinalConfirm(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <GlassModal
      open={isOpen}
      onClose={onClose}
      size="sm"
      title={isFinalStage ? 'Complete pipeline' : 'Advance stage'}
      description={isFinalStage ? 'This is the final stage — the project pipeline will be marked complete.' : 'Hand the project on to the next stage.'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>Cancel</Button>
          <Button variant="primary" onClick={handleSubmit} disabled={!canConfirm} loading={isSubmitting}
            rightIcon={isFinalStage ? undefined : <ArrowRight size={14} aria-hidden="true" />}>
            {isFinalStage ? 'Complete pipeline' : 'Advance stage'}
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        {isFinalStage ? (
          <StageCard stage={currentStage} role="from" label="Final stage" />
        ) : (
          <div className={s.route}>
            <StageCard stage={currentStage} role="from" label="Current stage" />
            <ArrowRight size={16} className={s.arrow} aria-hidden="true" />
            <StageCard stage={nextStage} role="to" label="Next stage" />
          </div>
        )}
        <Textarea label="Handoff note (optional)" value={comment} onChange={setComment} placeholder="What the next stage needs to know" rows={3} style={{ marginBottom: 0 }} />
        {isFinalStage && (
          <label className={s.check}>
            <input type="checkbox" checked={finalConfirm} onChange={e => setFinalConfirm(e.target.checked)} />
            I confirm this project pipeline is complete and ready to be closed.
          </label>
        )}
      </div>
    </GlassModal>
  );
}
