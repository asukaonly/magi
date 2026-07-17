import { api, unwrapGatewayPayload } from '../client';
import type { GatewayResponse } from '../client';
import type { EmbeddingVectorIdentity, VectorLayerId } from './config';

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
  workspace_path?: string | null;
  message_count?: number | null;
  last_message_preview?: string | null;
  last_user_message_preview?: string | null;
  title_overridden?: boolean | null;
  history_version?: number | null;
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

export interface L0ContextSummary {
  summary_id: string;
  parent_summary_id?: string | null;
  status: string;
  summary_kind: string;
  persona_scope?: string | null;
  covered_from_message_id?: string | null;
  covered_to_message_id?: string | null;
  first_kept_message_id?: string | null;
  covered_to_sequence_no?: number | null;
  session_origin?: string | null;
  summary_text: string;
  prompt_profile?: string | null;
  model_provider?: string | null;
  model_id?: string | null;
  token_count_before?: number | null;
  token_count_after?: number | null;
  quality_status?: string | null;
  created_at_ms?: number | null;
  updated_at_ms?: number | null;
}

export interface L0ContextUsage {
  user_id?: string | null;
  session_id?: string | null;
  turn_id?: string | null;
  used_tokens: number;
  window_size: number;
  threshold?: number | null;
  timestamp?: number | null;
  notification_id?: number | null;
  created_at_ms?: number | null;
}

