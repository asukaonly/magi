import { api } from '../client';

import type { ModelDownloadStatus } from 'app';

export interface ModelDownloadStatus {
  model: string;
  status: 'not_downloaded' | 'downloading' | 'ready';
  progress: number;
  message?: string;
  updated_at: number;
}

// L0 Working Memory Types
export interface L0Session {

// L0 Working Memory Types
export interface L0Session {
  session_id: string;
  user_id?: string;
  status: string;
  started_at: number;
  last_active_at: number;
  goal_count: number;
  entity_count: number;
  tactic_count: number;
}

export interface L0Stats {
  active_sessions: number;
  total_goals: number;
  total_entities: number;
  total_tactics: number;
  db_path?: string;
}

export interface L0Workbench {
  session: Record<string, unknown> | null;
  goal_stack: Array<Record<string, unknown>>;
  active_entities: Array<Record<string, unknown>>;
  temporary_tactics: Array<Record<string, unknown>>;
}

// L1 Event Types
export interface L1Event {
  event_id: string;
  event_type: string;
  raw_content: string;
  timestamp: number;
  source: string;
  memory_domain: string;
  retention_class: string;
  importance_score: number;
  cognition_eligible: boolean;
}

// L2 Cognition Types
export interface L2Relation {
  triple_id: string;
  subject_id: string;
  subject_type: string;
  predicate: string;
  object_id: string;
  object_type: string;
  confidence: number;
  evidence_event_ids: string[];
  observation_count: number;
  status: string;
}

export interface L2Assertion {
  assertion_id: string;
  entity_id: string;
  entity_type: string;
  trait_name: string;
  trait_value: string;
  confidence_score: number;
  evidence_events: string[];
  validation_state: string;
  volatility_index: number;
  source_domain: string;
  inference_depth: string;
  first_inferred_at: number;
  last_validated_at: number;
}

// L3 Summary Types
export interface L3Summary {
  summary_id: string;
  summary_type: string;
  summary_category: string;
  period_start: number;
  period_end: number;
  content: string;
  key_topics: string[];
  source_event_count: number;
  created_at: number;
}

// L4 Procedural Types
export interface L4Skill {
  skill_id: string;
  skill_name: string;
  skill_category: string;
  proficiency: number;
  success_rate: number;
  total_attempts: number;
  success_count: number;
  failure_count: number;
  circuit_breaker_state: string;
  last_used_at: number | null;
}

// Statistics Types
export interface MemoryStatistics {
  l0: L0Stats;
  l1: { event_count: number; db_path?: string };
  l2: { relation_count: number; assertion_count: number; db_path?: string };
  l3: { summary_count: number; db_path?: string };
  l4: { skill_count: number; open_circuit_breakers: number; db_path?: string };
}

export interface ClearMemoryResult {
  cleared: boolean;
  count: number;
}

export interface ClearMemoryResponse {
  success: boolean;
  results: {
    l0: ClearMemoryResult;
    l1: ClearMemoryResult;
    l2: ClearMemoryResult;
    l3: ClearMemoryResult;
    l4: ClearMemoryResult;
    chat_context: ClearMemoryResult;
  };
  warnings?: string[];
}

// Legacy API object for backward compatibility
export const memoryApi = {
  // L0 Working Memory
  getL0Sessions: () =>
    api.get<{ sessions: L0Session[]; stats: L0Stats }>('/memory/l0/sessions'),
  getL0Workbench: (sessionId: string) =>
    api.get<L0Workbench>(`/memory/l0/workbench/${sessionId}`),

  // L1 Event Stream
  getL1Events: (params?: { limit?: number; event_type?: string; user_id?: string; session_id?: string }) =>
    api.get<{ events: L1Event[]; stats: { total: number } }>('/memory/l1/events', { params }),

  // L2 Cognition
  getL2Statistics: () =>
    api.get<{ relation_count: number; assertion_count: number; db_path?: string }>('/memory/l2/statistics'),
  getL2Relations: (limit?: number) =>
    api.get<L2Relation[]>('/memory/l2/relations', { params: limit ? { limit } : undefined }),
  getL2Assertions: (limit?: number) =>
    api.get<L2Assertion[]>('/memory/l2/assertions', { params: limit ? { limit } : undefined }),

  // L3 Reflection
  getL3Summaries: (params?: { limit?: number; summary_type?: string }) =>
    api.get<L3Summary[]>('/memory/l3/summaries', { params }),

  // L4 Procedural
  getL4Skills: (limit?: number) =>
    api.get<L4Skill[]>('/memory/procedures', { params: limit ? { limit } : undefined }),

  // Statistics & Search
  getStatistics: () =>
    api.get<MemoryStatistics>('/memory/statistics'),
  search: (query: string, options?: { limit?: number; query_mode?: string }) =>
    api.post('/memory/search', { query, limit: options?.limit ?? 20, query_mode: options?.query_mode ?? 'detail' }),

  // Clear
  clearAll: () =>
    api.delete<ClearMemoryResponse>('/memory/clear') as unknown as Promise<ClearMemoryResponse>,
};

export default memoryApi;
