import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryEpisodesPage } from '@/pages/memory-pages/MemoryEpisodesPage';
import { memoryApi } from '@/api/modules/memory';

// Mirror the i18n mock style used in memoryStoryPage.test.tsx so we don't load
// the real i18n module inside jsdom (its top-level localStorage access fails there).
vi.mock('react-i18next', async () => {
  const labels: Record<string, string> = {
    'memory.episodes.title': '章节',
    'memory.episodes.subtitle': '...',
    'memory.episodes.pinnedSection': '置顶',
    'memory.episodes.recentSection': '最近',
    'memory.episodes.emptyTitle': '还没有可读的章节',
    'memory.episodes.emptyBody': '...',
    'memory.episodes.actions.pin': '置顶',
    'memory.episodes.actions.unpin': '取消置顶',
    'memory.episodes.actions.rename': '重命名',
    'memory.episodes.actions.annotate': '备注',
    'memory.episodes.actions.forget': '遗忘',
    'memory.episodes.filters.activity': '活动',
    'memory.episodes.filters.session': '会话',
    'common.save': '保存',
    'common.cancel': '取消',
  };
  return {
    useTranslation: () => ({
      t: (key: string, opts?: { defaultValue?: string }) => labels[key] ?? opts?.defaultValue ?? key,
      i18n: { language: 'zh-CN' },
    }),
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    listEpisodes: vi.fn(),
    annotateEpisode: vi.fn(),
    forgetEpisode: vi.fn(),
  },
}));

const renderPage = () => render(
  <MemoryRouter>
    <MemoryEpisodesPage />
  </MemoryRouter>
);

beforeEach(() => vi.clearAllMocks());

describe('MemoryEpisodesPage', () => {
  it('renders pinned section above recent section', async () => {
    vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
      items: [
        { episode_id: 'e1', episode_type: 'activity', user_pinned: true, user_label: '搬家那周', summary: '',
          time_start: 1700000000, time_end: 1700100000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
          dominant_mode: null, status: 'active', user_note: '', label: '' } as never,
        { episode_id: 'e2', episode_type: 'activity', user_pinned: false, user_label: null, summary: '昨天下午聊了一会',
          time_start: 1700200000, time_end: 1700300000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
          dominant_mode: null, status: 'active', user_note: '', label: '' } as never,
      ],
      total: 2, limit: 50, offset: 0,
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText('搬家那周')).toBeInTheDocument();
    });
    const pinnedSection = screen.getByTestId('episodes-pinned');
    const recentSection = screen.getByTestId('episodes-recent');
    expect(pinnedSection.textContent).toContain('搬家那周');
    expect(recentSection.textContent).toContain('昨天下午聊了一会');
  });

  it('opens rename dialog and calls annotateEpisode with new user_label on save', async () => {
    vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
      items: [{
        episode_id: 'e1', episode_type: 'activity', user_pinned: false, user_label: '旧名字', summary: 'demo',
        time_start: 1700000000, time_end: 1700100000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
        dominant_mode: null, status: 'active', user_note: '', label: '',
      }] as never,
      total: 1, limit: 50, offset: 0,
    });
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText('旧名字'));

    // Click rename button to open dialog
    await user.click(screen.getByLabelText(/重命名/i));

    // Dialog should appear with the rename title
    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    // Clear input and type a new name
    const input = screen.getByRole('textbox');
    await user.clear(input);
    await user.type(input, '新名字');

    // Click Save
    await user.click(screen.getByText('保存'));

    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('e1', { user_label: '新名字' });
    });
  });

  it('toggles pin on an episode', async () => {
    vi.mocked(memoryApi.listEpisodes).mockResolvedValue({
      items: [{
        episode_id: 'e1', episode_type: 'session', user_pinned: false, user_label: null, summary: 'demo',
        time_start: 1700000000, time_end: 1700100000, primary_entity_ids: [], primary_place_ids: [], primary_topic_keys: [],
        dominant_mode: null, status: 'active', user_note: '', label: '',
      }] as never,
      total: 1, limit: 50, offset: 0,
    });
    vi.mocked(memoryApi.annotateEpisode).mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByText('demo'));
    await user.click(screen.getByLabelText(/置顶|Pin/i));
    await waitFor(() => {
      expect(memoryApi.annotateEpisode).toHaveBeenCalledWith('e1', { user_pinned: true });
    });
  });
});
