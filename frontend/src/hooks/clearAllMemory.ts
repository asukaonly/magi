import { memoryApi, type ClearMemoryResponse } from '@/api/modules/memory';
import { clearDesktopLogHistory } from '@/runtime/desktop';
import { completeMemoryClear } from './chatRetryLifecycle';

const DIAGNOSTIC_LOG_CLEANUP_WARNING = 'diagnostic_log_cleanup_failed';

function withDiagnosticLogWarning(result: ClearMemoryResponse): ClearMemoryResponse {
  const warnings = result.warnings || [];
  if (warnings.includes(DIAGNOSTIC_LOG_CLEANUP_WARNING)) {
    return result;
  }
  return {
    ...result,
    warnings: [...warnings, DIAGNOSTIC_LOG_CLEANUP_WARNING],
  };
}

export const clearAllMemory = async (): Promise<ClearMemoryResponse> => {
  let result = await memoryApi.clearAll();
  if (!result.success) {
    throw new Error('Memory clear request was not completed');
  }
  try {
    const desktopLogResult = await clearDesktopLogHistory();
    if (!desktopLogResult || desktopLogResult.failedEntries > 0) {
      result = withDiagnosticLogWarning(result);
    }
  } catch {
    result = withDiagnosticLogWarning(result);
  }
  completeMemoryClear();
  return result;
};
