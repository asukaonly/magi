import { render, screen } from '@testing-library/react';
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { MemoryPortraitRail } from '@/components/chat/MemoryPortraitRail';
import { memoryPortraitApi } from '@/api/modules/memoryPortrait';

vi.mock('@/api/modules/memoryPortrait', () => ({
  memoryPortraitApi: {
    get: vi.fn(),
  },
}));

describe('MemoryPortraitRail', () => {
  beforeEach(() => {
    vi.mocked(memoryPortraitApi.get).mockReset();
  });

  it('renders cards when observations exist', async () => {
    vi.mocked(memoryPortraitApi.get).mockResolvedValue({
      session_id: 's1',
      persona_id: 'p1',
      topic: 't',
      generated_at: 0,
      observations: [
        { kind: 'reflection', text: '你又在想老罗', basis_count: 1, basis_summary: '1', basis_refs: [] },
        { kind: 'assertion', text: '你不喜欢直播', basis_count: 1, basis_summary: '1', basis_refs: [] },
      ],
      is_cold_start: false,
      cold_start_line: null,
      cold_start_reason: null,
      is_stale: false,
    });
    render(<MemoryPortraitRail sessionId="s1" userId="u1" personaId="p1" />);
    const cards = await screen.findAllByTestId('portrait-card');
    expect(cards).toHaveLength(2);
    expect(screen.getByText('你又在想老罗')).toBeInTheDocument();
  });

  it('renders cold-start when payload is empty', async () => {
    vi.mocked(memoryPortraitApi.get).mockResolvedValue({
      session_id: 's1', persona_id: 'p1', topic: '', generated_at: 0,
      observations: [], is_cold_start: true, cold_start_line: 'hi',
      cold_start_reason: 'computing', is_stale: false,
    });
    render(<MemoryPortraitRail sessionId="s1" userId="u1" personaId="p1" />);
    // The cold-start container also renders pre-resolution (the initial null payload
    // shows the fallback line), so waiting for the container races the API-provided
    // line. findByText retries until the resolved render shows the actual cold_start_line.
    expect(await screen.findByText('hi')).toBeInTheDocument();
    expect(screen.getByTestId('portrait-cold-start')).toBeInTheDocument();
  });

  it('renders nothing visible when sessionId is missing', () => {
    render(<MemoryPortraitRail sessionId="" userId="u1" personaId="p1" />);
    expect(screen.queryByTestId('portrait-card')).not.toBeInTheDocument();
    expect(screen.queryByTestId('portrait-cold-start')).not.toBeInTheDocument();
  });
});
