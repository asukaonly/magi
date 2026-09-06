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
  | 'l0'
  | 'l1'
  | 'l2'
  | 'l3'
  | 'l4';

// ============================================================================
// Draft Types
// ============================================================================

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
