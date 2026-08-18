import type { TFunction } from 'i18next';

import { toApiClientError, type ApiClientError } from '@/api/client';
import type { MemoryPortabilityTimestamp } from '@/api/modules/memoryPortability';

const ERROR_KEY_BY_CODE: Record<string, string> = {
  memory_portability_busy: 'busy',
  portability_busy: 'busy',
  operation_in_progress: 'busy',
  candidate_in_use: 'busy',
  restore_runtime_busy: 'busy',
  memory_portability_destination_invalid: 'destinationInvalid',
  destination_invalid: 'destinationInvalid',
  output_directory_invalid: 'destinationInvalid',
  local_path_invalid: 'destinationInvalid',
  backup_filename_invalid: 'destinationInvalid',
  memory_portability_insufficient_space: 'insufficientSpace',
  insufficient_space: 'insufficientSpace',
  free_space_unknown: 'spaceCheckFailed',
  memory_portability_password_required: 'passwordRequired',
  password_required: 'passwordRequired',
  backup_requires_password: 'passwordRequired',
  memory_portability_wrong_password: 'wrongPassword',
  wrong_password: 'wrongPassword',
  decryption_failed: 'wrongPassword',
  password_or_integrity_invalid: 'wrongPassword',
  invalid_password: 'passwordInvalid',
  password_invalid: 'passwordInvalid',
  password_too_long: 'passwordInvalid',
  password_not_allowed: 'passwordInvalid',
  memory_portability_corrupt: 'corruptBackup',
  corrupt_backup: 'corruptBackup',
  backup_corrupt: 'corruptBackup',
  backup_inspection_failed: 'corruptBackup',
  manifest_invalid: 'corruptBackup',
  backup_manifest_invalid: 'corruptBackup',
  backup_archive_invalid: 'corruptBackup',
  backup_asset_invalid: 'corruptBackup',
  backup_assets_invalid: 'corruptBackup',
  backup_counts_invalid: 'corruptBackup',
  backup_member_count_invalid: 'corruptBackup',
  backup_member_duplicate: 'corruptBackup',
  backup_member_invalid: 'corruptBackup',
  backup_members_invalid: 'corruptBackup',
  backup_record_count_invalid: 'corruptBackup',
  backup_scope_invalid: 'corruptBackup',
  backup_size_invalid: 'corruptBackup',
  database_invalid: 'corruptBackup',
  candidate_integrity_invalid: 'corruptBackup',
  candidate_integrity_missing: 'corruptBackup',
  restore_file_invalid: 'corruptBackup',
  memory_portability_checksum_mismatch: 'checksumMismatch',
  checksum_mismatch: 'checksumMismatch',
  backup_checksum_invalid: 'checksumMismatch',
  backup_integrity_failed: 'checksumMismatch',
  backup_changed: 'checksumMismatch',
  restore_file_changed: 'checksumMismatch',
  candidate_changed: 'candidateChanged',
  memory_portability_unsupported_format: 'unsupportedFormat',
  unsupported_format: 'unsupportedFormat',
  backup_archive_unsupported: 'unsupportedFormat',
  backup_compression_invalid: 'unsupportedFormat',
  backup_version_unsupported: 'unsupportedFormat',
  backup_format_invalid: 'unsupportedFormat',
  backup_zip64_unsupported: 'unsupportedFormat',
  encryption_mode_invalid: 'unsupportedFormat',
  encryption_parameters_invalid: 'unsupportedFormat',
  encryption_state_invalid: 'unsupportedFormat',
  memory_portability_unsupported_schema: 'unsupportedSchema',
  unsupported_schema: 'unsupportedSchema',
  archive_schema_invalid: 'unsupportedSchema',
  database_schema_invalid: 'unsupportedSchema',
  schema_revision_mismatch: 'unsupportedSchema',
  schema_revision_missing: 'unsupportedSchema',
  schema_revision_unsupported: 'unsupportedSchema',
  schema_upgrade_failed: 'unsupportedSchema',
  schema_validation_failed: 'unsupportedSchema',
  memory_portability_incomplete: 'incompleteBackup',
  incomplete_backup: 'incompleteBackup',
  backup_asset_too_large: 'backupTooLarge',
  backup_too_large: 'backupTooLarge',
  managed_asset_too_large: 'backupTooLarge',
  backup_unreadable: 'sourceUnavailable',
  restore_file_unavailable: 'sourceUnavailable',
  managed_asset_changed: 'sourceUnavailable',
  managed_asset_invalid: 'sourceUnavailable',
  managed_asset_missing: 'sourceUnavailable',
  managed_source_invalid: 'sourceUnavailable',
  managed_source_unreadable: 'sourceUnavailable',
  memory_runtime_unavailable: 'runtimeUnavailable',
  archive_runtime_stale: 'archiveRuntimeStale',
  archive_runtime_unavailable: 'archiveUnavailable',
  archive_target_invalid: 'archiveUnavailable',
  output_exists: 'outputExists',
  backup_package_failed: 'writeFailed',
  backup_write_failed: 'writeFailed',
  export_write_failed: 'writeFailed',
  export_data_invalid: 'exportFailed',
  export_schema_mismatch: 'exportFailed',
  snapshot_failed: 'exportFailed',
  snapshot_incomplete: 'exportFailed',
  memory_portability_candidate_expired: 'candidateExpired',
  candidate_expired: 'candidateExpired',
  candidate_unavailable: 'candidateExpired',
  candidate_invalid: 'candidateExpired',
  operation_not_found: 'operationInterrupted',
  operation_cancelled: 'operationInterrupted',
  operation_interrupted: 'operationInterrupted',
  operation_failed: 'operationFailed',
  operation_state_write_failed: 'operationStateFailed',
  index_invalidation_failed: 'indexRebuildFailed',
  index_rebuild_failed: 'indexRebuildFailed',
  index_rebuild_queue_failed: 'indexRebuildFailed',
  restore_transaction_pending: 'restorePending',
  restore_commit_outcome_unknown: 'restoreOutcomeUnknown',
  memory_portability_restore_failed: 'restoreFailed',
  restore_failed: 'restoreFailed',
  restore_already_committed: 'restoreFailed',
  restore_journal_invalid: 'restoreFailed',
  restore_not_committed: 'restoreFailed',
  restore_not_ready_to_commit: 'restoreFailed',
  restore_rollback_snapshot_failed: 'restoreFailed',
  restore_runtime_recovery_failed: 'restoreFailed',
  restore_runtime_shutdown_failed: 'restoreFailed',
  restore_runtime_start_failed: 'restoreFailed',
  restore_runtime_unavailable: 'runtimeUnavailable',
  restore_safety_backup_invalid: 'restoreFailed',
  restore_staging_failed: 'restoreFailed',
  restore_staging_invalid: 'restoreFailed',
  restore_target_invalid: 'restoreFailed',
  restore_target_unavailable: 'restoreFailed',
  restore_transaction_changed: 'restoreFailed',
  memory_portability_rollback_failed: 'rollbackFailed',
  rollback_failed: 'rollbackFailed',
  restore_rollback_failed: 'rollbackFailed',
};

