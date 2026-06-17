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
});
