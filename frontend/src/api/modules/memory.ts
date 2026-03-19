import { api } from '../client';

export interface ModelDownloadStatus {
  model: string;
  status: 'not_downloaded' | 'downloading' | 'ready';
  progress: number;
  message?: string;
  updated_at: number;
}

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
  runtime_user_id?: string | null;
  memory_owner_id?: string | null;
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

export interface L2Entity {
  entity_id: string;
  canonical_name: string;
  entity_type: string;
  aliases: string[];
}

export interface L2Mention {
  mention_id: number;
  mention_text: string;
  normalized_surface?: string;
  entity_type?: string;
  evidence_event_ids?: string[];
  evidence_text?: string | null;
  resolved_entity_id?: string | null;
  confidence?: number | null;
}

export interface L2Snapshot {
  snapshot_id: string;
  entity_id: string;
  entity_type: string;
  core_traits: Record<string, unknown>;
  preferences: Record<string, unknown>;
  relationship_topology?: Record<string, unknown>;
  current_stress_level?: number;
  current_mood?: string | null;
  current_engagement?: number;
}

export interface L2GraphConflictRule {
  predicate: string;
  opposite_predicates: string[];
  opposite_resolution: string;
  exclusive_group?: string | null;
  exclusive_scope: string;
  exclusive_resolution: string;
}

export interface L2GraphConflictRulePayload {
  predicate: string;
  opposite_predicates: string[];
  opposite_resolution: string;
  exclusive_group?: string | null;
  exclusive_scope?: string;
  exclusive_resolution: string;
}

export interface ManualL2EventPayload {
  text: string;
  user_id: string;
  session_id?: string;
  source?: string;
  entity_focus_hint?: string;
}

export interface L2QueuedActionResponse {
  queued: boolean;
  event_id?: string;
  entity_ids?: string[];
}

export interface L2Statistics {
  canonical_self_id?: string;
  identity_link_count?: number;
  relation_count: number;
  assertion_count: number;
  extract_skipped?: number;
  extract_by_evidence_class?: Record<string, number>;
  skip_by_reason?: Record<string, number>;
  db_path?: string;
}

export interface MemoryIdentityLink {
  namespace: string;
  runtime_user_id: string;
  memory_owner_id: string;
  link_type: string;
}

