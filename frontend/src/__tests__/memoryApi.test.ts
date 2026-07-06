import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from '@/api/client';
import { memoryApi } from '@/api/modules/memory';

describe('memoryApi episode endpoints', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads an episode detail by id', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { episode_id: 'ep-1', events: [], inferred: [] },
    });

    await memoryApi.getEpisode('ep-1');

    expect(getSpy).toHaveBeenCalledWith('/memory/l2/episodes/ep-1');
  });

  it('merges an absorbed episode into a survivor episode', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { episode_id: 'ep-1' },
    });

    await memoryApi.mergeEpisodes('ep-1', 'ep-2');

    expect(postSpy).toHaveBeenCalledWith('/memory/l2/episodes/ep-1/merge', { absorbed_id: 'ep-2' });
  });

  it('creates an experience seed from selected episodes', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      success: true,
      message: 'ok',
      data: { seed_id: 'seed-1', promoted_experience_id: 'exp-1' },
    });

    await memoryApi.createExperienceSeed({
      episode_ids: ['ep-1', 'ep-2'],
      title_hint: 'Japan planning',
      promote_now: true,
    });

    expect(postSpy).toHaveBeenCalledWith('/memory/l2/experience-seeds', {
      episode_ids: ['ep-1', 'ep-2'],
      event_ids: [],
      title_hint: 'Japan planning',
      promote_now: true,
    });
  });

  it('loads the memory dashboard read model', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      success: true,
      message: 'ok',
      data: {
        statistics: {
          l0: { active_sessions: 0, total_goals: 0, total_entities: 0, total_tactics: 0 },
          l1: { event_count: 0 },
          l2: { relation_count: 0, assertion_count: 0 },
          l3: { summary_count: 0 },
          l4: { skill_count: 0, open_circuit_breakers: 0 },
          attention: { pending_assertions: 0, open_circuit_breakers: 0 },
        },
        source_counts: [],
        attention: { pending_assertions: 0, open_circuit_breakers: 0 },
        pending_assertions: { items: [], total: 0, limit: 8, offset: 0 },
      },
    });

    await memoryApi.getDashboard({ pending_limit: 8 });

    expect(getSpy).toHaveBeenCalledWith('/memory/dashboard', { params: { pending_limit: 8 } });
  });
});
