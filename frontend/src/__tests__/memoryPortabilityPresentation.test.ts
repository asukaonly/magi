import type { TFunction } from 'i18next';
import { describe, expect, it } from 'vitest';

import {
  formatPortabilityElapsedTime,
  operationErrorMessage,
  operationPhaseLabel,
  portabilityErrorMessage,
  recordCountLabel,
  warningLabel,
} from '@/components/settings/memory-data/presentation';

const translate = ((key: string) => key) as TFunction<'app'>;

const STABLE_PORTABILITY_ERROR_CODES = `
  archive_runtime_stale archive_runtime_unavailable archive_schema_invalid archive_target_invalid
  backup_archive_invalid backup_archive_unsupported backup_asset_invalid backup_asset_too_large
  backup_assets_invalid backup_changed backup_checksum_invalid backup_compression_invalid
  backup_corrupt backup_counts_invalid backup_filename_invalid backup_format_invalid
  backup_inspection_failed backup_member_count_invalid backup_member_duplicate backup_member_invalid
  backup_members_invalid backup_package_failed backup_record_count_invalid backup_scope_invalid
  backup_size_invalid backup_too_large backup_unreadable backup_version_unsupported
  backup_write_failed backup_zip64_unsupported candidate_changed candidate_expired candidate_in_use
  candidate_integrity_invalid candidate_integrity_missing candidate_invalid candidate_unavailable
  database_invalid database_schema_invalid encryption_mode_invalid encryption_parameters_invalid
  encryption_state_invalid export_data_invalid export_schema_mismatch export_write_failed
  free_space_unknown index_invalidation_failed index_rebuild_failed index_rebuild_queue_failed
  insufficient_space local_path_invalid managed_asset_changed managed_asset_invalid
  managed_asset_missing managed_asset_too_large managed_source_invalid managed_source_unreadable
  manifest_invalid memory_runtime_unavailable operation_cancelled operation_failed
  operation_in_progress operation_interrupted operation_not_found operation_state_write_failed
  output_directory_invalid output_exists password_invalid password_not_allowed
  password_or_integrity_invalid password_required password_too_long restore_already_committed
  restore_file_changed restore_file_invalid restore_file_unavailable restore_journal_invalid
  restore_not_committed restore_not_ready_to_commit restore_rollback_failed
  restore_rollback_snapshot_failed restore_runtime_busy restore_runtime_recovery_failed
  restore_runtime_shutdown_failed restore_runtime_start_failed restore_runtime_unavailable
  restore_safety_backup_invalid restore_staging_failed restore_staging_invalid restore_target_invalid
  restore_target_unavailable restore_transaction_changed restore_transaction_pending
  schema_revision_mismatch schema_revision_missing schema_revision_unsupported schema_upgrade_failed
  schema_validation_failed snapshot_failed snapshot_incomplete
`.trim().split(/\s+/);

describe('memory portability presentation', () => {
  it('maps every stable backend error code to bilingual semantic copy', () => {
    for (const code of STABLE_PORTABILITY_ERROR_CODES) {
      expect(operationErrorMessage(translate, code, 'Raw backend error')).not.toBe(
        'settings.memory.dataManagement.errors.generic',
      );
      expect(operationErrorMessage(translate, code, 'Raw backend error')).not.toContain(
        'Raw backend error',
      );
    }
  });

  it('normalizes request codes and never leaks unknown backend messages', () => {
    expect(portabilityErrorMessage(translate, {
      message: 'Raw backend error',
      code: 'ARCHIVE_RUNTIME_STALE',
      kind: 'http',
    })).toBe('settings.memory.dataManagement.errors.archiveRuntimeStale');
    expect(operationErrorMessage(translate, 'future_backend_error', 'Raw backend error')).toBe(
      'settings.memory.dataManagement.errors.generic',
    );
  });

  it('presents inspection validation as a localized operation phase', () => {
    expect(operationPhaseLabel(translate, 'validating')).toBe(
      'settings.memory.dataManagement.operation.phases.validating',
    );
  });

  it('labels both persisted L0 counts and formats elapsed operation time', () => {
    expect(recordCountLabel(translate, 'l0_sessions')).toBe(
      'settings.memory.dataManagement.recordCounts.l0Sessions',
    );
    expect(recordCountLabel(translate, 'l0_attention_items')).toBe(
      'settings.memory.dataManagement.recordCounts.l0',
    );
    expect(warningLabel(translate, 'l0_runtime_attention_not_restored')).toBe(
      'settings.memory.dataManagement.warnings.l0_runtime_attention_not_restored',
    );
    expect(formatPortabilityElapsedTime(
      '2026-08-18T09:00:00Z',
      '2026-08-18T10:02:03Z',
      0,
    )).toBe('1:02:03');
  });
});