export interface MemoryIdentityLinksResponse {
  canonical_self_id: string;
  links: MemoryIdentityLink[];
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
  key_entities?: Array<{ entity_id?: string; entity_type?: string }>;
  sentiment_summary?: Record<string, unknown> | null;
  change_and_pattern?: { changes?: string[]; patterns?: string[] } | null;
  source_event_ids?: string[];
  source_event_count: number;
  importance_aggregate?: number;
  event_type_distribution?: Record<string, number>;
  generated_by_model?: string | null;
  created_at: number;
  updated_at?: number;
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
  identity?: { canonical_self_id: string; identity_link_count: number };
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

export interface MemorySearchResultPayload {
  l0_workbench: Array<Record<string, unknown>>;
  l1_events: Array<Record<string, unknown>>;
  l2_entity_cards: Array<Record<string, unknown>>;
  l2_relationships: Array<Record<string, unknown>>;
  l3_reflections: Array<Record<string, unknown>>;
  l4_procedures: Array<Record<string, unknown>>;
  trace: Record<string, unknown>;
}

// Legacy API object for backward compatibility
export const memoryApi = {
  // L0 Working Memory
  getL0Sessions: () =>
    api.get<{ sessions: L0Session[]; stats: L0Stats }>('/memory/l0/sessions') as unknown as Promise<{ sessions: L0Session[]; stats: L0Stats }>,
  getL0Workbench: (sessionId: string) =>
    api.get<L0Workbench>(`/memory/l0/workbench/${sessionId}`) as unknown as Promise<L0Workbench>,

  // L1 Event Stream
  getL1Events: (params?: { limit?: number; event_type?: string; user_id?: string; session_id?: string }) =>
    api.get<{ events: L1Event[]; stats: { total: number } }>('/memory/l1/events', { params }) as unknown as Promise<{ events: L1Event[]; stats: { total: number } }>,

  // L2 Cognition
  getL2Statistics: () =>
    api.get<L2Statistics>('/memory/l2/statistics') as unknown as Promise<L2Statistics>,
  getIdentityLinks: () =>
    api.get<MemoryIdentityLinksResponse>('/memory/identity/links') as unknown as Promise<MemoryIdentityLinksResponse>,
  getL2Relations: (limit?: number) =>
    api.get<L2Relation[]>('/memory/l2/relations', { params: limit ? { limit } : undefined }) as unknown as Promise<L2Relation[]>,
  getL2Assertions: (limit?: number) =>
    api.get<L2Assertion[]>('/memory/l2/assertions', { params: limit ? { limit } : undefined }) as unknown as Promise<L2Assertion[]>,
  getL2Entities: (limit?: number) =>
    api.get<L2Entity[]>('/memory/l2/entities', { params: limit ? { limit } : undefined }) as unknown as Promise<L2Entity[]>,
  getL2Mentions: (limit?: number) =>
    api.get<L2Mention[]>('/memory/l2/mentions', { params: limit ? { limit } : undefined }) as unknown as Promise<L2Mention[]>,
  getL2Snapshots: (limit?: number) =>
    api.get<L2Snapshot[]>('/memory/l2/snapshots', { params: limit ? { limit } : undefined }) as unknown as Promise<L2Snapshot[]>,
  getL2ConflictRules: () =>
    api.get<L2GraphConflictRule[]>('/memory/l2/conflict-rules') as unknown as Promise<L2GraphConflictRule[]>,
  createManualL2Event: (payload: ManualL2EventPayload) =>
    api.post<L2QueuedActionResponse>('/memory/l2/manual-event', payload) as unknown as Promise<L2QueuedActionResponse>,
  replayL2Extraction: (eventId: string) =>
    api.post<L2QueuedActionResponse>(`/memory/l2/extract/${eventId}`) as unknown as Promise<L2QueuedActionResponse>,
  reconcileL2Entities: (entityIds: string[]) =>
    api.post<L2QueuedActionResponse>('/memory/l2/reconcile', { entity_ids: entityIds }) as unknown as Promise<L2QueuedActionResponse>,
  refreshL2Snapshots: (entityIds: string[]) =>
    api.post<L2QueuedActionResponse>('/memory/l2/snapshot-refresh', { entity_ids: entityIds }) as unknown as Promise<L2QueuedActionResponse>,
  upsertL2ConflictRule: (payload: L2GraphConflictRulePayload) =>
    api.put<L2GraphConflictRule>(`/memory/l2/conflict-rules/${payload.predicate}`, {
      opposite_predicates: payload.opposite_predicates,
      opposite_resolution: payload.opposite_resolution,
      exclusive_group: payload.exclusive_group ?? null,
      exclusive_scope: payload.exclusive_scope ?? 'same_subject',
      exclusive_resolution: payload.exclusive_resolution,
    }) as unknown as Promise<L2GraphConflictRule>,

  // L3 Reflection
  getL3Summaries: (params?: { limit?: number; summary_type?: string; summary_category?: string }) =>
    api.get<L3Summary[]>('/memory/l3/summaries', { params }) as unknown as Promise<L3Summary[]>,

  // L4 Procedural
  getL4Skills: (limit?: number) =>
    api.get<L4Skill[]>('/memory/procedures', { params: limit ? { limit } : undefined }) as unknown as Promise<L4Skill[]>,

  // Statistics & Search
  getStatistics: () =>
    api.get<MemoryStatistics>('/memory/statistics') as unknown as Promise<MemoryStatistics>,
  search: (query: string, options?: { limit?: number; query_mode?: string }) =>
    api.post<MemorySearchResultPayload>('/memory/search', { query, limit: options?.limit ?? 20, query_mode: options?.query_mode ?? 'detail' }) as unknown as Promise<MemorySearchResultPayload>,

  // Clear
  clearAll: () =>
    api.delete<ClearMemoryResponse>('/memory/clear') as unknown as Promise<ClearMemoryResponse>,
};

export default memoryApi;
