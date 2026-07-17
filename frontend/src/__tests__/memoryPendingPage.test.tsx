import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { MemoryPendingPage } from '@/pages/memory-pages/MemoryPendingPage';
import { memoryApi } from '@/api/modules/memory';
import { memoryStoriesApi } from '@/api/modules/memoryStories';
import { listNotifications, resolveConflict } from '@/api/modules/notifications';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        'memory.pending.title': '待确认',
        'memory.pending.subtitle': '需要你判断的记忆线索都在这里。',
        'memory.pending.totalCount': '{{count}} 条',
        'memory.pending.filters.all': '全部',
        'memory.pending.filters.memory': '影响记忆',
        'memory.pending.filters.experiences': '整理经历',
        'memory.pending.filters.observations': '总结复核',
        'memory.pending.groups.memory.title': '影响记忆',
        'memory.pending.groups.memory.description': '这些会直接影响 Magi 之后怎么理解你',
        'memory.pending.groups.experiences.title': '整理经历',
        'memory.pending.groups.experiences.description': '确认后会保存成一段经历',
        'memory.pending.groups.observations.title': '总结复核',
        'memory.pending.groups.observations.description': '确认这些阶段总结是否说准了',
        'memory.pending.sections.profile': '关于你的判断',
        'memory.pending.sections.summaries': '待确认记忆',
        'memory.pending.sections.experiences': '待整理经历',
        'memory.pending.sections.conflicts': '偏好冲突',
        'memory.pending.emptyTitle': '现在没有需要处理的内容',
        'memory.pending.emptyBody': 'Magi 有新的判断或经历线索时会放到这里。',
        'memory.pending.actions.confirm': '确认',
        'memory.pending.actions.confirmJudgment': '是的',
        'memory.pending.actions.reject': '不对',
        'memory.pending.actions.confirmObservation': '说得对',
        'memory.pending.actions.rejectObservation': '不太对',
        'memory.pending.actions.acceptConflict': '采用新记忆',
        'memory.pending.actions.keepExisting': '保留旧记忆',
        'memory.pending.actions.promoteExperience': '保存为经历',
        'memory.pending.actions.rejectExperience': '忽略',
        'memory.pending.meta.assertion': '关于你的判断',
        'memory.pending.meta.conflict': '偏好冲突',
        'memory.pending.meta.summary': '总结',
        'memory.pending.meta.experienceSeed': '经历线索',
        'memory.pending.assertions.tentativeTitle': '我整理出一个关于你的判断：「{{value}}」',
        'memory.pending.assertions.unknownValue': '这条记忆判断',
        'memory.pending.assertions.tentativeBody': '这个判断对吗？',
        'memory.pending.assertions.conflictTitle': '我发现「{{value}}」这个判断和新的证据有冲突',
        'memory.pending.assertions.conflictBody': '需要你确认它是否还应该影响 Magi 对你的理解。',
        'memory.pending.assertions.conflictPairTitle': '「{{oldValue}}」和「{{newValue}}」这两个判断对不上',
        'memory.pending.assertions.conflictPairBody': '旧判断是「{{oldValue}}」，新证据更支持「{{newValue}}」。请确认旧判断是否还准确。',
        'memory.pending.assertions.uncertainTitle': '我对「{{value}}」这个判断没把握',
        'memory.pending.assertions.uncertainBody': '证据还不够一致，但没有明确的相反判断。请确认它准不准。',
        'memory.pending.assertions.traitBody': '判断类型：{{trait}}',
        'memory.pages.knowledge.readable.assertions.communication_address_preferred': '你希望我称呼你为“{{value}}”。',
        'memory.pending.conflictMeta': '和已确认记忆不一致',
        'memory.pending.evidenceCount': '{{count}} 条证据',
        'memory.pending.fragmentCount': '{{count}} 个片段',
      };
      let result = labels[key] ?? key;
      if (opts) {
        for (const [name, value] of Object.entries(opts)) {
          result = result.replace(`{{${name}}}`, String(value));
        }
      }
      return result;
    },
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('@/api/modules/memory', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/memory')>('@/api/modules/memory');
  return {
    ...actual,
    memoryApi: {
      getDashboard: vi.fn(),
      submitAssertionFeedback: vi.fn(),
      applyCorrection: vi.fn(),
      listExperienceSeeds: vi.fn(),
      promoteExperienceSeed: vi.fn(),
      rejectExperienceSeed: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/memoryStories', () => ({
  memoryStoriesApi: {
    list: vi.fn(),
    review: vi.fn(),
  },
}));

