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
  { id: 'personality', icon: User, children: [{ id: 'personalitySelection' }, { id: 'personalitySettings' }] },
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
  { id: 'plugins', icon: PlugZap, children: [{ id: 'pluginsInstalled' }, { id: 'pluginsMarketplace' }] },
  { id: 'timeline', icon: ScrollText },
  { id: 'channels', icon: Radio },
  { id: 'tools', icon: Wrench },
  {
    id: 'statistics',
    icon: BarChart3,
    children: [{ id: 'statisticsLlm' }, { id: 'statisticsRuntime' }],
  },
];
