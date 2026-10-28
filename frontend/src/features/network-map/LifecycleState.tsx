import type { NetLifecycleStatus } from '@shared';
import { LIFECYCLE_COLOR, LIFECYCLE_LABEL } from './symbology';
import s from './NetworkMap.module.css';

/** Lifecycle as words plus a mark whose shape also changes (faulty ◆, verified ◌). */
export function LifecycleState({ status }: { status: NetLifecycleStatus }) {
  return (
    <span className={s.state} data-state={status} style={{ ['--state-color' as string]: LIFECYCLE_COLOR[status] }}>
      <span className={s.stateMark} aria-hidden="true" />
      {LIFECYCLE_LABEL[status] ?? status}
    </span>
  );
}
