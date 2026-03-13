import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import EventsPage from '@/pages/Events';
import { memoryApi } from '@/api/modules/memory';
import { apiClient } from '@/api/client';

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    clearAll: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  },
}));

const L1_EVENT = {
  id: 'event-1',
  type: 'AI_RESPONSE',
  data: {
    content: 'hello',
  },
  timestamp: 1710000000,
  source: 'assistant',
  level: 1,
  correlation_id: 'corr-1',
  metadata: {},
};

describe('events page', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url === '/memory/l1/events') {
        return {
          data: {
            events: [L1_EVENT],
            stats: { total: 1 },
          },
        } as any;
      }

      if (url === '/memory/l2/statistics') {
        return {
          data: {
            total_events: 1,
            total_relations: 2,
          },
        } as any;
      }

      if (url === '/memory/statistics') {
        return {
          data: {
            l3_embeddings: { total_embeddings: 3, dimension: 1536 },
            l4_summaries: { total_summaries: 2 },
            l5_capabilities: { total_capabilities: 1 },
          },
        } as any;
      }

      if (url === '/memory/capabilities') {
        return {
          data: [
            {
              capability_id: 'cap-1',
              name: 'Summarize',
              description: 'Summarize recent activity.',
              success_rate: 0.92,
              usage_count: 4,
            },
          ],
        } as any;
      }

      throw new Error(`Unhandled GET ${url}`);
    });

    vi.mocked(memoryApi.clearAll).mockResolvedValue({
      success: true,
      results: {
        l1_raw: { cleared: true, count: 1 },
        l2_relations: { cleared: true, count: 2 },
        l3_embeddings: { cleared: true, count: 3 },
        l4_summaries: { cleared: true, count: 4 },
        l5_capabilities: { cleared: true, count: 5 },
        chat_context: { cleared: true, count: 6 },
      },
    });
  });

  it('renders raw-event rows as full-width interactive summaries', async () => {
    render(<EventsPage />);

    const summary = (await screen.findByText('AI_RESPONSE')).closest('summary');

    expect(summary).toHaveClass('flex');
    expect(summary).toHaveClass('w-full');
    expect(summary).toHaveClass('px-4');
    expect(summary).toHaveClass('py-3');
    expect(summary?.closest('details')).toHaveClass('p-0');
  });

  it('opens the clear confirmation in a compact dialog container', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('button', { name: /events\.clearMemory|Clear/i }));

    const dialog = await screen.findByRole('dialog');

    expect(dialog).toHaveClass('max-w-lg');
    expect(dialog).toHaveClass('overflow-hidden');
    expect(dialog).toHaveClass('p-0');
    expect(dialog).toHaveClass('z-[80]');
  });
});
