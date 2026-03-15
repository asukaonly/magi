/**
 * Chat domain types.
 */

import type {
  ChatTimelineMessage,
  NormalizedTraceSummary,
  NormalizedTraceNode,
  NormalizedTraceSnapshot,
} from '@/types';

// Re-export types from central types
export type {
  ChatTimelineMessage,
  NormalizedTraceSummary,
  NormalizedTraceNode,
  NormalizedTraceSnapshot,
};

// Domain-specific types
export type ChatMessageKind = 'user' | 'assistant' | 'status';
export type ChatMessageRole = 'user' | 'assistant';

export interface PersonalityInfo {
  name: string;
  avatar?: string;
  greeting?: string;
}
