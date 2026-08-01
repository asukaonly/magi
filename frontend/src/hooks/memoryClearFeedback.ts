import type { ClearMemoryResponse } from '@/api/modules/memory';

export interface MemoryClearFeedback {
  clearedItemCount: number;
  recoveryPending: boolean;
  diagnosticLogsIncomplete: boolean;
  browserStateIncomplete: boolean;
  otherWarningsPresent: boolean;
}

const DIAGNOSTIC_LOG_CLEANUP_WARNING = 'diagnostic_log_cleanup_failed';
const BROWSER_STATE_CLEANUP_WARNING = 'browser_state_cleanup_failed';

const CONVERSATION_RECOVERY_WARNINGS = new Set([
  'chat_asset_cleanup_pending',
  'channel_conversation_cleanup_failed',
  'channel_conversation_cleanup_pending',
  'orchestration_cleanup_failed',
  'conversation_clear_finalization_failed',
  'clear_boundary_recovery_failed',
  'chat_resume_failed',
]);

export const summarizeMemoryClear = (
  result: ClearMemoryResponse,
): MemoryClearFeedback => {
  const warnings = result.warnings ?? [];
  return {
    clearedItemCount: Object.values(result.results ?? {}).reduce(
      (total, layer) => total + (layer.cleared ? Math.max(0, layer.count) : 0),
      0,
    ),
    recoveryPending: warnings.some((warning) => (
      CONVERSATION_RECOVERY_WARNINGS.has(warning)
    )),
    diagnosticLogsIncomplete: warnings.includes(DIAGNOSTIC_LOG_CLEANUP_WARNING),
    browserStateIncomplete: warnings.includes(BROWSER_STATE_CLEANUP_WARNING),
    otherWarningsPresent: warnings.some((warning) => (
      !CONVERSATION_RECOVERY_WARNINGS.has(warning)
      && warning !== DIAGNOSTIC_LOG_CLEANUP_WARNING
      && warning !== BROWSER_STATE_CLEANUP_WARNING
    )),
  };
};