const RECORD_COUNT_KEY_ALIASES: Record<string, string> = {
  l0: 'l0',
  l0_sessions: 'l0Sessions',
  l0_attention: 'l0',
  l0_attention_items: 'l0',
  l1: 'l1',
  l1_events: 'l1',
  l2: 'l2',
  l2_entities: 'l2Entities',
  l2_relations: 'l2Relations',
  l2_relationships: 'l2Relations',
  l2_assertions: 'l2Assertions',
  l2_episodes: 'l2Episodes',
  l2_experiences: 'l2Experiences',
  l3: 'l3',
  l3_summaries: 'l3',
  l3_reflections: 'l3',
  l4: 'l4',
  l4_procedures: 'l4',
  l4_skills: 'l4',
  archive: 'archives',
  archives: 'archives',
  archive_files: 'archives',
  manual_assets: 'managedAssets',
  managed_assets: 'managedAssets',
  manual_entries: 'manualEntries',
  manual_entry_assets: 'managedAssets',
};

const SCOPE_KEY_ALIASES: Record<string, string> = {
  l0: 'l0',
  l1: 'l1',
  l2: 'l2',
  l3: 'l3',
  l4: 'l4',
  archives: 'archives',
  archive: 'archives',
  managed_assets: 'managedAssets',
  manual_assets: 'managedAssets',
  manual_entry_assets: 'managedAssets',
};

const PHASE_KEY_ALIASES: Record<string, string> = {
  queued: 'queued',
  preparing: 'preparing',
  snapshot: 'snapshot',
  snapshotting: 'snapshot',
  packaging: 'packaging',
  encrypting: 'encrypting',
  writing: 'writing',
  exporting: 'exporting',
  validating: 'validating',
  safety_backup: 'safetyBackup',
  shutting_down: 'shuttingDown',
  cutover: 'cutover',
  replacing: 'replacing',
  rebuilding_indexes: 'rebuildingIndexes',
  index_rebuild: 'rebuildingIndexes',
  restarting: 'restarting',
  finalizing: 'finalizing',
  complete: 'complete',
  completed: 'complete',
};