export interface L0Workbench {
  session: Record<string, unknown> | null;
  goal_stack: Array<Record<string, unknown>>;
  active_entities: Array<Record<string, unknown>>;
  temporary_tactics: Array<Record<string, unknown>>;
  active_context_summary?: L0ContextSummary | null;
  context_usage?: L0ContextUsage | null;
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
  metadata_json?: Record<string, unknown> | null;
  embedding_status?: string | null;
  embedding_profile_id?: string | null;
  embedding_chunk_count?: number | null;
  last_embedded_at?: number | null;
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

export type MemoryListQueryParams = PaginationParams & {
  query?: string;
  include_inactive?: boolean;
};

export interface L1EventQueryParams {
  limit?: number;
  offset?: number;
  event_id?: string;
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
  first_observed_at?: number;
  last_observed_at?: number;
  updated_at?: number;
  fact_kind?: string;
  scope?: Record<string, unknown> | null;
}

export interface L2AssertionConflictContext {
  kind?: 'superseded_by_assertion' | string;
  previous_assertion_id?: string | null;
  previous_value?: string | null;
  current_assertion_id?: string | null;
  current_value?: string | null;
}

export interface L2Assertion {
  assertion_id: string;
  entity_id: string;
  entity_type: string;
  trait_family?: string | null;
  trait_name: string;
  trait_value: string;
  trait_value_i18n?: 'literal' | 'controlled' | string | null;
  assertion_family_snapshot_bucket?: string | null;
  assertion_family_description?: string | null;
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
  created_at?: number | null;
  updated_at?: number | null;
  valid_from?: number | null;
  valid_to?: number | null;
  scope?: Record<string, unknown> | null;
  status?: string | null;
  superseded_by?: string | null;
  superseded_at?: number | null;
  conflict_context?: L2AssertionConflictContext | null;
}

export type MemoryCorrectionTargetKind = 'assertion' | 'edge';
export type MemoryCorrectionKind = 'record_error' | 'situation_changed' | 'scope_refinement';
export type MemoryCorrectionState = 'active' | 'reverted';
export type MemoryCorrectionDerivationState = 'pending' | 'running' | 'completed' | 'failed';
export type MemoryCorrectionContextDimension = 'project' | 'activity' | 'place' | 'person' | 'time';
export type MemoryCorrectionWritableContextDimension = 'project';

export interface MemoryCorrectionContextCondition<
  Dimension extends MemoryCorrectionContextDimension = MemoryCorrectionContextDimension,
> {
  dimension: Dimension;
  context_id: string;
}

export interface MemoryCorrectionScope<
  Dimension extends MemoryCorrectionContextDimension = MemoryCorrectionContextDimension,
> {
  all_of: MemoryCorrectionContextCondition<Dimension>[];
}

export interface MemoryCorrectionTarget {
  kind: MemoryCorrectionTargetKind;
  id: string;
}

export interface MemoryCorrectionRequest {
  request_id: string;
  target: MemoryCorrectionTarget;
  correction_kind: MemoryCorrectionKind;
  replacement?: Record<string, unknown> | null;
  reason?: string | null;
  effective_at?: number | null;
  scope?: MemoryCorrectionScope<MemoryCorrectionWritableContextDimension> | null;
  source_event_id?: string | null;
  expected_updated_at?: number | null;
}

export interface MemoryCorrectionClaimValue {
  value?: unknown;
  trait_value?: unknown;
  subject_id?: string | null;
  subject_type?: string | null;
  predicate?: string | null;
  object_id?: string | null;
  object_type?: string | null;
  fact_kind?: string | null;
  status?: string | null;
  validation_state?: string | null;
  scope?: MemoryCorrectionScope | null;
}

export interface MemoryCorrectionRecord {
  correction_id: string;
  correction_kind: MemoryCorrectionKind;
  before?: MemoryCorrectionClaimValue | null;
  created_at: number;
  state: MemoryCorrectionState;
  reason?: string | null;
  replacement?: MemoryCorrectionClaimValue | null;
  effective_at?: number | null;
  scope?: MemoryCorrectionScope | null;
  transition_applied_at?: number | null;
  transition_cancelled_at?: number | null;
  target_forgotten?: boolean;
  forget_affected?: boolean;
  content_redacted?: boolean;
  can_revert?: boolean;
}

export interface MemoryCorrectionVersion {
  trait_value?: unknown;
  subject_id?: string | null;
  subject_type?: string | null;
  predicate?: string | null;
  object_id?: string | null;
  object_type?: string | null;
  status?: string | null;
  validation_state?: string | null;
  valid_from?: number | null;
  valid_to?: number | null;
  first_inferred_at?: number | null;
  first_observed_at?: number | null;
  created_at?: number | null;
  scope?: MemoryCorrectionScope | null;
}

export interface MemoryCorrectionCommandResponse {
  correction: MemoryCorrectionRecord;
  current_claim?: MemoryCorrectionClaimValue | null;
  subject_revision?: number | null;
  derivation_state: MemoryCorrectionDerivationState;
  created: boolean;
}

export interface MemoryCorrectionHistoryResponse {
  target: MemoryCorrectionTarget;
  versions: MemoryCorrectionVersion[];
  corrections: MemoryCorrectionRecord[];
  context_labels: Record<string, string>;
}

export interface MemoryCorrectionContextOption {
  context_id: string;
  dimension: 'project';
  label: string;
}

export interface MemoryCorrectionContextOptionsResponse {
  items: MemoryCorrectionContextOption[];
}

export interface L2Entity {
  entity_id: string;
  canonical_name: string;
  entity_type: string;
  created_at?: number | null;
  updated_at?: number | null;
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
  current_context?: Record<string, unknown>;
  current_stress_level?: number;
  current_mood?: string | null;
  current_engagement?: number;
  interaction_count?: number;
  last_interaction_at?: number | null;
  last_updated_at?: number;
  emerging_signals?: Array<Record<string, unknown>>;
}

export interface L2Episode {
  episode_id: string;
  episode_type?: string;
  status?: string;
  time_start?: number;
  time_end?: number;
  label?: string | null;
  summary?: string | null;
  dominant_mode?: string | null;
  source_event_count?: number;
  confidence?: number | null;
  parent_episode_id?: string | null;
  slice_narrative?: string | null;
  slice_sensory_detail?: string | null;
  magi_standout?: boolean | null;
  standout_score?: number | null;
  standout_reason?: string | null;
  representative_asset_ref?: string | null;
  user_label?: string | null;
  user_note?: string | null;
  user_pinned?: boolean;
  primary_entity_ids?: string[] | null;
  primary_entities?: L2EpisodeEntityPreview[] | null;
  primary_place_ids?: string[] | null;
  primary_topic_keys?: string[] | null;
  continuity_signals?: string[] | null;
  formation_method?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
}

export interface L2EpisodeEntityPreview {
  id: string;
  name: string;
  type?: string | null;
}

export interface L2EpisodeSummary {
  summary_id: string;
  content: string;
  label: string;
  updated_at: number | null;
  is_fallback: boolean;
}

export interface L2EpisodeWithSummary extends L2Episode {
  episode_summary?: L2EpisodeSummary | null;
  display_title?: string;
  display_description?: string;
  display_source?: 'user_override' | 'generated' | 'fallback' | string;
}

export interface L2Experience {
  experience_id: string;
  status?: string;
  title?: string | null;
  experience_type?: string | null;
  intent?: string | null;
  outcome?: string | null;
  magi_interpretation?: string | null;
  time_start?: number | null;
  time_end?: number | null;
  narrative_score?: number | null;
  primary_entity_ids?: string[] | null;
  primary_entities?: L2EpisodeEntityPreview[] | null;
  primary_place_ids?: string[] | null;
  primary_topic_keys?: string[] | null;
  source_episode_count?: number;
  source_event_count?: number;
  parent_experience_id?: string | null;
  merged_into_experience_id?: string | null;
  user_label?: string | null;
  user_note?: string | null;
  user_cover_asset_ref?: string | null;
  user_pinned?: boolean;
  created_at?: number | null;
  updated_at?: number | null;
  last_recomputed_at?: number | null;
  chapters?: ExperienceDraftChapter[] | null;
}

export interface L2ExperienceWithReview extends L2Experience {
  experience_review?: L2EpisodeSummary | null;
  display_title?: string;
  display_description?: string;
  display_source?: 'user_override' | 'generated' | 'fallback' | string;
}

export interface L2ExperienceSeed {
  seed_id: string;
  seed_type?: 'manual' | 'project' | 'repeated_goal' | string;
  status?: 'candidate' | 'accepted' | 'rejected' | 'promoted' | 'stale' | string;
  title?: string | null;
  description?: string | null;
  anchor_entity_ids?: string[] | null;
  anchor_place_ids?: string[] | null;
  anchor_topic_keys?: string[] | null;
  time_start?: number | null;
  time_end?: number | null;
  confidence?: number | null;
  evidence_count?: number;
  display_title?: string;
  display_description?: string;
  display_tags?: string[];
  promoted_experience_id?: string | null;
  created_at?: number | null;
  updated_at?: number | null;
  last_evaluated_at?: number | null;
}

export interface ExperienceSeedPromotionResponse {
  seed_id: string;
  seed?: L2ExperienceSeed | null;
  promoted_experience_id?: string | null;
  experience?: L2ExperienceReviewDetail | null;
}

export interface ExperienceSeedCreatePayload {
  episode_ids?: string[];
  event_ids?: string[];
  title_hint?: string | null;
  promote_now?: boolean;
}

export interface ExperienceDraftEvidence {
  ref_type: 'episode' | 'event' | string;
  ref_id: string;
  title: string;
  summary: string;
  time_start?: number | null;
  time_end?: number | null;
  event_count?: number;
  reason?: string | null;
  restore_chapter?: {
    chapter_id: string;
    chapter_order: number;
    episode_ids: string[];
    event_ids: string[];
    event_count?: number;
  } | null;
}

export interface ExperienceDraftChapter {
  chapter_id: string;
  draft_order?: number;
  title: string;
  summary: string;
  time_start?: number | null;
  time_end?: number | null;
  episode_ids: string[];
  event_ids: string[];
  event_count?: number;
}

export interface ExperienceDraft {
  draft_id: string;
  status: 'editing' | 'completed' | 'discarded' | string;
  query_text: string;
  title: string;
  one_sentence_review: string;
  time_start: number;
  time_end: number;
  chapters: ExperienceDraftChapter[];
  possible_evidence: ExperienceDraftEvidence[];
  excluded_evidence: ExperienceDraftEvidence[];
  user_cover_asset_ref?: string | null;
  created_experience_id?: string | null;
  created_at: number;
  updated_at: number;
}

export interface ExperienceDraftChoice {
  choice_id: string;
  time_start: number;
  time_end: number;
  event_count: number;
  preview: string;
}

export interface ExperienceDraftOrganizeResponse {
  status: 'draft' | 'ambiguous' | 'insufficient';
  draft?: ExperienceDraft | null;
  choices: ExperienceDraftChoice[];
  message?: string | null;
}

export interface ExperienceDraftUpdatePayload {
  title?: string;
  one_sentence_review?: string;
  time_start?: number;
  time_end?: number;
  chapters?: ExperienceDraftChapter[];
  possible_evidence?: ExperienceDraftEvidence[];
  excluded_evidence?: ExperienceDraftEvidence[];
}

export interface L2ExperienceSourceEpisode extends L2EpisodeWithSummary {
  membership_role?: string | null;
  membership_confidence?: number | null;
  membership_added_at?: number | null;
}

export interface L2EpisodeEvent {
  episode_id: string;
  event_id: string;
  membership_role: string;
  membership_confidence: number;
  added_at: number | null;
}

export interface L2EpisodeEventPreview extends L2EpisodeEvent {
  timestamp?: number | null;
  event_type?: string | null;
  source?: string | null;
  content_preview?: string | null;
  candidate_score?: number;
  candidate_reasons?: string[];
}

export interface L2EpisodeInference {
  assertion_id: string;
  entity_id: string;
  entity_type: string;
  trait_family?: string | null;
  trait_name: string;
  trait_value: string;
  confidence_score: number;
  natural_summary: string;
  validation_state?: string | null;
  user_feedback: 'confirmed' | 'rejected' | string | null;
  evidence_events: string[];
}

export interface L2EpisodeDetail extends L2Episode {
  events: L2EpisodeEvent[];
  inferred: L2EpisodeInference[];
}

export interface L2EpisodeReviewDetail extends Omit<L2EpisodeDetail, 'events'> {
  episode_summary?: L2EpisodeSummary | null;
  display_title?: string;
  display_description?: string;
  display_source?: 'user_override' | 'generated' | 'fallback' | string;
  events: L2EpisodeEventPreview[];
}

export interface L2ExperienceReviewDetail extends L2ExperienceWithReview {
  source_episodes: L2ExperienceSourceEpisode[];
  events: L2EpisodeEventPreview[];
  key_events?: L2EpisodeEventPreview[];
}

export interface L2EpisodeCandidate extends L2EpisodeWithSummary {
  candidate_score: number;
  candidate_reasons: string[];
}

export interface L2EpisodeSplitSide {
  event_count: number;
  time_start?: number | null;
  time_end?: number | null;
  events: L2EpisodeEventPreview[];
  display_title?: string;
  display_description?: string;
}

export interface L2EpisodeSplitPreview {
  left: L2EpisodeSplitSide;
  right: L2EpisodeSplitSide;
}

export interface EpisodeReconsolidateResult {
  promoted: number;
  standouts: number;
  merged: number;
  invalidated: number;
  summaries_generated: number;
  summary_errors: string[];
  experience_candidates?: number;
  experiences_promoted?: number;
  experience_duplicates?: number;
  experience_rejected?: number;
  experience_summaries_generated?: number;
  experience_summary_errors?: string[];
}

export interface EpisodeAnnotationPayload {
  user_label?: string;
  user_note?: string;
  user_pinned?: boolean;
}

export type ExperienceAnnotationPayload = EpisodeAnnotationPayload;

export interface ForgetEpisodeResponse {
  episode_id: string;
  event_ids: string[];
  l1_events_deleted: number;
}

export interface DeleteL1EventResponse {
  event_id: string;
  deleted: boolean;
  deletion_scope?: 'projected_memory_only' | 'source_event';
}

export interface ForgetEntityResponse {
  l2_counts: Record<string, number>;
  l1_events_deleted: number;
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
export interface L3ChangeAndPattern {
  timeline?: string[];
  source_signals?: string[];
  decisions_and_actions?: string[];
  changes?: string[];
  patterns?: string[];
  open_threads?: string[];
  [key: string]: string[] | string | number | boolean | null | undefined;
}

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
  change_and_pattern?: L3ChangeAndPattern | null;
  source_event_ids?: string[];
  source_event_count: number;
  importance_aggregate?: number;
  event_type_distribution?: Record<string, number>;
  generated_by_model?: string | null;
  insight_key?: string | null;
  review_state?: string | null;
  insight_metadata?: Record<string, unknown>;
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

export interface MemorySourceCount {
  source: string;
  event_count: number;
  avg_importance: number;
  first_event_at: number | null;
  last_event_at: number | null;
}

export interface MemoryEmbeddingBacklog {
  pending: number;
  worker_running: boolean;
  vector_enabled: boolean;
  async_embeddings: boolean;
}

export interface MemoryL2ProcessingBacklog {
  extract_pending: number;
  reconcile_pending: number;
  snapshot_pending: number;
  projection_pending: number;
  projection_claimed: number;
  projection_failed: number;
}

export interface MemoryProcessingBacklog {
  all_idle: boolean;
  total_pending: number;
  l2: MemoryL2ProcessingBacklog;
  l1_embeddings: MemoryEmbeddingBacklog;
  l3_embeddings: MemoryEmbeddingBacklog;
  l4_embeddings: MemoryEmbeddingBacklog;
}

export interface MemoryDashboardDeltaWindow {
  total_memories: number;
  l1_events: number;
  l2_assertions: number;
  l3_summaries: number;
  disk_usage_bytes: number | null;
}

export interface MemoryDashboardDeltas {
  today: MemoryDashboardDeltaWindow;
}

export interface MemoryDashboard {
  statistics: MemoryStatistics;
  source_counts: MemorySourceCount[];
  attention: MemoryAttention;
  processing_backlog: MemoryProcessingBacklog;
  deltas: MemoryDashboardDeltas;
  pending_assertions: PaginatedResponse<L2Assertion>;
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

export type EmbeddingRebuildJobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface EmbeddingRebuildJobLayer {
  layer: VectorLayerId;
  status: EmbeddingRebuildJobStatus;
  total_items: number;
  processed_items: number;
  succeeded_items: number;
  failed_items: number;
  error?: string | null;
  started_at?: number | null;
  finished_at?: number | null;
  updated_at: number;
}

export interface EmbeddingRebuildJob {
  job_id: string;
  status: EmbeddingRebuildJobStatus;
  requested_layers: VectorLayerId[];
  active_layer?: VectorLayerId | null;
  total_items: number;
  processed_items: number;
  succeeded_items: number;
  failed_items: number;
  cancel_requested: boolean;
  error?: string | null;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  updated_at: number;
  terminal: boolean;
  layers: EmbeddingRebuildJobLayer[];
}

export interface EmbeddingVectorStatus {
  ready_counts: Record<VectorLayerId, number>;
  ready_total: number;
  active_identities: Record<VectorLayerId, EmbeddingVectorIdentity | null>;
  latest_job?: EmbeddingRebuildJob | null;
}

export interface MemorySearchResultPayload {
  l0_workbench: Array<Record<string, unknown>>;
  l1_events: Array<Record<string, unknown>>;
  l1_evidence_bundles?: Array<Record<string, unknown>>;
  l1_timeline_summary?: Array<Record<string, unknown>>;
  l2_entity_cards: Array<Record<string, unknown>>;
  l2_relationships: Array<Record<string, unknown>>;
  l2_assertions?: Array<Record<string, unknown>>;
  l2_episodes?: Array<Record<string, unknown>>;
  l2_experiences?: Array<Record<string, unknown>>;
  l2_state_facts?: Array<Record<string, unknown>>;
  l2_state_history?: Array<Record<string, unknown>>;
  l3_reflections: Array<Record<string, unknown>>;
  l4_procedures: Array<Record<string, unknown>>;
  structured_results?: Array<Record<string, unknown>>;
  trace: Record<string, unknown>;
}

export type MemorySearchQueryMode =
  | 'event_stream'
  | 'exact_fact'
  | 'current_state'
  | 'episode_recall'
  | 'summary'
  | 'strategy';

type L0SessionsResponse = PaginatedResponse<L0Session> & { stats: L0Stats };
type L3SummariesParams = MemoryListQueryParams & { summary_type?: string; summary_category?: string };

const unwrapMemoryResponse = <T>(response: GatewayResponse<T>): T => unwrapGatewayPayload<T>(response);

// Memory API client
export const memoryApi = {
  // L0 Working Memory
  getL0Sessions: async (params?: PaginationParams & { status?: string; query?: string }): Promise<L0SessionsResponse> =>
    unwrapMemoryResponse(await api.get<L0SessionsResponse>('/memory/l0/sessions', { params })),
  getL0Workbench: async (sessionId: string): Promise<L0Workbench> =>
    unwrapMemoryResponse(await api.get<L0Workbench>(`/memory/l0/workbench/${sessionId}`)),

  // L1 Event Stream
  getL1Events: async (params?: L1EventQueryParams): Promise<PaginatedResponse<L1Event>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L1Event>>('/memory/l1/events', { params })),
  deleteL1Event: async (eventId: string): Promise<DeleteL1EventResponse> =>
    unwrapMemoryResponse(await api.delete<DeleteL1EventResponse>(`/memory/l1/events/${eventId}`)),

