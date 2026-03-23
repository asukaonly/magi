/**
 * Settings page type definitions.
 */

import type { LucideIcon } from 'lucide-react';

// ============================================================================
// Navigation Types
// ============================================================================

export type NavLeaf = {
  id: string;
  icon: LucideIcon;
  children?: never;
};

export type NavGroup = {
  id: string;
  icon: LucideIcon;
  children: Array<{ id: string }>;
};

export type NavItem = NavLeaf | NavGroup;

export const isNavGroup = (item: NavItem): item is NavGroup =>
  Array.isArray((item as NavGroup).children);

// ============================================================================
// Memory Types
// ============================================================================

export type MemoryToggleFieldId =
  | 'enable_l0'
  | 'enable_l1'
  | 'enable_l2'
  | 'enable_l3'
  | 'enable_l4'
  | 'runtime_replay_include_l0_only'
  | 'enable_t1_importance'
  | 'enable_l1_vectorization'
  | 'enable_l2_llm_extraction'
  | 'enable_l2_conflict_arbitration'
  | 'enable_l3_llm_summary'
  | 'enable_l3_vectorization'
  | 'enable_l4_skill_extraction'
  | 'retention_days'
  | 'l0_checkpoint_interval_seconds';

// ============================================================================
// Draft Types
// ============================================================================

export type PluginDraftMap = Record<string, Record<string, unknown>>;

export type ToolDraftSnapshot = {
  enabled: boolean;
  values: Record<string, unknown>;
};

export type ToolDraftMap = Record<string, ToolDraftSnapshot>;

// ============================================================================
// Handle Types
// ============================================================================

export interface SettingsPageHandle {
  hasUnsavedChanges: () => boolean;
  discardChanges: () => Promise<void>;
}

export interface SettingsPageProps {
  onRequestClose?: () => void;
}
