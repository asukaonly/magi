import { api, unwrapGatewayPayload } from '../client';
import type { GatewayResponse } from '../client';

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
  short_session_id?: string;
  display_title?: string;
  display_subtitle?: string | null;
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

export const getL0SessionPrimaryLabel = (session: Pick<L0Session, 'display_title' | 'short_session_id' | 'session_id'>): string =>
  String(session.display_title || session.short_session_id || session.session_id || '').trim();

export const getL0SessionSecondaryLabel = (
  session: Pick<L0Session, 'display_subtitle' | 'session_id' | 'short_session_id'>
): string | null => {
  const subtitle = String(session.display_subtitle || '').trim();
  if (subtitle) {
    return subtitle;
  }
  const shortId = String(session.short_session_id || '').trim();
  const sessionId = String(session.session_id || '').trim();
  if (sessionId && shortId && sessionId !== shortId) {
    return sessionId;
  }
  return null;
};

// L1 Event Types
export interface L1Event {
  id?: number;
  event_id: string;
  correlation_id?: string | null;
  event_type: string;
  source?: string;
  source_item_id?: string | null;
  idempotency_key?: string | null;
  timestamp: number;
  created_at?: number;
  session_id?: string | null;
  turn_id?: string | null;
  user_id?: string | null;
  task_id?: string | null;
  content: string;
  author_type?: string | null;
  content_type?: string | null;
  memory_domain: string;
  ingest_target?: string | string[] | null;
  tom_depth?: string | null;
  retention_class: string;
  importance_score: number;
  cognition_eligible: boolean;
  level?: string | null;
  media_path?: string | null;
  deleted_at?: number | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PaginationParams {
  limit?: number;
  offset?: number;
}

export interface L1EventQueryParams {
  limit?: number;
  offset?: number;
  event_type?: string;
  user_id?: string;
  session_id?: string;
  query?: string;
  source?: string;
  source_item_id?: string;
  idempotency_key?: string;
  start_date?: string;
  end_date?: string;
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
  user_feedback: string | null;
  user_feedback_at: number | null;
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
  batch_count?: number;
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
export interface MemoryAttention {
  pending_assertions: number;
  open_circuit_breakers: number;
}

export interface MemoryStatistics {
  identity?: { canonical_self_id: string; identity_link_count: number };
  l0: L0Stats;
  l1: { event_count: number; db_path?: string };
  l2: { relation_count: number; assertion_count: number; db_path?: string };
  l3: { summary_count: number; db_path?: string };
  l4: { skill_count: number; open_circuit_breakers: number; db_path?: string };
  total_memories?: number;
  disk_usage_bytes?: number;
  attention?: MemoryAttention;
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

type L0SessionsResponse = PaginatedResponse<L0Session> & { stats: L0Stats };
type L3SummariesParams = PaginationParams & { summary_type?: string; summary_category?: string };

const unwrapMemoryResponse = <T>(response: GatewayResponse<T>): T => unwrapGatewayPayload<T>(response);

// Legacy API object for backward compatibility
export const memoryApi = {
  // L0 Working Memory
  getL0Sessions: async (params?: PaginationParams & { status?: string; query?: string }): Promise<L0SessionsResponse> =>
    unwrapMemoryResponse(await api.get<L0SessionsResponse>('/memory/l0/sessions', { params })),
  getL0Workbench: async (sessionId: string): Promise<L0Workbench> =>
    unwrapMemoryResponse(await api.get<L0Workbench>(`/memory/l0/workbench/${sessionId}`)),

  // L1 Event Stream
  getL1Events: async (params?: L1EventQueryParams): Promise<PaginatedResponse<L1Event>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L1Event>>('/memory/l1/events', { params })),

