import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { L2Tab } from '@/components/memory/L2Tab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe('L2Tab lab', () => {
  it('queues a manual event from the lab composer', async () => {
    const user = userEvent.setup();
    const onSubmitManualEvent = vi.fn().mockResolvedValue(undefined);

    render(
      <L2Tab
        stats={{ relation_count: 1, assertion_count: 2 }}
        relations={[]}
        assertions={[]}
        entities={[]}
        mentions={[]}
        snapshots={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={onSubmitManualEvent}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
      />
    );

    await user.type(
      screen.getByPlaceholderText('memory.l2.lab.manualEventPlaceholder'),
      'I like Shanghai and call it Modu.'
    );
    await user.clear(screen.getByPlaceholderText('memory.l2.lab.userIdPlaceholder'));
    await user.type(screen.getByPlaceholderText('memory.l2.lab.userIdPlaceholder'), 'u7');
    await user.type(screen.getByPlaceholderText('memory.l2.lab.entityFocusPlaceholder'), 'place:shanghai');
    await user.click(screen.getByRole('button', { name: 'memory.l2.lab.injectEvent' }));

    expect(onSubmitManualEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        text: 'I like Shanghai and call it Modu.',
        user_id: 'u7',
        entity_focus_hint: 'place:shanghai',
      })
    );
  });

  it('triggers reconcile for the selected entity', async () => {
    const user = userEvent.setup();
    const onRunReconcile = vi.fn().mockResolvedValue(undefined);

    render(
      <L2Tab
        stats={{ relation_count: 1, assertion_count: 2 }}
        relations={[]}
        assertions={[]}
        entities={[
          {
            entity_id: 'user:u1',
            canonical_name: 'User U1',
            entity_type: 'user',
            aliases: ['me'],
          },
        ]}
        mentions={[]}
        snapshots={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={onRunReconcile}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
      />
    );

    await user.click(screen.getByRole('button', { name: 'memory.l2.lab.runReconcile' }));

    expect(onRunReconcile).toHaveBeenCalledWith(['user:u1']);
  });
});
