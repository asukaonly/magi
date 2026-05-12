import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { L2Tab } from '@/components/memory/L2Tab';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    getL1Events: vi.fn().mockResolvedValue({
      items: [
        {
          event_id: 'evt-2',
          timestamp: 1710000000,
          created_at: 1710000000,
          event_type: 'user_message',
          source: 'chat',
          memory_domain: 'user_authored',
          ingest_target: 'l1_only',
          cognition_eligible: true,
          tom_depth: 'topology_only',
          retention_class: 'permanent',
          content: 'I like jazz.',
          author_type: 'user',
          content_type: 'text',
          importance_score: 0.7,
        },
      ],
      total: 1,
      limit: 1,
      offset: 0,
    }),
  },
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

  it('renders a user-focused overview without diagnostics', () => {
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
        assertions={[
          {
            assertion_id: 'assert-stable-overview',
            entity_id: 'user:u1',
            entity_type: 'user',
            trait_name: 'preference.music',
            trait_value: 'jazz',
            confidence_score: 0.92,
            evidence_events: ['evt-2'],
            validation_state: 'stable',
            volatility_index: 0.1,
            source_domain: 'chat',
            inference_depth: 'explicit',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: 'confirmed',
            user_feedback_at: 1710000000,
          },
        ]}
        identityLinks={[
          {
            namespace: 'web',
            runtime_user_id: 'local_user',
            memory_owner_id: 'user:self',
            link_type: 'runtime_account',
          },
        ]}
        entities={[
          {
            entity_id: 'user:u1',
            canonical_name: 'User U1',
            entity_type: 'user',
            aliases: ['me'],
          },
        ]}
        mentions={[]}
        snapshots={[
          {
            snapshot_id: 'snapshot-overview',
            entity_id: 'user:u1',
            entity_type: 'user',
            core_traits: { 'preference.music': 'jazz' },
            preferences: {},
            relationship_topology: { outgoing_count: 0, incoming_count: 0 },
            current_context: { active_assertion_count: 1, relation_count: 0 },
            current_mood: null,
            current_stress_level: 0,
            current_engagement: 0.5,
            interaction_count: 1,
            last_interaction_at: 1710000000,
            last_updated_at: 1710000000,
          },
        ]}
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

    expect(screen.getByText('memory.pages.knowledge.overview.summary')).toBeInTheDocument();
    expect(screen.queryByText('memory.pages.knowledge.sections.reviewQueue')).not.toBeInTheDocument();
    expect(screen.getByText('memory.pages.knowledge.sections.entityOverview')).toBeInTheDocument();
    expect(screen.getAllByText('User U1').length).toBeGreaterThan(0);
    expect(screen.getByText('memory.pages.knowledge.entitySummaryFallback')).toBeInTheDocument();
    expect(screen.queryByText('memory.pages.knowledge.sections.recentKnowledge')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.knowledge.metrics.knowledgeItems')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.l2.lab.evidenceBreakdown')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.l2.lab.skipReasonBreakdown')).not.toBeInTheDocument();
    expect(screen.queryByText('user_self_report')).not.toBeInTheDocument();
  });

  it('renders a filtered grouped knowledge-base browser', async () => {
    const user = userEvent.setup();
    const onSubmitAssertionFeedback = vi.fn().mockResolvedValue(undefined);
    const onCorrectAssertion = vi.fn().mockResolvedValue(undefined);

    render(
      <L2Tab
        section="knowledgeBase"
        stats={{ relation_count: 1, assertion_count: 1 }}
        relations={[
          {
            triple_id: 'rel-1',
            subject_id: 'user:u1',
            subject_type: 'user',
            predicate: 'LIKES',
            object_id: 'music:jazz',
            object_type: 'topic',
            confidence: 0.82,
            evidence_event_ids: ['evt-1'],
            observation_count: 1,
            status: 'active',
          },
        ]}
        assertions={[
          {
            assertion_id: 'assert-1',
            entity_id: 'user:u1',
            entity_type: 'user',
            trait_name: 'preference.music',
            trait_value: 'jazz',
            confidence_score: 0.7,
            evidence_events: ['evt-2'],
            validation_state: 'tentative',
            volatility_index: 0.2,
            source_domain: 'chat',
            inference_depth: 'explicit',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: null,
            user_feedback_at: null,
          },
        ]}
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
        snapshots={[
          {
            snapshot_id: 'snapshot-1',
            entity_id: 'user:u1',
            entity_type: 'user',
            core_traits: { 'preference.music': 'jazz' },
            preferences: {},
            current_mood: 'focused',
          },
        ]}
        conflictRules={[]}
        events={[]}
        knowledgeStatusFilter="needsReview"
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
        onSubmitAssertionFeedback={onSubmitAssertionFeedback}
        onCorrectAssertion={onCorrectAssertion}
      />
    );

  expect(screen.getByText('memory.pages.knowledge.sections.knowledgeDirectory')).toBeInTheDocument();
  expect(screen.getAllByText('memory.pages.knowledge.groups.all').length).toBeGreaterThan(0);
  expect(screen.getByText('memory.pages.knowledge.groups.preferences')).toBeInTheDocument();
  expect(screen.getByText('memory.pages.knowledge.sections.pendingSignals')).toBeInTheDocument();
  expect(screen.queryByText('memory.pages.knowledge.sections.relations')).not.toBeInTheDocument();
  expect(screen.getByText('User U1\'s preference music may be "jazz".')).toBeInTheDocument();
    expect(screen.queryByText('User U1 likes jazz.')).not.toBeInTheDocument();
    expect(screen.queryByText('User U1 profile was updated.')).not.toBeInTheDocument();

  await user.click(screen.getByText('memory.pages.knowledge.groups.preferences'));
  expect(screen.getByText('User U1\'s preference music may be "jazz".')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'memory.l2.confirmAssertion' }));

    expect(onSubmitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    await user.click(screen.getByRole('button', { name: 'memory.l2.correctAssertion' }));
    const correctionInput = screen.getByLabelText('memory.l2.correctionValue');
    expect(correctionInput).toHaveValue('jazz');
    await user.clear(correctionInput);
    await user.type(correctionInput, 'blues');
    await user.click(screen.getByRole('button', { name: 'memory.l2.saveCorrection' }));

    expect(onCorrectAssertion).toHaveBeenCalledWith('assert-1', 'blues');

    expect(await screen.findByText('I like jazz.')).toBeInTheDocument();
    expect(screen.getByText('memory.pages.knowledge.sections.technicalDetails')).toBeInTheDocument();
  });

  it('renders knowledge items with nonstandard assertion values and evidence ids', () => {
    render(
      <L2Tab
        section="knowledgeBase"
        stats={{ relation_count: 0, assertion_count: 1 }}
        relations={[]}
        assertions={[
          {
            assertion_id: 'assert-malformed',
            entity_id: 'user:u1',
            entity_type: 'user',
            trait_name: 'preference.music',
            trait_value: { genre: 'jazz' } as unknown as string,
            confidence_score: 0.7,
            evidence_events: '["evt-2"]' as unknown as string[],
            validation_state: 'tentative',
            volatility_index: 0.2,
            source_domain: 'chat',
            inference_depth: 'explicit',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            user_feedback: null,
            user_feedback_at: null,
          },
        ]}
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
        knowledgeStatusFilter="needsReview"
        actionLoading={false}
        onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
        onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
        onRunReconcile={vi.fn().mockResolvedValue(undefined)}
        onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
        onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
        onSubmitAssertionFeedback={vi.fn().mockResolvedValue(undefined)}
        onCorrectAssertion={vi.fn().mockResolvedValue(undefined)}
      />
    );

    expect(screen.getByText('memory.pages.knowledge.sections.knowledgeDirectory')).toBeInTheDocument();
    expect(screen.getByText('User U1\'s preference music may be "{"genre":"jazz"}".')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.l2.correctAssertion' })).toBeInTheDocument();
  });
});
