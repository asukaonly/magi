import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { L1Tab } from '@/components/memory/L1Tab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      'memory.eventTypes.ai_response': 'Assistant reply',
      'memory.eventTypes.task_completed': 'Task completed',
    }[key] ?? key),
  }),
}));

vi.mock('@/hooks/useMemory', () => ({
  formatTimestamp: () => 'mock-time',
}));

describe('L1Tab', () => {
  it('translates PascalCase event types through i18n keys', () => {
    render(
      <L1Tab
        stats={{ event_count: 2 }}
        events={[
          {
            event_id: 'evt-ai',
            event_type: 'AIResponse',
            timestamp: 1710000000,
            content: 'hello',
            memory_domain: 'interaction',
            retention_class: 'compressible',
            importance_score: 0.5,
            cognition_eligible: false,
          },
          {
            event_id: 'evt-task',
            event_type: 'TaskCompleted',
            timestamp: 1710000001,
            content: 'task done',
            memory_domain: 'runtime_telemetry',
            retention_class: 'compressible',
            importance_score: 0.5,
            cognition_eligible: false,
          },
        ]}
        showHeader={false}
        showStats={false}
      />
    );

    expect(screen.getByText('Assistant reply')).toBeInTheDocument();
    expect(screen.getByText('Task completed')).toBeInTheDocument();
    expect(screen.queryByText('AIResponse')).not.toBeInTheDocument();
    expect(screen.queryByText('TaskCompleted')).not.toBeInTheDocument();
  });
});