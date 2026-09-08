import type { ComponentProps } from 'react';
import type { L2Assertion } from '@/api/modules/memory';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';

import { L2Tab } from '@/components/memory/L2Tab';
import { MemoryKnowledgePage } from '@/pages/memory-pages/MemoryKnowledgePage';
import { useMemory } from '@/hooks/useMemory';

const TEST_TRANSLATIONS: Record<string, string> = {
  'memory.pages.knowledge.entityTypes.user': '用户',
  'memory.facts.unavailable': '完整事实暂不可用',
  'memory.facts.unknownTrait': '事实判断',
  'memory.governance.assertions.unknownEntity': '未知对象',
  'memory.governance.statuses.needsReview': '待确认',
  'memory.governance.statuses.active': '有效',
  'memory.governance.statuses.stable': '稳定',
  'memory.sources.user_authored': '你写下的内容',
  'memory.provenance.direct_report': '你明确说过的',
};

const interpolate = (template: string, options?: Record<string, unknown>) => template.replace(
  /\{\{\s*(\w+)\s*\}\}/g,
  (_match, key: string) => String(options?.[key] ?? '')
);

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => (
      TEST_TRANSLATIONS[key] ? interpolate(TEST_TRANSLATIONS[key], options) : key
    ),
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
    getCorrectionContextOptions: vi.fn().mockResolvedValue({ items: [] }),
  },
}));

vi.mock('@/hooks/useMemory', () => ({
  useMemory: vi.fn(),
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
            natural_summary: 'User U1 likes jazz.',
            display_text: 'User U1 likes jazz.', display_status: 'complete',
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
    expect(screen.getAllByText('User U1 likes jazz.').length).toBeGreaterThan(0);
    expect(screen.queryByText('memory.pages.knowledge.sections.recentKnowledge')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.pages.knowledge.metrics.knowledgeItems')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.l2.lab.evidenceBreakdown')).not.toBeInTheDocument();
    expect(screen.queryByText('memory.l2.lab.skipReasonBreakdown')).not.toBeInTheDocument();
    expect(screen.queryByText('user_self_report')).not.toBeInTheDocument();
  });

  it('merges local user aliases into the self entity overview', () => {
    render(
      <L2Tab
        section="overview"
        stats={{
          canonical_self_id: 'user:self',
          identity_link_count: 1,
          relation_count: 0,
          assertion_count: 0,
        }}
        relations={[]}
        assertions={[]}
        identityLinks={[
          {
            namespace: 'desktop',
            runtime_user_id: 'local_user',
            memory_owner_id: 'user:self',
            link_type: 'runtime_account',
          },
        ]}
        entities={[
          {
            entity_id: 'user:self',
            canonical_name: 'You',
            entity_type: 'user',
            aliases: [],
          },
          {
            entity_id: 'person:shadow-local-user',
            canonical_name: 'local user',
            entity_type: 'user',
            aliases: [],
          },
        ]}
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

    expect(screen.getAllByText('memory.pages.knowledge.entities.self')).toHaveLength(1);
    expect(screen.queryByText('local user')).not.toBeInTheDocument();
  });

  it('renders a filtered grouped knowledge-base browser', async () => {
    const user = userEvent.setup();
    const onSubmitAssertionFeedback = vi.fn().mockResolvedValue(undefined);
    const onRequestAssertionCorrection = vi.fn();

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
            natural_summary: 'User U1 likes jazz.',
            display_text: 'User U1 likes jazz.', display_status: 'complete',
            confidence_score: 0.7,
            evidence_events: ['evt-2'],
            validation_state: 'tentative',
            volatility_index: 0.2,
            source_domain: 'chat',
            inference_depth: 'explicit',
            first_inferred_at: 1710000000,
            last_validated_at: 1710000000,
            updated_at: 1710000010,
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
        onRequestAssertionCorrection={onRequestAssertionCorrection}
      />
    );

  expect(screen.getByText('memory.pages.knowledge.sections.knowledgeDirectory')).toBeInTheDocument();
  expect(screen.getAllByText('memory.pages.knowledge.groups.all').length).toBeGreaterThan(0);
  expect(screen.getByText('memory.pages.knowledge.groups.preferences')).toBeInTheDocument();
  expect(screen.getByText('memory.pages.knowledge.sections.pendingSignals')).toBeInTheDocument();
  expect(screen.queryByText('memory.pages.knowledge.sections.relations')).not.toBeInTheDocument();
  expect(screen.getAllByText('User U1 likes jazz.')[0]).toBeInTheDocument();
    expect(screen.queryByText('User U1 profile was updated.')).not.toBeInTheDocument();

  await user.click(screen.getByText('memory.pages.knowledge.groups.preferences'));
  expect(screen.getAllByText('User U1 likes jazz.')[0]).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'memory.l2.confirmAssertion' }));

    expect(onSubmitAssertionFeedback).toHaveBeenCalledWith('assert-1', 'confirmed');

    await user.click(screen.getByRole('button', { name: 'memory.l2.rejectAssertion' }));
    expect(onRequestAssertionCorrection).toHaveBeenCalledWith(
      expect.objectContaining({ assertionId: 'assert-1', correctionValue: 'jazz', expectedUpdatedAt: 1710000010 }),
      'remove'
    );

    await user.click(screen.getByRole('button', { name: 'memory.l2.correctAssertion' }));
    expect(onRequestAssertionCorrection).toHaveBeenLastCalledWith(
      expect.objectContaining({ assertionId: 'assert-1', correctionValue: 'jazz', expectedUpdatedAt: 1710000010 }),
      'replace'
    );
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();

    await user.click(screen.getAllByText('User U1 likes jazz.')[0]);
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
            display_text: '完整事实暂不可用', display_status: 'unavailable',
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
        onRequestAssertionCorrection={vi.fn()}
      />
    );

    expect(screen.getByText('memory.pages.knowledge.sections.knowledgeDirectory')).toBeInTheDocument();
    expect(screen.getAllByText('完整事实暂不可用')[0]).toBeInTheDocument();
    expect(screen.queryByText(/genre/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'memory.l2.correctAssertion' })).toBeInTheDocument();
  });

  it('renders the host description of controlled values without changing correction payloads', async () => {
    const user = userEvent.setup();
    const onRequestAssertionCorrection = vi.fn();

    render(
      <L2Tab
        section="knowledgeBase"
        stats={{ relation_count: 0, assertion_count: 1 }}
        relations={[]}
        assertions={[
          {
            assertion_id: 'assert-mood',
            entity_id: 'user:u1',
            entity_type: 'user',
            trait_family: 'mood',
            trait_name: 'mood',
            trait_value: 'high',
            display_text: 'User U1 feels upbeat.', display_status: 'complete' as const,
            trait_value_i18n: 'controlled',
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
        onRequestAssertionCorrection={onRequestAssertionCorrection}
      />
    );

    expect(screen.getAllByText('User U1 feels upbeat.')[0]).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'memory.l2.correctAssertion' }));
    expect(onRequestAssertionCorrection).toHaveBeenCalledWith(
      expect.objectContaining({ assertionId: 'assert-mood', correctionValue: 'high' }),
      'replace'
    );
  });
});

