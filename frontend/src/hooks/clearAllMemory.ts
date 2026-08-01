import { memoryApi, type ClearMemoryResponse } from '@/api/modules/memory';
import { clearDesktopLogHistory } from '@/runtime/desktop';
import { completeMemoryClear } from './chatRetryLifecycle';
import { dispatchAppEvent } from '@/constants/events';

const DIAGNOSTIC_LOG_CLEANUP_WARNING = 'diagnostic_log_cleanup_failed';
const BROWSER_STATE_CLEANUP_WARNING = 'browser_state_cleanup_failed';

function withWarning(
  result: ClearMemoryResponse,
  warning: string,
): ClearMemoryResponse {
  const warnings = result.warnings || [];
  if (warnings.includes(warning)) {
    return result;
  }
  return {
    ...result,
    warnings: [...warnings, warning],
  };
}

export const clearAllMemory = async (): Promise<ClearMemoryResponse> => {
  const clearBoundaryAtSeconds = Date.now() / 1000;
  dispatchAppEvent.memoryClearStarted();
  let result = await memoryApi.clearAll();
  if (!result.success) {
    throw new Error('Memory clear request was not completed');
  }
  const browserCleanup = completeMemoryClear({
    clearBoundaryAtSeconds,
  });
  if (!browserCleanup.browserStateCleared) {
    result = withWarning(result, BROWSER_STATE_CLEANUP_WARNING);
  }
  try {
    const desktopLogResult = await clearDesktopLogHistory();
    if (!desktopLogResult || desktopLogResult.failedEntries > 0) {
      result = withWarning(result, DIAGNOSTIC_LOG_CLEANUP_WARNING);
    }
  } catch {
    result = withWarning(result, DIAGNOSTIC_LOG_CLEANUP_WARNING);
  }
  return result;
};
