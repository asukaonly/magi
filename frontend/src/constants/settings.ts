/**
 * Settings page constants.
 */

import {
  Settings2,
  Brain,
  User,
  Database,
  Wrench,
  BarChart3,
  ScrollText,
  PlugZap,
  Send,
} from 'lucide-react';

import type { NavItem } from '@/types/settings';
export { isNavGroup } from '@/types/settings';

// ============================================================================
// Storage Keys
// ============================================================================

export const LANGUAGE_STORAGE_KEY = 'magi_language';

// ============================================================================
// Navigation Items
// ============================================================================

export const NAV_ITEMS: NavItem[] = [
  { id: 'preferences', icon: Settings2 },
  { id: 'llm', icon: Brain, children: [{ id: 'llmProviders' }, { id: 'llmModels' }] },
  { id: 'usage', icon: BarChart3 },
  { id: 'personality', icon: User },
  {
    id: 'memory',
    icon: Database,
    children: [
      { id: 'memoryGeneral' },
      { id: 'memoryWorkbench' },
      { id: 'memoryEvents' },
      { id: 'memoryKnowledge' },
      { id: 'memoryReflection' },
      { id: 'memorySkills' },
    ],
  },
  { id: 'timeline', icon: ScrollText },
  { id: 'extensions', icon: PlugZap },
  { id: 'tools', icon: Wrench },
  { id: 'actions', icon: Send },
];