  // L2 Cognition
  getL2Statistics: async (): Promise<L2Statistics> =>
    unwrapMemoryResponse(await api.get<L2Statistics>('/memory/l2/statistics')),
  getIdentityLinks: async (): Promise<MemoryIdentityLinksResponse> =>
    unwrapMemoryResponse(await api.get<MemoryIdentityLinksResponse>('/memory/identity/links')),
  getL2Relations: async (params?: PaginationParams): Promise<PaginatedResponse<L2Relation>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Relation>>('/memory/l2/relations', { params })),
  getL2Assertions: async (params?: PaginationParams): Promise<PaginatedResponse<L2Assertion>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Assertion>>('/memory/l2/assertions', { params })),
  submitAssertionFeedback: async (assertionId: string, feedback: 'confirmed' | 'rejected'): Promise<L2Assertion> =>
    unwrapMemoryResponse(await api.patch<L2Assertion>(`/memory/l2/assertions/${assertionId}/feedback`, { feedback })),
  correctAssertion: async (assertionId: string, newValue: string, reason?: string): Promise<L2Assertion> =>
    unwrapMemoryResponse(await api.post<L2Assertion>(`/memory/l2/assertions/${assertionId}/correct`, { new_value: newValue, reason })),
  getL2Entities: async (params?: PaginationParams): Promise<PaginatedResponse<L2Entity>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Entity>>('/memory/l2/entities', { params })),
  getL2Mentions: async (params?: PaginationParams): Promise<PaginatedResponse<L2Mention>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Mention>>('/memory/l2/mentions', { params })),
  getL2Snapshots: async (params?: PaginationParams): Promise<PaginatedResponse<L2Snapshot>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Snapshot>>('/memory/l2/snapshots', { params })),
  getL2ConflictRules: async (): Promise<L2GraphConflictRule[]> =>
    unwrapMemoryResponse(await api.get<L2GraphConflictRule[]>('/memory/l2/conflict-rules')),
  createManualL2Event: async (payload: ManualL2EventPayload): Promise<L2QueuedActionResponse> =>
    unwrapMemoryResponse(await api.post<L2QueuedActionResponse>('/memory/l2/manual-event', payload)),
  replayL2Extraction: async (eventId: string): Promise<L2QueuedActionResponse> =>
    unwrapMemoryResponse(await api.post<L2QueuedActionResponse>(`/memory/l2/extract/${eventId}`)),
  flushL2Microbatches: async (): Promise<L2QueuedActionResponse> =>
    unwrapMemoryResponse(await api.post<L2QueuedActionResponse>('/memory/l2/microbatch-flush')),
  reconcileL2Entities: async (entityIds: string[]): Promise<L2QueuedActionResponse> =>
    unwrapMemoryResponse(await api.post<L2QueuedActionResponse>('/memory/l2/reconcile', { entity_ids: entityIds })),
  refreshL2Snapshots: async (entityIds: string[]): Promise<L2QueuedActionResponse> =>
    unwrapMemoryResponse(await api.post<L2QueuedActionResponse>('/memory/l2/snapshot-refresh', { entity_ids: entityIds })),
  upsertL2ConflictRule: async (payload: L2GraphConflictRulePayload): Promise<L2GraphConflictRule> =>
    unwrapMemoryResponse(await api.put<L2GraphConflictRule>(`/memory/l2/conflict-rules/${payload.predicate}`, {
      opposite_predicates: payload.opposite_predicates,
      opposite_resolution: payload.opposite_resolution,
      exclusive_group: payload.exclusive_group ?? null,
      exclusive_scope: payload.exclusive_scope ?? 'same_subject',
      exclusive_resolution: payload.exclusive_resolution,
    })),

  // L3 Reflection
  getL3Summaries: async (params?: L3SummariesParams): Promise<PaginatedResponse<L3Summary>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L3Summary>>('/memory/l3/summaries', { params })),

  // L4 Procedural
  getL4Skills: async (params?: PaginationParams): Promise<PaginatedResponse<L4Skill>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L4Skill>>('/memory/procedures', { params })),

  // Statistics & Search
  getStatistics: async (): Promise<MemoryStatistics> =>
    unwrapMemoryResponse(await api.get<MemoryStatistics>('/memory/statistics')),
  search: async (query: string, options?: { limit?: number; query_mode?: string }): Promise<MemorySearchResultPayload> =>
    unwrapMemoryResponse(await api.post<MemorySearchResultPayload>('/memory/search', { query, limit: options?.limit ?? 20, query_mode: options?.query_mode ?? 'detail' })),

  // Clear
  clearAll: async (): Promise<ClearMemoryResponse> =>
    unwrapMemoryResponse(await api.delete<ClearMemoryResponse>('/memory/clear')),
};

export default memoryApi;
