import type { LLMConfig } from '@/api/modules/config';

export function hasConfiguredEmbeddingSelection(value: LLMConfig): boolean {
  const selection = value.selections?.embedding;
  if (!selection?.provider_id || !selection.model) {
    return false;
  }
  const provider = value.providers?.[selection.provider_id];
  return Boolean(provider?.enabled && provider.services?.embedding?.enabled);
}

export function getMemoryModelStatus(value: LLMConfig): 'ready' | 'missing' | null {
  const coreProviderId = value.selections?.core?.provider_id;
  if (!coreProviderId || !value.providers?.[coreProviderId]) {
    return null;
  }
  return hasConfiguredEmbeddingSelection(value) ? 'ready' : 'missing';
}