describe('MemoryKnowledgePage correction entry', () => {
  it('keeps confirmation lightweight and sends rejection to the shared correction dialog', async () => {
    const user = userEvent.setup();
    const submitAssertionFeedback = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useMemory).mockReturnValue({
      loading: false,
      l1Events: [],
      l2Relations: [],
      l2Assertions: [{
        assertion_id: 'assert-knowledge-1',
        entity_id: 'user:self',
        entity_type: 'user',
        trait_name: 'preference.music',
        trait_value: 'jazz',
        natural_summary: 'User U1 likes jazz.',
        display_text: 'User U1 likes jazz.', display_status: 'complete',
        confidence_score: 0.7,
        evidence_events: [],
        validation_state: 'tentative',
        volatility_index: 0.2,
        source_domain: 'chat',
        inference_depth: 'explicit',
        first_inferred_at: 1710000000,
        last_validated_at: 1710000000,
        user_feedback: null,
        user_feedback_at: null,
      }],
      l2Stats: { relation_count: 0, assertion_count: 1, canonical_self_id: 'user:self' },
      identityLinks: [],
      l2Entities: [{
        entity_id: 'user:self',
        canonical_name: 'User',
        entity_type: 'user',
        aliases: [],
      }],
      l2Mentions: [],
      l2Snapshots: [],
      l2ConflictRules: [],
      l2ActionLoading: false,
      submitManualL2Event: vi.fn().mockResolvedValue(undefined),
      replayL2Extraction: vi.fn().mockResolvedValue(undefined),
      flushL2ProjectionJobs: vi.fn().mockResolvedValue(undefined),
      runL2Reconcile: vi.fn().mockResolvedValue(undefined),
      runL2SnapshotRefresh: vi.fn().mockResolvedValue(undefined),
      upsertL2GraphConflictRule: vi.fn().mockResolvedValue(undefined),
      submitAssertionFeedback,
      refresh: vi.fn().mockResolvedValue(undefined),
    } as unknown as ReturnType<typeof useMemory>);

    render(
      <MemoryRouter>
        <MemoryKnowledgePage />
      </MemoryRouter>
    );

    await user.click(screen.getByRole('tab', { name: 'memory.pages.knowledge.tabs.knowledgeBase' }));
    expect(screen.getByRole('option', { name: '用户' })).toHaveValue('user');
    expect(screen.queryByRole('option', { name: 'user' })).not.toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'memory.l2.confirmAssertion' })[0]);
    expect(submitAssertionFeedback).toHaveBeenCalledWith('assert-knowledge-1', 'confirmed');

    await user.click(screen.getAllByRole('button', { name: 'memory.l2.rejectAssertion' })[0]);
    const dialog = await screen.findByRole('dialog', { name: 'memory.correction.title' });
    expect(
      within(dialog).getByRole('button', { name: /memory\.correction\.actions\.removeAssertion/ })
    ).toHaveAttribute('aria-pressed', 'true');
    await user.click(
      within(dialog).getByRole('button', { name: /memory\.correction\.actions\.replaceAssertion/ })
    );
    expect(within(dialog).getByLabelText('memory.correction.correctValue')).toHaveValue('jazz');
    expect(submitAssertionFeedback).toHaveBeenCalledTimes(1);
  });
});


