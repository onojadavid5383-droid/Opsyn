// ============================================================
// OPSYN UI — Select  (Phase 4)
// Same props as before (36 call sites); now a GlassSelect: the open list is
// a glass listbox (a native <select>'s menu is drawn by the OS and can't be
// styled), with native-equivalent keyboard behaviour.
// ============================================================

import type React from 'react';
import { GlassSelect } from '../glass';

export interface SelectOption {
  label:     string;
  value:     string;
  disabled?: boolean;
}

export interface SelectProps {
  label?:       string;
  id?:          string;
  value:        string;
  onChange:     (value: string) => void;
  options:      SelectOption[];
  placeholder?: string;
  error?:       string;
  hint?:        string;
  required?:    boolean;
  disabled?:    boolean;
  style?:       React.CSSProperties;
  selectStyle?: React.CSSProperties;
  /** Accessible name when there is no visible label */
  ariaLabel?:   string;
}

export function Select(props: SelectProps) {
  return <GlassSelect {...props} />;
}
