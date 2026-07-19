import type { ClearMemoryResponse } from '@/api/modules/memory';

export interface MemoryClearFeedback {
  clearedItemCount: number;
  recoveryPending: boolean;
  otherWarningsPresent: boolean;
}

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
    otherWarningsPresent: warnings.some((warning) => (
      !CONVERSATION_RECOVERY_WARNINGS.has(warning)
    )),
  };
};
