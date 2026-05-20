import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { MemoryPortraitPage } from '@/pages/memory-pages/MemoryPortraitPage';
import { memoryPortraitSelfApi } from '@/api/modules/memoryPortraitSelf';

vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.portrait.title': '画像',
    'memory.portrait.subtitle': 'Magi 眼中的你',
    'memory.portrait.segments.identity': '身份',
    'memory.portrait.segments.state': '当下',
    'memory.portrait.segments.preferences': '偏好',
    'memory.portrait.segments.relationships': '关系',
    'memory.portrait.segments.impression': '总体印象',
    'memory.portrait.coldStartFallback': '还没结论',
    'memory.stories.actions.confirm': '确认',
    'memory.stories.actions.reject': '拒绝',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: { defaultValue?: string }) => labels[key] ?? opts?.defaultValue ?? key,
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memoryPortraitSelf', () => ({
  memoryPortraitSelfApi: { get: vi.fn() },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: { submitAssertionFeedback: vi.fn() },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryPortraitPage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryPortraitPage', () => {
  it('shows cold-start text when payload is_cold_start=true', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [], is_cold_start: true, cold_start_line: '还没结论', cold_start_reason: 'no_observations',
      is_stale: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('还没结论')).toBeInTheDocument();
    });
  });

  it('groups observations into segments by kind', async () => {
    vi.mocked(memoryPortraitSelfApi.get).mockResolvedValue({
      session_id: '', persona_id: '', topic: 'self', generated_at: 0,
      observations: [
        { kind: 'assertion', text: '住在杭州', basis_count: 1, basis_summary: 'projection', basis_refs: ['home_location'] },
        { kind: 'reflection', text: '好奇、专注', basis_count: 4, basis_summary: 'tom', basis_refs: ['tom-1'] },
      ],
      is_cold_start: false, cold_start_line: null, cold_start_reason: null, is_stale: false,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('住在杭州')).toBeInTheDocument();
      expect(screen.getByText('好奇、专注')).toBeInTheDocument();
    });
  });
});