const INDEX_REBUILD_KEY_ALIASES: Record<string, string> = {
  pending: 'pending',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
  not_required: 'notRequired',
  skipped: 'notRequired',
};

const KNOWN_WARNING_KEYS = new Set([
  'chat_evidence_unavailable',
  'index_rebuild_required',
  'l0_not_restored',
  'restore_replaces_current_memory',
  'deleted_memories_may_return',
  'l0_runtime_attention_not_restored',
  'chat_records_and_attachments_not_included',
  'source_evidence_may_be_unavailable',
  'raw_history_import_content_redacted',
]);

function isApiClientError(value: unknown): value is ApiClientError {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<ApiClientError>;
  return typeof candidate.message === 'string'
    && typeof candidate.code === 'string'
    && typeof candidate.kind === 'string';
}

export function normalizePortabilityError(error: unknown): ApiClientError {
  return isApiClientError(error) ? error : toApiClientError(error);
}

export function isTransientPortabilityError(error: unknown): boolean {
  const clientError = normalizePortabilityError(error);
  return clientError.kind === 'backend-not-ready' || clientError.kind === 'network';
}

export function portabilityErrorMessage(t: TFunction<'app'>, error: unknown): string {
  const clientError = normalizePortabilityError(error);
  const semanticKey = ERROR_KEY_BY_CODE[clientError.code.toLowerCase()];
  if (semanticKey) {
    return t(`settings.memory.dataManagement.errors.${semanticKey}`);
  }
  return t('settings.memory.dataManagement.errors.generic');
}

export function operationErrorMessage(
  t: TFunction<'app'>,
  errorCode: string | null,
  _errorMessage: string | null,
): string {
  const semanticKey = errorCode ? ERROR_KEY_BY_CODE[errorCode.toLowerCase()] : undefined;
  if (semanticKey) {
    return t(`settings.memory.dataManagement.errors.${semanticKey}`);
  }
  return t('settings.memory.dataManagement.errors.generic');
}

export function formatPortabilityTimestamp(
  value: MemoryPortabilityTimestamp | null,
  locale?: string,
): string | null {
  if (value === null || value === '') {
    return null;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(locale || undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatPortabilityBytes(bytes: number | null): string | null {
  if (bytes === null || !Number.isFinite(bytes) || bytes < 0) {
    return null;
  }
  if (bytes < 1024) {
    return `${Math.round(bytes)} B`;
  }
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[unitIndex]}`;
}

export function formatPortabilityElapsedTime(
  createdAt: MemoryPortabilityTimestamp,
  completedAt: MemoryPortabilityTimestamp | null,
  now: number,
): string | null {
  const started = new Date(createdAt).getTime();
  const finished = completedAt ? new Date(completedAt).getTime() : now;
  if (!Number.isFinite(started) || !Number.isFinite(finished)) {
    return null;
  }
  const totalSeconds = Math.max(0, Math.floor((finished - started) / 1_000));
  const seconds = totalSeconds % 60;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const minutes = totalMinutes % 60;
  const hours = Math.floor(totalMinutes / 60);
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function recordCountLabel(t: TFunction<'app'>, key: string): string | null {
  const translationKey = RECORD_COUNT_KEY_ALIASES[key.toLowerCase()];
  return translationKey
    ? t(`settings.memory.dataManagement.recordCounts.${translationKey}`)
    : null;
}

export function scopeLabel(t: TFunction<'app'>, key: string): string | null {
  const translationKey = SCOPE_KEY_ALIASES[key.toLowerCase()];
  return translationKey
    ? t(`settings.memory.dataManagement.scope.${translationKey}`)
    : null;
}

export function operationPhaseLabel(t: TFunction<'app'>, phase: string): string {
  const translationKey = PHASE_KEY_ALIASES[phase.toLowerCase()];
  return translationKey
    ? t(`settings.memory.dataManagement.operation.phases.${translationKey}`)
    : t('settings.memory.dataManagement.operation.phases.working');
}

export function indexRebuildLabel(t: TFunction<'app'>, status: string): string {
  const translationKey = INDEX_REBUILD_KEY_ALIASES[status.toLowerCase()];
  return translationKey
    ? t(`settings.memory.dataManagement.operation.indexRebuild.${translationKey}`)
    : t('settings.memory.dataManagement.operation.indexRebuild.unknown');
}

export function warningLabel(t: TFunction<'app'>, warning: string): string {
  return KNOWN_WARNING_KEYS.has(warning)
    ? t(`settings.memory.dataManagement.warnings.${warning}`)
    : t('settings.memory.dataManagement.warnings.generic');
}
