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
        identityLinks={[]}
        entities={[]}
        mentions={[]}
        snapshots={[]}
        conflictRules={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={onSubmitManualEvent}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
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
        identityLinks={[]}
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
        conflictRules={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={onRunReconcile}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
      />
    );

    await user.click(screen.getByRole('button', { name: 'memory.l2.lab.runReconcile' }));

    expect(onRunReconcile).toHaveBeenCalledWith(['user:u1']);
  });

  it('renders the provided knowledge-graph relations', () => {
    render(
      <L2Tab
        section="knowledgeGraph"
        stats={{ relation_count: 2, assertion_count: 0 }}
        relations={[
          {
            triple_id: 'rel-active',
            subject_id: 'user:u1',
            subject_type: 'user',
            predicate: 'LIKES',
            object_id: 'food:sushi',
            object_type: 'food',
            confidence: 0.8,
            evidence_event_ids: ['evt-1'],
            observation_count: 1,
            status: 'active',
          },
          {
            triple_id: 'rel-conflicted',
            subject_id: 'user:u1',
            subject_type: 'user',
            predicate: 'ENDORSES',
            object_id: 'topic:remote-work',
            object_type: 'topic',
            confidence: 0.7,
            evidence_event_ids: ['evt-2'],
            observation_count: 1,
            status: 'conflicted',
          },
        ]}
        assertions={[]}
        identityLinks={[]}
        entities={[]}
        mentions={[]}
        snapshots={[]}
        conflictRules={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
      />
    );

    expect(screen.getByText('LIKES → food:sushi')).toBeInTheDocument();
    expect(screen.getByText('ENDORSES → topic:remote-work')).toBeInTheDocument();
  });

  it('renders rules and saves a conflict rule update', async () => {
    const user = userEvent.setup();
    const onUpsertGraphConflictRule = vi.fn().mockResolvedValue(undefined);

    render(
      <L2Tab
        section="conflictRules"
        stats={{ relation_count: 0, assertion_count: 0 }}
        relations={[]}
        assertions={[]}
        identityLinks={[]}
        entities={[]}
        mentions={[]}
        snapshots={[]}
        conflictRules={[
          {
            predicate: 'LIKES',
            opposite_predicates: ['DISLIKES'],
            opposite_resolution: 'mark_deprecated',
            exclusive_group: null,
            exclusive_scope: 'same_subject',
            exclusive_resolution: 'mark_deprecated',
          },
        ]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={onUpsertGraphConflictRule}
      />
    );

    expect(screen.getByText('LIKES')).toBeInTheDocument();
    expect(screen.getByText('DISLIKES')).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText('memory.l2.lab.rulePredicatePlaceholder'), 'ENDORSES');
    await user.type(screen.getByPlaceholderText('memory.l2.lab.ruleOppositesPlaceholder'), 'REJECTS, AVOIDS');
    await user.type(screen.getByPlaceholderText('memory.l2.lab.ruleExclusiveGroupPlaceholder'), 'stance');
    await user.selectOptions(screen.getByLabelText('memory.l2.lab.ruleOppositeResolution'), 'mark_conflicted');
    await user.selectOptions(screen.getByLabelText('memory.l2.lab.ruleExclusiveResolution'), 'mark_conflicted');
    await user.click(screen.getByRole('button', { name: 'memory.l2.lab.saveRule' }));

    expect(onUpsertGraphConflictRule).toHaveBeenCalledWith({
      predicate: 'ENDORSES',
      opposite_predicates: ['REJECTS', 'AVOIDS'],
      opposite_resolution: 'mark_conflicted',
      exclusive_group: 'stance',
      exclusive_scope: 'same_subject',
      exclusive_resolution: 'mark_conflicted',
    });
  });

  it('renders evidence class and skip reason breakdowns', () => {
    render(
      <L2Tab
        section="overview"
        stats={{
          canonical_self_id: 'user:self',
          identity_link_count: 2,
          relation_count: 0,
          assertion_count: 0,
          extract_skipped: 3,
          extract_by_evidence_class: {
            user_self_report: 4,
            assistant_freeform: 2,
          },
          skip_by_reason: {
            assistant_freeform: 2,
            assistant_tool_grounded: 1,
          },
        }}
        relations={[]}
        assertions={[]}
        identityLinks={[
          {
            namespace: 'web',
            runtime_user_id: 'local_user',
            memory_owner_id: 'user:self',
            link_type: 'runtime_account',
          },
        ]}
        entities={[]}
        mentions={[]}
        snapshots={[]}
        conflictRules={[]}
        events={[]}
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
      />
    );

    expect(screen.getByText('memory.pages.knowledge.sections.identitySummary')).toBeInTheDocument();
    expect(screen.getByText('memory.identity.runtimeLinks')).toBeInTheDocument();
    expect(screen.getAllByText('user:self').length).toBeGreaterThan(0);
    expect(screen.getByText('local_user')).toBeInTheDocument();
    expect(screen.getByText('memory.l2.lab.evidenceBreakdown')).toBeInTheDocument();
    expect(screen.getByText('memory.l2.lab.skipReasonBreakdown')).toBeInTheDocument();
    expect(screen.getByText('user_self_report')).toBeInTheDocument();
    expect(screen.getByText('assistant_tool_grounded')).toBeInTheDocument();
  });
});