  // L2 Cognition
  getL2Statistics: async (): Promise<L2Statistics> =>
    unwrapMemoryResponse(await api.get<L2Statistics>('/memory/l2/statistics')),
  getIdentityLinks: async (): Promise<MemoryIdentityLinksResponse> =>
    unwrapMemoryResponse(await api.get<MemoryIdentityLinksResponse>('/memory/identity/links')),
  getL2Relations: async (params?: MemoryListQueryParams): Promise<PaginatedResponse<L2Relation>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Relation>>('/memory/l2/relations', { params })),
  getL2Assertions: async (params?: MemoryListQueryParams): Promise<PaginatedResponse<L2Assertion>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Assertion>>('/memory/l2/assertions', { params })),
  submitAssertionFeedback: async (assertionId: string, feedback: 'confirmed'): Promise<L2Assertion> =>
    unwrapMemoryResponse(await api.patch<L2Assertion>(`/memory/l2/assertions/${assertionId}/feedback`, { feedback })),
  applyCorrection: async (payload: MemoryCorrectionRequest): Promise<MemoryCorrectionCommandResponse> =>
    unwrapMemoryResponse(await api.post<MemoryCorrectionCommandResponse>('/memory/l2/corrections', payload)),
  getCorrectionHistory: async (
    targetKind: MemoryCorrectionTargetKind,
    targetId: string,
  ): Promise<MemoryCorrectionHistoryResponse> =>
    unwrapMemoryResponse(await api.get<MemoryCorrectionHistoryResponse>('/memory/l2/corrections', {
      params: { target_kind: targetKind, target_id: targetId },
    })),
  getCorrectionContextOptions: async (): Promise<MemoryCorrectionContextOptionsResponse> =>
    unwrapMemoryResponse(await api.get<MemoryCorrectionContextOptionsResponse>('/memory/l2/context-options')),
  revertCorrection: async (correctionId: string, requestId: string): Promise<MemoryCorrectionCommandResponse> =>
    unwrapMemoryResponse(await api.post<MemoryCorrectionCommandResponse>(
      `/memory/l2/corrections/${encodeURIComponent(correctionId)}/revert`,
      { request_id: requestId },
    )),
  getL2Entities: async (params?: MemoryListQueryParams): Promise<PaginatedResponse<L2Entity>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Entity>>('/memory/l2/entities', { params })),
  getL2Mentions: async (params?: PaginationParams): Promise<PaginatedResponse<L2Mention>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2Mention>>('/memory/l2/mentions', { params })),
  getL2Snapshots: async (params?: MemoryListQueryParams): Promise<PaginatedResponse<L2Snapshot>> =>
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
  listEpisodes: async (params?: PaginationParams & {
    episode_type?: string;
    status?: string;
    surface?: 'standout';
  }): Promise<PaginatedResponse<L2EpisodeWithSummary>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2EpisodeWithSummary>>('/memory/l2/episodes', { params })),
  listExperiences: async (params?: PaginationParams & {
    status?: string;
    time_start?: number;
    time_end?: number;
  }): Promise<PaginatedResponse<L2ExperienceWithReview>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2ExperienceWithReview>>('/memory/l2/experiences', { params })),
  listExperienceSeeds: async (params?: PaginationParams & {
    status?: string;
  }): Promise<PaginatedResponse<L2ExperienceSeed>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L2ExperienceSeed>>('/memory/l2/experience-seeds', { params })),
  createExperienceSeed: async (payload: ExperienceSeedCreatePayload): Promise<ExperienceSeedPromotionResponse> =>
    unwrapMemoryResponse(await api.post<ExperienceSeedPromotionResponse>('/memory/l2/experience-seeds', {
      episode_ids: payload.episode_ids ?? [],
      event_ids: payload.event_ids ?? [],
      title_hint: payload.title_hint ?? null,
      promote_now: payload.promote_now ?? false,
    })),
  listExperienceDrafts: async (params?: PaginationParams & { status?: string }): Promise<PaginatedResponse<ExperienceDraft>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<ExperienceDraft>>('/memory/l2/experience-drafts', { params })),
  organizeExperienceDraft: async (payload: {
    query_text: string;
    time_start?: number;
    time_end?: number;
  }): Promise<ExperienceDraftOrganizeResponse> =>
    unwrapMemoryResponse(await api.post<ExperienceDraftOrganizeResponse>('/memory/l2/experience-drafts/organize', payload)),
  getExperienceDraft: async (draftId: string): Promise<ExperienceDraft> =>
    unwrapMemoryResponse(await api.get<ExperienceDraft>(`/memory/l2/experience-drafts/${draftId}`)),
  updateExperienceDraft: async (draftId: string, payload: ExperienceDraftUpdatePayload): Promise<ExperienceDraft> =>
    unwrapMemoryResponse(await api.patch<ExperienceDraft>(`/memory/l2/experience-drafts/${draftId}`, payload)),
  uploadExperienceDraftCover: async (draftId: string, file: File): Promise<ExperienceDraft> => {
    const formData = new FormData();
    formData.append('file', file);
    return unwrapMemoryResponse(await api.post<ExperienceDraft>(
      `/memory/l2/experience-drafts/${draftId}/cover`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ));
  },
  createExperienceFromDraft: async (draftId: string): Promise<{
    draft_id: string;
    experience_id: string;
    experience?: L2ExperienceReviewDetail | null;
  }> => unwrapMemoryResponse(await api.post(`/memory/l2/experience-drafts/${draftId}/create`)),
  promoteExperienceSeed: async (seedId: string): Promise<ExperienceSeedPromotionResponse> =>
    unwrapMemoryResponse(await api.post<ExperienceSeedPromotionResponse>(`/memory/l2/experience-seeds/${seedId}/promote`)),
  rejectExperienceSeed: async (seedId: string): Promise<{ seed_id: string; seed?: L2ExperienceSeed | null }> =>
    unwrapMemoryResponse(await api.post<{ seed_id: string; seed?: L2ExperienceSeed | null }>(`/memory/l2/experience-seeds/${seedId}/reject`)),
  getExperience: async (experienceId: string): Promise<L2ExperienceReviewDetail> =>
    unwrapMemoryResponse(await api.get<L2ExperienceReviewDetail>(`/memory/l2/experiences/${experienceId}`)),
  annotateExperience: async (experienceId: string, payload: ExperienceAnnotationPayload): Promise<L2ExperienceReviewDetail> =>
    unwrapMemoryResponse(await api.patch<L2ExperienceReviewDetail>(`/memory/l2/experiences/${experienceId}`, payload)),
  uploadExperienceCover: async (experienceId: string, file: File): Promise<L2ExperienceReviewDetail> => {
    const formData = new FormData();
    formData.append('file', file);
    return unwrapMemoryResponse(await api.post<L2ExperienceReviewDetail>(
      `/memory/l2/experiences/${experienceId}/cover`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    ));
  },
  regenerateExperienceReview: async (experienceId: string): Promise<L2ExperienceReviewDetail> =>
    unwrapMemoryResponse(await api.post<L2ExperienceReviewDetail>(`/memory/l2/experiences/${experienceId}/regenerate`)),
  hideExperience: async (experienceId: string): Promise<L2ExperienceReviewDetail> =>
    unwrapMemoryResponse(await api.post<L2ExperienceReviewDetail>(`/memory/l2/experiences/${experienceId}/hide`)),
  getEpisode: async (episodeId: string): Promise<L2EpisodeReviewDetail> =>
    unwrapMemoryResponse(await api.get<L2EpisodeReviewDetail>(`/memory/l2/episodes/${episodeId}`)),
  regenerateEpisode: async (episodeId: string): Promise<L2EpisodeReviewDetail> =>
    unwrapMemoryResponse(await api.post<L2EpisodeReviewDetail>(`/memory/l2/episodes/${episodeId}/regenerate`)),
  listEpisodeEventCandidates: async (episodeId: string): Promise<{ items: L2EpisodeEventPreview[] }> =>
    unwrapMemoryResponse(await api.get<{ items: L2EpisodeEventPreview[] }>(`/memory/l2/episodes/${episodeId}/event-candidates`)),
  addEpisodeEvents: async (episodeId: string, eventIds: string[]): Promise<L2EpisodeReviewDetail> =>
    unwrapMemoryResponse(await api.post<L2EpisodeReviewDetail>(`/memory/l2/episodes/${episodeId}/events`, { event_ids: eventIds })),
  removeEpisodeEvents: async (episodeId: string, eventIds: string[]): Promise<L2EpisodeReviewDetail> =>
    unwrapMemoryResponse(await api.delete<L2EpisodeReviewDetail>(`/memory/l2/episodes/${episodeId}/events`, { data: { event_ids: eventIds } })),
  listEpisodeMergeCandidates: async (episodeId: string): Promise<{ items: L2EpisodeCandidate[] }> =>
    unwrapMemoryResponse(await api.get<{ items: L2EpisodeCandidate[] }>(`/memory/l2/episodes/${episodeId}/merge-candidates`)),
  previewEpisodeSplit: async (episodeId: string, breakAfterEventId: string): Promise<L2EpisodeSplitPreview> =>
    unwrapMemoryResponse(await api.post<L2EpisodeSplitPreview>(`/memory/l2/episodes/${episodeId}/split-preview`, {
      break_after_event_id: breakAfterEventId,
    })),
  splitEpisode: async (episodeId: string, breakAfterEventId: string): Promise<{ items: L2EpisodeReviewDetail[] }> =>
    unwrapMemoryResponse(await api.post<{ items: L2EpisodeReviewDetail[] }>(`/memory/l2/episodes/${episodeId}/split`, {
      break_after_event_id: breakAfterEventId,
    })),
  reconsolidateEpisodes: async (): Promise<EpisodeReconsolidateResult> =>
    unwrapMemoryResponse(await api.post<EpisodeReconsolidateResult>('/memory/l2/episodes/reconsolidate')),
  annotateEpisode: async (episodeId: string, payload: EpisodeAnnotationPayload): Promise<L2Episode> =>
    unwrapMemoryResponse(await api.patch<L2Episode>(`/memory/l2/episodes/${episodeId}`, payload)),
  mergeEpisodes: async (episodeId: string, absorbedId: string): Promise<L2EpisodeReviewDetail> =>
    unwrapMemoryResponse(await api.post<L2EpisodeReviewDetail>(`/memory/l2/episodes/${episodeId}/merge`, { absorbed_id: absorbedId })),
  forgetEpisode: async (episodeId: string, deleteEvents = false): Promise<ForgetEpisodeResponse> =>
    unwrapMemoryResponse(await api.post<ForgetEpisodeResponse>('/memory/forget/episode', {
      episode_id: episodeId,
      delete_events: deleteEvents,
    })),
  forgetEntity: async (entityId: string, deleteL1Events = false): Promise<ForgetEntityResponse> =>
    unwrapMemoryResponse(await api.post<ForgetEntityResponse>('/memory/forget/entity', {
      entity_id: entityId,
      delete_l1_events: deleteL1Events,
    })),
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
  getL4Skills: async (params?: MemoryListQueryParams): Promise<PaginatedResponse<L4Skill>> =>
    unwrapMemoryResponse(await api.get<PaginatedResponse<L4Skill>>('/memory/procedures', { params })),

  // Statistics & Search
  getDashboard: async (params?: { pending_limit?: number }): Promise<MemoryDashboard> =>
    unwrapMemoryResponse(await api.get<MemoryDashboard>('/memory/dashboard', { params })),
  getStatistics: async (): Promise<MemoryStatistics> =>
    unwrapMemoryResponse(await api.get<MemoryStatistics>('/memory/statistics')),
  getEmbeddingVectorStatus: async (): Promise<EmbeddingVectorStatus> =>
    unwrapMemoryResponse(await api.get<EmbeddingVectorStatus>('/memory/embeddings/status')),
  startEmbeddingRebuild: async (layers?: VectorLayerId[]): Promise<EmbeddingRebuildJob> =>
    unwrapMemoryResponse(await api.post<EmbeddingRebuildJob>('/memory/embeddings/rebuild', { layers })),
  getEmbeddingRebuildJob: async (jobId: string): Promise<EmbeddingRebuildJob> =>
    unwrapMemoryResponse(await api.get<EmbeddingRebuildJob>(`/memory/embeddings/rebuild/${jobId}`)),
  cancelEmbeddingRebuild: async (jobId: string): Promise<EmbeddingRebuildJob> =>
    unwrapMemoryResponse(await api.post<EmbeddingRebuildJob>(`/memory/embeddings/rebuild/${jobId}/cancel`)),
  search: async (query: string, options?: { limit?: number; query_mode?: MemorySearchQueryMode }): Promise<MemorySearchResultPayload> => {
    const payload: { query: string; limit: number; query_mode?: MemorySearchQueryMode } = {
      query,
      limit: options?.limit ?? 20,
    };
    if (options?.query_mode) {
      payload.query_mode = options.query_mode;
    }
    return unwrapMemoryResponse(await api.post<MemorySearchResultPayload>('/memory/search', payload));
  },

  // Clear
  clearAll: async (): Promise<ClearMemoryResponse> =>
    unwrapMemoryResponse(await api.delete<ClearMemoryResponse>('/memory/clear')),
};

export default memoryApi;