const preferenceAssertion = (overrides: Partial<L2Assertion> = {}): L2Assertion => ({
  assertion_id: 'assert-strawberry',
  entity_id: 'user:self',
  entity_name: '你',
  entity_type: 'user',
  trait_name: 'preference.affinity',
  trait_family: 'preference_profile',
  trait_value: 'like',
  target_entity_id: 'entity-strawberry',
  target_entity_name: '草莓',
  natural_summary: '用户喜欢草莓。',
  display_text: '用户喜欢草莓。', display_status: 'complete',
  confidence_score: 0.9,
  evidence_events: [],
  validation_state: 'tentative',
  status: 'tentative',
  source_domain: 'user_authored',
  inference_depth: 'explicit',
  volatility_index: 0.1,
  first_inferred_at: 1710000000,
  last_validated_at: 1710000000,
  user_feedback: null,
  user_feedback_at: null,
  ...overrides,
});

const renderFactKnowledge = (assertions: L2Assertion[], options: {
  knowledgeQuery?: string;
  section?: 'overview' | 'knowledgeBase' | 'theoryOfMind';
  onCorrect?: ComponentProps<typeof L2Tab>['onRequestAssertionCorrection'];
  snapshots?: ComponentProps<typeof L2Tab>['snapshots'];
} = {}) => render(
  <L2Tab
    section={options.section ?? 'knowledgeBase'}
    stats={{ relation_count: 0, assertion_count: assertions.length }}
    assertions={assertions}
    relations={[]}
    entities={[]}
    identityLinks={[]}
    mentions={[]}
    snapshots={options.snapshots ?? []}
    conflictRules={[]}
    events={[]}
    actionLoading={false}
    onSubmitManualEvent={vi.fn().mockResolvedValue(undefined)}
    onReplayExtraction={vi.fn().mockResolvedValue(undefined)}
    onRunReconcile={vi.fn().mockResolvedValue(undefined)}
    onRunSnapshotRefresh={vi.fn().mockResolvedValue(undefined)}
    onUpsertGraphConflictRule={vi.fn().mockResolvedValue(undefined)}
    knowledgeQuery={options.knowledgeQuery}
    onRequestAssertionCorrection={options.onCorrect}
  />
);

