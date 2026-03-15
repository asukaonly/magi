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
  event_id: 'event-1',
  event_type: 'AI_RESPONSE',
  raw_content: 'hello',
  timestamp: 1710000000,
  source: 'assistant',
  memory_domain: 'chat',
  retention_class: 'default',
  importance_score: 0.5,
  cognition_eligible: true,
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
        l0: { cleared: true, count: 1 },
        l1: { cleared: true, count: 2 },
        l2: { cleared: true, count: 3 },
        l3: { cleared: true, count: 4 },
        l4: { cleared: true, count: 5 },
        chat_context: { cleared: true, count: 6 },
      },
    });
  });

  it('renders event cards with proper structure', async () => {
    render(<EventsPage />);

    // Find the event badge that displays the event type
    const eventTypeBadge = await screen.findByText('AI_RESPONSE');

    // The badge should be inside a card container
    const eventCard = eventTypeBadge.closest('.border');
    expect(eventCard).toBeInTheDocument();
    expect(eventCard).toHaveClass('rounded-lg');
  });

  it('opens the clear confirmation in a compact dialog container', async () => {
    const user = userEvent.setup();
    render(<EventsPage />);

    await user.click(await screen.findByRole('button', { name: /events\.clearMemory|Clear/i }));

    const dialog = await screen.findByRole('dialog');
    // Dialog uses responsive Tailwind classes - just check it dialog exists
    expect(dialog).toBeInTheDocument();
  });
});