vi.mock('@/api/modules/notifications', () => ({
  listNotifications: vi.fn(),
  resolveConflict: vi.fn(),
}));

const dashboardPayload = {
  pending_assertions: {
    items: [
      {
        assertion_id: 'assert-1',
        entity_id: 'user:self',
        entity_type: 'user',
        trait_family: 'preference_profile',
        trait_name: '关注方向',
        trait_value: '本地优先的记忆系统',
        confidence_score: 0.52,
        evidence_events: ['evt-1', 'evt-2'],
        validation_state: 'tentative',
        volatility_index: 0.4,
        source_domain: 'conversation',
        inference_depth: 'semantic',
        first_inferred_at: 1710000000,
        last_validated_at: 1710000000,
        user_feedback: null,
        user_feedback_at: null,
        status: 'tentative',
      },
    ],
    total: 1,
    limit: 25,
    offset: 0,
  },
};

const storyPayload = {
  items: [
    {
      summary_id: 'story-1',
      summary_type: 'insight',
      summary_category: 'state_change',
      title: '最近更关注记忆产品',
      content: 'Magi 觉得你这几天更常讨论记忆页面和用户校准。',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003600,
      review_state: 'pending_confirmation',
      insight_key: 'state:memory',
      insight_metadata: {},
      evidence_event_count: 4,
      feed_group: 'memory_update',
      summary_feed_visible: false,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: '最近更关注记忆产品',
      detail_lead_text: 'Magi 觉得你这几天更常讨论记忆页面和用户校准。',
    },
    {
      summary_id: 'story-2',
      summary_type: 'insight',
      summary_category: 'trend_shift',
      title: '趋势观察',
      content: '最近持续关注：Codex、DeepSeek。',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003550,
      review_state: 'pending_confirmation',
      insight_key: 'trend:memory',
      insight_metadata: {},
      evidence_event_count: 6,
      feed_group: 'observations',
      summary_feed_visible: true,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: '趋势观察',
      detail_lead_text: '最近持续关注：Codex、DeepSeek。',
    },
    {
      summary_id: 'story-3',
      summary_type: 'temporal',
      summary_category: 'day',
      title: '普通总结',
      content: '已经处理过的总结。',
      period_start: 1710000000,
      period_end: 1710003600,
      updated_at: 1710003500,
      review_state: 'neutral',
      insight_key: null,
      insight_metadata: {},
      evidence_event_count: 1,
      feed_group: 'periodic',
      summary_feed_visible: true,
      featured_rank: null,
      display_timestamp: 1710003600,
      preview_text: '普通总结',
      detail_lead_text: '已经处理过的总结。',
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
  stats: {
    highlights: 1,
    periodic: 1,
    observations: 1,
    tasks: 0,
  },
};

const seedPayload = {
  items: [
    {
      seed_id: 'seed-1',
      seed_type: 'project',
      status: 'candidate',
      display_title: '可能是一段记忆页面改版',
      display_description: '这些片段都在围绕记忆导航和回顾页调整。',
      display_tags: ['记忆', '导航'],
      anchor_entity_ids: ['project:magi'],
      anchor_topic_keys: ['topic:memory'],
      time_start: 1710000000,
      time_end: 1710003600,
      confidence: 0.78,
      evidence_count: 3,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
};

const notificationPayload = {
  items: [
    {
      id: 42,
      kind: 'suggestion',
      dedupe_key: 'profile_conflict:interest.anime:topic:anime',
      title: '偏好冲突：interest.anime',
      body: '你最近常关注「安静圣地巡礼」，但你说过「城市热门路线」—— 要更新偏好吗？',
      payload: {
        conflict_type: 'profile_conflict',
        shadow_id: 'assert-shadow-1',
        authoritative_id: 'assert-old-1',
        authoritative_value: '城市热门路线',
        inferred_value: '安静圣地巡礼',
        trait_name: 'interest.anime',
        entity_id: 'user:self',
      },
      status: 'unread',
      created_at_ms: 1710000000000,
      read_at_ms: null,
    },
  ],
  unread_count: 1,
};

const renderPage = () =>
  render(
    <MemoryRouter>
      <MemoryPendingPage />
    </MemoryRouter>
  );

describe('MemoryPendingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(memoryApi.getDashboard).mockResolvedValue(dashboardPayload as never);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue(storyPayload as never);
    vi.mocked(memoryApi.listExperienceSeeds).mockResolvedValue(seedPayload as never);
    vi.mocked(listNotifications).mockResolvedValue(notificationPayload as never);
    vi.mocked(memoryApi.submitAssertionFeedback).mockResolvedValue(dashboardPayload.pending_assertions.items[0] as never);
    vi.mocked(memoryApi.applyCorrection).mockResolvedValue({
      correction: {
        correction_id: 'correction-1',
        correction_kind: 'record_error',
        created_at: 1710000001,
        state: 'active',
      },
      current_claim: null,
      derivation_state: 'completed',
      created: true,
    });
    vi.mocked(resolveConflict).mockResolvedValue(undefined);
    vi.mocked(memoryStoriesApi.review).mockResolvedValue({
      ok: true,
      summary_id: 'story-1',
      review_state: 'confirmed',
    });
    vi.mocked(memoryApi.promoteExperienceSeed).mockResolvedValue({
      seed_id: 'seed-1',
      promoted_experience_id: 'exp-1',
      experience: null,
    } as never);
    vi.mocked(memoryApi.rejectExperienceSeed).mockResolvedValue({
      seed_id: 'seed-1',
      seed: { ...seedPayload.items[0], status: 'rejected' },
    } as never);
  });

  it('collects pending items into grouped confirmation lanes without the old page header', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: '影响记忆' })).toBeInTheDocument();
    expect(screen.queryByTestId('memory-page-header')).not.toBeInTheDocument();
    expect(screen.getByText('这些会直接影响 Magi 之后怎么理解你')).toBeInTheDocument();
    expect(screen.getByText('我整理出一个关于你的判断：「本地优先的记忆系统」')).toBeInTheDocument();
    expect(screen.getByText('判断类型：关注方向')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '总结复核' })).toBeInTheDocument();
    expect(screen.getByText('最近更关注记忆产品')).toBeInTheDocument();
    expect(screen.queryByText('观察')).not.toBeInTheDocument();
    expect(screen.queryByText('趋势观察')).not.toBeInTheDocument();
    expect(screen.queryByText('最近持续关注：Codex、DeepSeek。')).not.toBeInTheDocument();
    expect(screen.queryByText('普通总结')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '整理经历' })).toBeInTheDocument();
    expect(screen.getByText('可能是一段记忆页面改版')).toBeInTheDocument();
    expect(screen.getByText('你最近常关注「安静圣地巡礼」，但你说过「城市热门路线」—— 要更新偏好吗？')).toBeInTheDocument();
    expect(memoryApi.getDashboard).toHaveBeenCalledWith({ pending_limit: 25 });
    expect(memoryStoriesApi.list).toHaveBeenCalledWith({ limit: 50, offset: 0, surface: 'all' });
    expect(memoryApi.listExperienceSeeds).toHaveBeenCalledWith({ status: 'candidate', limit: 50, offset: 0 });
    expect(listNotifications).toHaveBeenCalled();
  });

  it('explains conflicted L2 assertions without exposing internal trait identifiers', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      pending_assertions: {
        items: [
          {
            assertion_id: 'assert-conflict',
            entity_id: 'user:self',
            entity_type: 'user',
            trait_family: 'preference_profile',
            trait_name: 'interest.frank_wang-7efea7',
            trait_value: '阿里巴巴集团',
            confidence_score: 0.35,
            evidence_events: ['evt-1', 'evt-2', 'evt-3', 'evt-4', 'evt-5'],
            validation_state: 'contradicted',
            volatility_index: 0.4,
            source_domain: 'external_activity',
            inference_depth: 'topology_only',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: null,
            user_feedback_at: null,
            status: 'contradicted',
            conflict_context: {
              kind: 'superseded_by_assertion',
              previous_assertion_id: 'assert-conflict',
              previous_value: '阿里巴巴集团',
              current_assertion_id: 'assert-current',
              current_value: 'Frank Wang',
            },
          },
          {
            assertion_id: 'assert-conflict-no-value',
            entity_id: 'user:self',
            entity_type: 'user',
            trait_family: 'preference_profile',
            trait_name: 'interest.frank_wang-7efea7',
            trait_value: '',
            confidence_score: 0.35,
            evidence_events: ['evt-1'],
            validation_state: 'contradicted',
            volatility_index: 0.4,
            source_domain: 'external_activity',
            inference_depth: 'topology_only',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: null,
            user_feedback_at: null,
            status: 'contradicted',
          },
        ],
        total: 2,
        limit: 25,
        offset: 0,
      },
    } as never);

    renderPage();

    const card = await screen.findByTestId('pending-assertion-assert-conflict');
    expect(within(card).getByText('「阿里巴巴集团」和「Frank Wang」这两个判断对不上')).toBeInTheDocument();
    expect(within(card).getByText('旧判断是「阿里巴巴集团」，新证据更支持「Frank Wang」。请确认旧判断是否还准确。')).toBeInTheDocument();
    expect(card.textContent).not.toContain('interest.frank_wang-7efea7');

    const fallbackCard = await screen.findByTestId('pending-assertion-assert-conflict-no-value');
    expect(within(fallbackCard).getByText('我对「这条记忆判断」这个判断没把握')).toBeInTheDocument();
    expect(within(fallbackCard).getByText('证据还不够一致，但没有明确的相反判断。请确认它准不准。')).toBeInTheDocument();
    expect(fallbackCard.textContent).not.toContain('interest.frank_wang-7efea7');
  });

  it('renders communication assertions as address preferences instead of interests', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      pending_assertions: {
        items: [
          {
            assertion_id: 'assert-address',
            entity_id: 'user:self',
            entity_type: 'user',
            trait_family: 'communication_profile',
            trait_name: 'communication.address.preferred',
            trait_value: '子涵',
            confidence_score: 0.52,
            evidence_events: ['evt-1'],
            validation_state: 'tentative',
            volatility_index: 0.2,
            source_domain: 'conversation',
            inference_depth: 'semantic',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: null,
            user_feedback_at: null,
            status: 'tentative',
          },
        ],
        total: 1,
        limit: 25,
        offset: 0,
      },
    } as never);

    renderPage();

    const card = await screen.findByTestId('pending-assertion-assert-address');
    expect(within(card).getByText('你希望我称呼你为“子涵”。')).toBeInTheDocument();
    expect(within(card).getByText('这个判断对吗？')).toBeInTheDocument();
    expect(card.textContent).not.toContain('communication.address.preferred');
    expect(card.textContent).not.toContain('关注「子涵」');
  });

  it('filters the confirmation lanes by decision type', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByTestId('pending-assertion-assert-1')).toBeInTheDocument();
    expect(screen.getByTestId('pending-story-story-1')).toBeInTheDocument();
    expect(screen.getByTestId('pending-experience-seed-1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /总结复核/ }));

    expect(screen.queryByTestId('pending-assertion-assert-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pending-experience-seed-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('pending-story-story-1')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /整理经历/ }));

    expect(screen.queryByTestId('pending-story-story-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('pending-experience-seed-1')).toBeInTheDocument();
  });

  it('routes each pending action to its owning API and removes completed cards', async () => {
    const user = userEvent.setup();
    renderPage();

    const assertionCard = await screen.findByTestId('pending-assertion-assert-1');
    await user.click(within(assertionCard).getByRole('button', { name: '是的' }));
    expect(memoryApi.submitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');
    await waitFor(() => {
      expect(screen.queryByTestId('pending-assertion-assert-1')).not.toBeInTheDocument();
    });

    const storyCard = screen.getByTestId('pending-story-story-1');
    await user.click(within(storyCard).getByRole('button', { name: '不太对' }));
    expect(memoryStoriesApi.review).toHaveBeenCalledWith('story-1', { review_state: 'rejected' });
    await waitFor(() => {
      expect(screen.queryByTestId('pending-story-story-1')).not.toBeInTheDocument();
    });

    const seedCard = screen.getByTestId('pending-experience-seed-1');
    await user.click(within(seedCard).getByRole('button', { name: '保存为经历' }));
    expect(memoryApi.promoteExperienceSeed).toHaveBeenCalledWith('seed-1');
    await waitFor(() => {
      expect(screen.queryByTestId('pending-experience-seed-1')).not.toBeInTheDocument();
    });

    const conflictCard = screen.getByTestId('pending-conflict-42');
    await user.click(within(conflictCard).getByRole('button', { name: '采用新记忆' }));
    expect(resolveConflict).toHaveBeenCalledWith(42, 'confirm');
    await waitFor(() => {
      expect(screen.queryByTestId('pending-conflict-42')).not.toBeInTheDocument();
    });
  });

  it('opens governed correction instead of rejecting an assertion through feedback', async () => {
    const user = userEvent.setup();
    renderPage();

    const assertionCard = await screen.findByTestId('pending-assertion-assert-1');
    await user.click(within(assertionCard).getByRole('button', { name: '不对' }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('memory.correction.title')).toBeInTheDocument();
    expect(memoryApi.submitAssertionFeedback).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'memory.correction.removeSubmit' }));
    await waitFor(() => {
      expect(memoryApi.applyCorrection).toHaveBeenCalledWith(expect.objectContaining({
        target: { kind: 'assertion', id: 'assert-1' },
        correction_kind: 'record_error',
      }));
    });
    expect(vi.mocked(memoryApi.applyCorrection).mock.calls[0][0]).not.toHaveProperty('replacement');
  });

  it('keeps the existing memory when a profile conflict is rejected', async () => {
    const user = userEvent.setup();
    renderPage();

    const conflictCard = await screen.findByTestId('pending-conflict-42');
    await user.click(within(conflictCard).getByRole('button', { name: '保留旧记忆' }));

    expect(resolveConflict).toHaveBeenCalledWith(42, 'reject');
    await waitFor(() => {
      expect(screen.queryByTestId('pending-conflict-42')).not.toBeInTheDocument();
    });
  });

  it('shows a calm empty state when there is nothing to review', async () => {
    vi.mocked(memoryApi.getDashboard).mockResolvedValue({
      pending_assertions: { items: [], total: 0, limit: 25, offset: 0 },
    } as never);
    vi.mocked(memoryStoriesApi.list).mockResolvedValue({
      ...storyPayload,
      items: storyPayload.items.filter((item) => item.review_state !== 'pending_confirmation'),
    } as never);
    vi.mocked(memoryApi.listExperienceSeeds).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    } as never);
    vi.mocked(listNotifications).mockResolvedValue({
      items: [],
      unread_count: 0,
    } as never);

    renderPage();

    expect(await screen.findByText('现在没有需要处理的内容')).toBeInTheDocument();
    expect(screen.getByText('Magi 有新的判断或经历线索时会放到这里。')).toBeInTheDocument();
  });
});