describe('knowledge assertion fact display', () => {
  it.each([
    ['喜欢', {}, '用户喜欢草莓。'],
    ['不喜欢', { trait_value: 'dislike', natural_summary: '用户不喜欢草莓。', display_text: '用户不喜欢草莓。' }, '用户不喜欢草莓。'],
    ['兴趣', { trait_name: 'interest.attention', trait_value: 'interested', natural_summary: '用户对摄影感兴趣。', display_text: '用户对摄影感兴趣。' }, '用户对摄影感兴趣。'],
    ['称呼', { trait_name: 'communication.address.preferred', trait_value: '小涵', natural_summary: '用户希望被称为小涵。', display_text: '用户希望被称为小涵。' }, '用户希望被称为小涵。'],
    ['近期偏好', { temporal_scope: 'recent', natural_summary: '用户最近喜欢草莓。', display_text: '用户最近喜欢草莓。' }, '用户最近喜欢草莓。'],
    ['无摘要', { natural_summary: null, display_text: '用户喜欢草莓。', display_status: 'complete' as const }, '用户喜欢草莓。'],
    ['未解析对象', { target_entity_name: null, natural_summary: null, display_text: '用户表达了喜欢，但具体对象暂不可用。', display_status: 'partial' as const }, '用户表达了喜欢，但具体对象暂不可用。'],
    ['无展示资料', { natural_summary: null, display_text: '完整事实暂不可用', display_status: 'unavailable' as const }, '完整事实暂不可用'],
  ] as const)('renders the complete %s fact without internal values', (_name, overrides, expected) => {
    renderFactKnowledge([preferenceAssertion(overrides)]);
    expect(screen.getAllByText(expected)[0]).toBeInTheDocument();
    expect(screen.queryByText('like')).not.toBeInTheDocument();
    expect(screen.queryByText('dislike')).not.toBeInTheDocument();
    expect(screen.queryByText('user authored')).not.toBeInTheDocument();
    expect(screen.queryByText('tentative')).not.toBeInTheDocument();
    expect(screen.queryByText('entity-strawberry')).not.toBeInTheDocument();
    expect(screen.getByText(/待确认/)).toBeInTheDocument();
  });

  it('retains different objects with the same internal value and searches their complete fact', () => {
    renderFactKnowledge([
      preferenceAssertion(),
      preferenceAssertion({ assertion_id: 'assert-blueberry', target_entity_id: 'entity-blueberry', target_entity_name: '蓝莓', natural_summary: '用户喜欢蓝莓。', display_text: '用户喜欢蓝莓。' }),
    ], { knowledgeQuery: '草莓' });
    expect(screen.getAllByText('用户喜欢草莓。')[0]).toBeInTheDocument();
    expect(screen.queryByText('用户喜欢蓝莓。')).not.toBeInTheDocument();
  });

  it('shows both objects and preserves semantic correction values when a fact is expanded', async () => {
    const onCorrect = vi.fn();
    renderFactKnowledge([
      preferenceAssertion({ value_options: ['like', 'dislike'] }),
      preferenceAssertion({ assertion_id: 'assert-blueberry', target_entity_id: 'entity-blueberry', target_entity_name: '蓝莓', natural_summary: '用户喜欢蓝莓。', display_text: '用户喜欢蓝莓。' }),
    ], { onCorrect });
    expect(screen.getAllByText('用户喜欢蓝莓。')[0]).toBeInTheDocument();
    const title = screen.getAllByText('用户喜欢草莓。')[0];
    await userEvent.click(title);
    const fact = title.closest('details');
    expect(fact).not.toBeNull();
    expect(within(fact!).getAllByText('用户喜欢草莓。')).toHaveLength(2);
    expect(within(fact!).queryByText('like')).not.toBeInTheDocument();
    await userEvent.click(within(fact!).getByRole('button', { name: 'memory.l2.correctAssertion' }));
    expect(onCorrect).toHaveBeenCalledWith(expect.objectContaining({
      assertionId: 'assert-strawberry',
      traitName: 'preference.affinity',
      correctionValue: 'like',
      valueOptions: ['like', 'dislike'],
      title: '用户喜欢草莓。',
    }), 'replace');
  });

  it('builds an entity summary from current facts without rendering snapshot preference enums', () => {
    renderFactKnowledge([preferenceAssertion({ status: 'active', validation_state: 'stable', user_feedback: 'confirmed' })], {
      section: 'overview',
      snapshots: [{
        snapshot_id: 'snapshot-self',
        entity_id: 'user:self',
        entity_type: 'user',
        core_traits: { 'preference.affinity': 'like' },
        preferences: { food: { value: 'like', target_entity_id: 'entity-strawberry' } },
      }],
    });
    expect(screen.getAllByText('用户喜欢草莓。').length).toBeGreaterThan(1);
    expect(screen.queryByText(/like/)).not.toBeInTheDocument();
    expect(screen.queryByText(/entity-strawberry/)).not.toBeInTheDocument();
  });

  it('uses complete facts and localized metadata in the assertion inspector', () => {
    renderFactKnowledge([preferenceAssertion()], { section: 'theoryOfMind' });
    expect(screen.getAllByText('用户喜欢草莓。')[0]).toBeInTheDocument();
    expect(screen.getByText(/待确认/)).toBeInTheDocument();
    expect(screen.queryByText('user:self')).not.toBeInTheDocument();
    expect(screen.queryByText('explicit')).not.toBeInTheDocument();
    expect(screen.queryByText('like')).not.toBeInTheDocument();
  });
});
