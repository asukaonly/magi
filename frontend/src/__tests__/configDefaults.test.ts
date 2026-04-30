import { describe, expect, it } from 'vitest';

import { DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';

describe('default system config', () => {
  it('keeps llm provider and model selections empty until the user chooses them', () => {
    expect(DEFAULT_SYSTEM_CONFIG.llm.providers.openai.enabled).toBe(false);
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.context_decider.provider_id).toBe('');
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.context_decider.model).toBe('');
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.core.provider_id).toBe('');
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.core.model).toBe('');
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.memory_summarizer.provider_id).toBe('');
    expect(DEFAULT_SYSTEM_CONFIG.llm.selections.memory_summarizer.model).toBe('');
  });

  it('starts with the managed chat workspace path in preferences', () => {
    expect(DEFAULT_SYSTEM_CONFIG.preferences.default_chat_workspace_path).toBe('~/.magi/chat-workspace');
  });
});
