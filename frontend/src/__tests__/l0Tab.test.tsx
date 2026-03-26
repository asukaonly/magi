import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { L0Tab } from '@/components/memory/L0Tab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('L0Tab', () => {
  it('shows a shell-only hint when the selected session has no L0 workbench content yet', async () => {
    const onSelectSession = vi.fn();
    const user = userEvent.setup();

    render(
      <L0Tab
        stats={{ active_sessions: 1, total_goals: 0, total_entities: 0, total_tactics: 0 }}
        sessions={[
          {
            session_id: 'session-alpha',
            status: 'active',
            started_at: 1710000000,
            last_active_at: 1710000300,
            goal_count: 0,
            entity_count: 0,
            tactic_count: 0,
          },
        ]}
        workbench={{
          session: { session_id: 'session-alpha' },
          goal_stack: [],
          active_entities: [],
          temporary_tactics: [],
        }}
        selectedSessionId="session-alpha"
        onSelectSession={onSelectSession}
      />
    );

    expect(screen.getByText('memory.pages.workbench.shellEmpty')).toBeInTheDocument();

    await user.click(screen.getAllByText('session-alpha')[0].closest('button') as HTMLButtonElement);
    expect(onSelectSession).toHaveBeenCalledWith('session-alpha');
  });
});
