import { memoryApi, type ClearMemoryResponse } from '@/api/modules/memory';
import { completeMemoryClear } from './chatRetryLifecycle';

export const clearAllMemory = async (): Promise<ClearMemoryResponse> => {
  const result = await memoryApi.clearAll();
  if (!result.success) {
    throw new Error('Memory clear request was not completed');
  }
  completeMemoryClear();
  return result;
};
