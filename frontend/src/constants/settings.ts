/**
 * Settings page constants.
 */

import {
  Settings2,
  Brain,
  MessageSquare,
  User,
  Database,
  Wrench,
  BarChart3,
  ScrollText,
  PlugZap,
  Send,
  Radio,
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
  { id: 'conversation', icon: MessageSquare },
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
  { id: 'extensions', icon: PlugZap, children: [{ id: 'extensionsInstalled' }, { id: 'extensionsMarketplace' }] },
  { id: 'timeline', icon: ScrollText },
  { id: 'actions', icon: Send },
  { id: 'channels', icon: Radio },
  { id: 'tools', icon: Wrench },
  {
    id: 'statistics',
    icon: BarChart3,
    children: [{ id: 'statisticsLlm' }, { id: 'statisticsRuntime' }],
  },
];
