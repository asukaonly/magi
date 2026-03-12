import { describe, expect, it, vi } from 'vitest';

vi.mock('@/api/client', () => ({
  api: {
    post: vi.fn(),
  },
}));

import { api } from '@/api/client';
import { personalityApi } from '@/api/modules/personality';

describe('personalityApi.generate', () => {
  it('uses an extended timeout for AI generation', () => {
    personalityApi.generate({
      description: 'asoul的向晚',
      target_language: 'Chinese',
    });

    expect(api.post).toHaveBeenCalledWith(
      '/personality/generate',
      {
        description: 'asoul的向晚',
        target_language: 'Chinese',
      },
      {
        timeout: 120000,
      }
    );
  });
});
