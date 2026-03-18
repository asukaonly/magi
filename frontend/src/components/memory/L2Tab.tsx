/**
 * L2Tab - L2 cognition workspace rendered as focused in-page sections.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { Brain, DatabaseZap, GitMerge, Network, Orbit, RefreshCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type {
  L1Event,
  L2Assertion,
  L2Entity,
  L2GraphConflictRule,
  MemoryIdentityLink,
  L2GraphConflictRulePayload,
  L2Mention,
  L2Relation,
  L2Snapshot,
  L2Statistics,
  ManualL2EventPayload,
} from '@/api/modules/memory';

export type L2KnowledgeSection =
  | 'overview'
  | 'knowledgeGraph'
  | 'theoryOfMind'
  | 'mindSnapshots'
  | 'lab'
  | 'canonicalEntities'
  | 'recentMentions'
  | 'conflictRules';

interface L2TabProps {
  section?: L2KnowledgeSection;
  stats: L2Statistics;
  relations: L2Relation[];
  assertions: L2Assertion[];
  identityLinks: MemoryIdentityLink[];
  entities: L2Entity[];
  mentions: L2Mention[];
  snapshots: L2Snapshot[];
  conflictRules: L2GraphConflictRule[];
  events: L1Event[];
  dominantPredicates?: Array<[string, number]>;
  actionLoading: boolean;
  onSubmitManualEvent: (payload: ManualL2EventPayload) => Promise<void>;
  onReplayExtraction: (eventId: string) => Promise<void>;
  onRunReconcile: (entityIds: string[]) => Promise<void>;
  onRunSnapshotRefresh: (entityIds: string[]) => Promise<void>;
  onUpsertGraphConflictRule: (payload: L2GraphConflictRulePayload) => Promise<void>;
}

const defaultManualState: ManualL2EventPayload = {
  text: '',
  user_id: 'web_user',
  session_id: 'l2-lab',
  source: 'l2_lab',
  entity_focus_hint: '',
};

const defaultRuleState: L2GraphConflictRulePayload = {
  predicate: '',
  opposite_predicates: [],
  opposite_resolution: 'mark_deprecated',
  exclusive_group: '',
  exclusive_scope: 'same_subject',
  exclusive_resolution: 'mark_deprecated',
};

const PANEL_CARD_CLASS =
  'rounded-[1.35rem] border-[#e8ddd4] bg-[rgba(255,253,250,0.95)] shadow-[0_12px_24px_-24px_rgba(99,71,48,0.28)]';

const SOFT_PANEL_CLASS =
  'rounded-[1.15rem] border border-[#eadfd5] bg-[#fffdfa] px-4 py-3 text-sm text-[#6c594b]';

export const L2Tab: React.FC<L2TabProps> = ({
  section = 'lab',
  stats,
  relations,
  assertions,
  identityLinks,
  entities,
  mentions,
  snapshots,
  conflictRules,
  events,
  dominantPredicates = [],
  actionLoading,
  onSubmitManualEvent,
  onReplayExtraction,
  onRunReconcile,
  onRunSnapshotRefresh,
  onUpsertGraphConflictRule,
}) => {
  const { t } = useTranslation('app');
  const [manualEvent, setManualEvent] = useState<ManualL2EventPayload>(defaultManualState);
  const [selectedEntityId, setSelectedEntityId] = useState('');
  const [selectedEventId, setSelectedEventId] = useState('');
  const [relationStatusFilter, setRelationStatusFilter] = useState('all');
  const [ruleForm, setRuleForm] = useState<L2GraphConflictRulePayload>(defaultRuleState);
  const [ruleOppositesText, setRuleOppositesText] = useState('');

  useEffect(() => {
    if (!selectedEntityId && entities.length > 0) {
      setSelectedEntityId(entities[0].entity_id);
    }
  }, [entities, selectedEntityId]);

  useEffect(() => {
    if (!selectedEventId && events.length > 0) {
      setSelectedEventId(events[0].event_id);
    }
  }, [events, selectedEventId]);

  const selectedEntity = useMemo(
    () => entities.find((entity) => entity.entity_id === selectedEntityId) ?? null,
    [entities, selectedEntityId]
  );

  const filteredRelations = useMemo(() => {
    if (relationStatusFilter === 'all') {
      return relations;
    }
    return relations.filter((relation) => relation.status === relationStatusFilter);
  }, [relationStatusFilter, relations]);

  const evidenceBreakdownEntries = useMemo(
    () => Object.entries(stats.extract_by_evidence_class || {}).sort((left, right) => right[1] - left[1]),
    [stats.extract_by_evidence_class]
  );

  const skipReasonEntries = useMemo(
    () => Object.entries(stats.skip_by_reason || {}).sort((left, right) => right[1] - left[1]),
    [stats.skip_by_reason]
  );

  const entityTypeBreakdown = useMemo(
    () =>
      Array.from(
        entities.reduce((map, entity) => {
          map.set(entity.entity_type, (map.get(entity.entity_type) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [entities]
  );

  const dominantTraits = useMemo(
    () =>
      Array.from(
        assertions.reduce((map, assertion) => {
          map.set(assertion.trait_name, (map.get(assertion.trait_name) ?? 0) + 1);
          return map;
        }, new Map<string, number>())
      ).sort((left, right) => right[1] - left[1]),
    [assertions]
  );

  const handleManualSubmit = async () => {
    if (!manualEvent.text.trim() || !manualEvent.user_id.trim()) {
      return;
    }
    await onSubmitManualEvent({
      ...manualEvent,
      text: manualEvent.text.trim(),
      user_id: manualEvent.user_id.trim(),
      session_id: manualEvent.session_id?.trim() || undefined,
      entity_focus_hint: manualEvent.entity_focus_hint?.trim() || undefined,
    });
    setManualEvent((current) => ({ ...current, text: '' }));
  };

  const handleRuleSave = async () => {
    if (!ruleForm.predicate.trim()) {
      return;
    }
    await onUpsertGraphConflictRule({
      predicate: ruleForm.predicate.trim(),
      opposite_predicates: ruleOppositesText
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      opposite_resolution: ruleForm.opposite_resolution,
      exclusive_group: ruleForm.exclusive_group?.trim() || null,
      exclusive_scope: ruleForm.exclusive_scope ?? 'same_subject',
      exclusive_resolution: ruleForm.exclusive_resolution,
    });
    setRuleForm(defaultRuleState);
    setRuleOppositesText('');
  };

  const renderOverview = () => (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-4">
        <MetricCard label={t('memory.l2.relationCount')} value={stats.relation_count} />
        <MetricCard label={t('memory.l2.assertionCount')} value={stats.assertion_count} />
        <MetricCard label={t('memory.l2.lab.entityCount')} value={entities.length} />
        <MetricCard label={t('memory.l2.lab.snapshotCount')} value={snapshots.length} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#443227]">
              {t('memory.pages.knowledge.sections.structureOverview')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {dominantPredicates.slice(0, 6).map(([predicate, count]) => (
                <SummaryPill key={predicate}>
                  {predicate} · {count}
                </SummaryPill>
              ))}
              {dominantPredicates.length === 0 ? (
                <SummaryPill>{t('memory.l2.noRelations')}</SummaryPill>
              ) : null}
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <StatLine
                label={t('memory.pages.knowledge.sections.identitySummary')}
                value={String(identityLinks.length)}
              />
              <StatLine
                label={t('memory.pages.knowledge.sections.evidenceClasses')}
                value={String(evidenceBreakdownEntries.length)}
              />
            </div>
          </CardContent>
        </Card>

        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#443227]">
              {t('memory.pages.knowledge.sections.entityTypes')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {entityTypeBreakdown.length === 0 ? (
              <EmptyState copy={t('memory.pages.knowledge.focusAll')} />
            ) : (
              entityTypeBreakdown.map(([entityType, count]) => (
                <div key={entityType} className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
                  <span>{entityType}</span>
                  <span className="font-medium text-[#34271f]">{count}</span>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.identity.runtimeLinks')}
          emptyText={t('memory.identity.noLinks')}
        >
          {identityLinks.map((link) => (
            <div key={`${link.namespace}:${link.runtime_user_id}`} className={SOFT_PANEL_CLASS}>
              <div className="font-medium text-[#2f231b]">{link.namespace}</div>
              <div className="mt-1 text-[#725c4b]">{link.runtime_user_id}</div>
              <div className="mt-1 font-mono text-xs text-[#8a7260]">{link.memory_owner_id}</div>
            </div>
          ))}
        </InfoCard>
        <BreakdownCard
          title={t('memory.l2.lab.evidenceBreakdown')}
          emptyText={t('memory.l2.lab.noEvidenceBreakdown')}
          entries={evidenceBreakdownEntries}
        />
        <BreakdownCard
          title={t('memory.l2.lab.skipReasonBreakdown')}
          emptyText={t('memory.l2.lab.noSkipReasons')}
          entries={skipReasonEntries}
        />
      </div>
    </div>
  );

  const renderKnowledgeGraph = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[0.92fr_1.08fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base text-[#443227]">
              <Network className="h-5 w-5" />
              {t('memory.pages.knowledge.sections.graphFocus')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className={SOFT_PANEL_CLASS}>
              <div className="text-xs text-[#8a7260]">{t('memory.l2.relationCount')}</div>
              <div className="mt-1 text-2xl font-semibold text-[#32261e]">{relations.length}</div>
            </div>
            <div className="space-y-2">
              <label htmlFor="l2-relation-status-filter" className="text-sm font-medium text-[#4d392c]">
                {t('memory.l2.lab.relationStatusFilter')}
              </label>
              <select
                id="l2-relation-status-filter"
                className="flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]"
                value={relationStatusFilter}
                onChange={(event) => setRelationStatusFilter(event.target.value)}
              >
                <option value="all">{t('memory.l2.lab.relationStatusOptions.all')}</option>
                <option value="active">{t('memory.l2.lab.relationStatusOptions.active')}</option>
                <option value="conflicted">{t('memory.l2.lab.relationStatusOptions.conflicted')}</option>
                <option value="deprecated">{t('memory.l2.lab.relationStatusOptions.deprecated')}</option>
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              {dominantPredicates.slice(0, 8).map(([predicate, count]) => (
                <SummaryPill key={predicate}>
                  {predicate} · {count}
                </SummaryPill>
              ))}
            </div>
          </CardContent>
        </Card>

        <InfoCard
          icon={<Network className="h-5 w-5" />}
          title={t('memory.l2.relations')}
          emptyText={t('memory.l2.noRelations')}
        >
          {filteredRelations.slice(0, 60).map((relation) => (
            <div key={relation.triple_id} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium text-[#2f231b]">{relation.subject_id}</div>
                <Badge variant={relation.status === 'active' ? 'secondary' : 'outline'}>{relation.status}</Badge>
              </div>
              <div className="mt-2 text-[#6e5a4a]">
                {relation.predicate} → {relation.object_id}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="secondary">{`${(relation.confidence * 100).toFixed(0)}%`}</Badge>
                <Badge variant="outline">{`${relation.observation_count} obs`}</Badge>
              </div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderTheoryOfMind = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base text-[#443227]">
              <Brain className="h-5 w-5" />
              {t('memory.pages.knowledge.sections.traitFocus')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatLine label={t('memory.l2.assertionCount')} value={String(assertions.length)} />
            <div className="flex flex-wrap gap-2">
              {dominantTraits.slice(0, 8).map(([trait, count]) => (
                <SummaryPill key={trait}>
                  {trait} · {count}
                </SummaryPill>
              ))}
              {dominantTraits.length === 0 ? (
                <SummaryPill>{t('memory.l2.noAssertions')}</SummaryPill>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <InfoCard
          icon={<Brain className="h-5 w-5" />}
          title={t('memory.l2.assertions')}
          emptyText={t('memory.l2.noAssertions')}
        >
          {assertions.slice(0, 60).map((assertion) => (
            <div key={assertion.assertion_id} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[#2f231b]">{assertion.entity_id}</span>
                <Badge variant="outline">{assertion.validation_state}</Badge>
              </div>
              <div className="mt-2 text-[#6e5a4a]">
                {assertion.trait_name}: {assertion.trait_value}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge variant="secondary">{`${(assertion.confidence_score * 100).toFixed(0)}%`}</Badge>
                <Badge variant="outline">{assertion.inference_depth}</Badge>
              </div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderMindSnapshots = () => (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <MetricCard label={t('memory.l2.lab.snapshotCount')} value={snapshots.length} />
        <MetricCard
          label={t('memory.pages.knowledge.sections.snapshotMood')}
          value={snapshots.filter((snapshot) => snapshot.current_mood).length}
        />
        <MetricCard
          label={t('memory.pages.knowledge.sections.snapshotTraits')}
          value={snapshots.reduce((count, snapshot) => count + Object.keys(snapshot.core_traits || {}).length, 0)}
        />
      </div>

      <InfoCard
        icon={<Orbit className="h-5 w-5" />}
        title={t('memory.l2.lab.snapshots')}
        emptyText={t('memory.l2.lab.noSnapshots')}
      >
        {snapshots.slice(0, 60).map((snapshot) => (
          <div key={snapshot.snapshot_id} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-[#2f231b]">{snapshot.entity_id}</span>
              {snapshot.current_mood ? <Badge variant="secondary">{snapshot.current_mood}</Badge> : null}
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {Object.entries(snapshot.core_traits || {}).slice(0, 6).map(([trait, value]) => (
                <SummaryPill key={`${snapshot.snapshot_id}-${trait}`}>
                  {trait}: {String(value)}
                </SummaryPill>
              ))}
              {Object.keys(snapshot.core_traits || {}).length === 0 ? (
                <span className="text-sm text-[#8a7260]">{t('memory.l2.lab.noCoreTraits')}</span>
              ) : null}
            </div>
          </div>
        ))}
      </InfoCard>
    </div>
  );

  const renderLab = () => (
    <div className="grid gap-4 xl:grid-cols-[1.12fr_0.88fr]">
      <Card className={`${PANEL_CARD_CLASS} border-dashed`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-[#443227]">
            <DatabaseZap className="h-5 w-5" />
            {t('memory.l2.lab.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="text-sm font-medium text-[#4d392c]">{t('memory.l2.lab.manualEventLabel')}</label>
          <Textarea
            value={manualEvent.text}
            onChange={(event) => setManualEvent((current) => ({ ...current, text: event.target.value }))}
            placeholder={t('memory.l2.lab.manualEventPlaceholder')}
          />
          <div className="grid gap-3 md:grid-cols-3">
            <Input
              value={manualEvent.user_id}
              onChange={(event) => setManualEvent((current) => ({ ...current, user_id: event.target.value }))}
              placeholder={t('memory.l2.lab.userIdPlaceholder')}
            />
            <Input
              value={manualEvent.session_id || ''}
              onChange={(event) => setManualEvent((current) => ({ ...current, session_id: event.target.value }))}
              placeholder={t('memory.l2.lab.sessionIdPlaceholder')}
            />
            <Input
              value={manualEvent.entity_focus_hint || ''}
              onChange={(event) => setManualEvent((current) => ({ ...current, entity_focus_hint: event.target.value }))}
              placeholder={t('memory.l2.lab.entityFocusPlaceholder')}
            />
          </div>
          <Button onClick={handleManualSubmit} disabled={actionLoading || !manualEvent.text.trim()}>
            <DatabaseZap className="mr-2 h-4 w-4" />
            {t('memory.l2.lab.injectEvent')}
          </Button>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#443227]">{t('memory.l2.lab.eventReplayLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]"
              value={selectedEventId}
              onChange={(event) => setSelectedEventId(event.target.value)}
            >
              <option value="">{t('memory.l2.lab.selectEvent')}</option>
              {events.map((event) => (
                <option key={event.event_id} value={event.event_id}>
                  {event.event_id} · {event.event_type}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              className="w-full rounded-xl border-[#ddd2c6] bg-white hover:bg-[#f8f3ed]"
              onClick={() => onReplayExtraction(selectedEventId)}
              disabled={actionLoading || !selectedEventId}
            >
              <RefreshCcw className="mr-2 h-4 w-4" />
              {t('memory.l2.lab.replayExtraction')}
            </Button>
          </CardContent>
        </Card>

        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#443227]">{t('memory.l2.lab.entityActionLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]"
              value={selectedEntityId}
              onChange={(event) => setSelectedEntityId(event.target.value)}
            >
              <option value="">{t('memory.l2.lab.selectEntity')}</option>
              {entities.map((entity) => (
                <option key={entity.entity_id} value={entity.entity_id}>
                  {entity.entity_id} · {entity.canonical_name}
                </option>
              ))}
            </select>
            <div className="grid gap-2 md:grid-cols-2">
              <Button
                variant="outline"
                className="rounded-xl border-[#ddd2c6] bg-white hover:bg-[#f8f3ed]"
                onClick={() => onRunReconcile(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <GitMerge className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.runReconcile')}
              </Button>
              <Button
                variant="outline"
                className="rounded-xl border-[#ddd2c6] bg-white hover:bg-[#f8f3ed]"
                onClick={() => onRunSnapshotRefresh(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <Orbit className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.refreshSnapshot')}
              </Button>
            </div>
            {selectedEntity ? (
              <div className={SOFT_PANEL_CLASS}>
                <div className="font-medium text-[#2f231b]">{selectedEntity.canonical_name}</div>
                <div className="mt-1 text-[#725c4b]">{selectedEntity.entity_id}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedEntity.aliases.length > 0 ? (
                    selectedEntity.aliases.map((alias) => (
                      <SummaryPill key={`${selectedEntity.entity_id}-${alias}`}>{alias}</SummaryPill>
                    ))
                  ) : (
                    <span className="text-sm text-[#8a7260]">{t('memory.l2.lab.noAliases')}</span>
                  )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );

  const renderCanonicalEntities = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
        <Card className={PANEL_CARD_CLASS}>
          <CardHeader className="pb-3">
            <CardTitle className="text-base text-[#443227]">{t('memory.l2.lab.entities')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatLine label={t('memory.l2.lab.entityCount')} value={String(entities.length)} />
            <div className="flex flex-wrap gap-2">
              {entityTypeBreakdown.map(([entityType, count]) => (
                <SummaryPill key={entityType}>
                  {entityType} · {count}
                </SummaryPill>
              ))}
            </div>
          </CardContent>
        </Card>

        <InfoCard
          icon={<GitMerge className="h-5 w-5" />}
          title={t('memory.l2.lab.entities')}
          emptyText={t('memory.l2.lab.noEntities')}
        >
          {entities.slice(0, 60).map((entity) => (
            <div key={entity.entity_id} className={SOFT_PANEL_CLASS}>
              <div className="font-medium text-[#2f231b]">{entity.canonical_name}</div>
              <div className="mt-1 text-[#725c4b]">{entity.entity_id}</div>
              <div className="mt-3 flex flex-wrap gap-2">
                {entity.aliases.length > 0 ? (
                  entity.aliases.map((alias) => (
                    <SummaryPill key={`${entity.entity_id}-${alias}`}>{alias}</SummaryPill>
                  ))
                ) : (
                  <span className="text-sm text-[#8a7260]">{t('memory.l2.lab.noAliases')}</span>
                )}
              </div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderRecentMentions = () => (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.l2.lab.mentions')}
          emptyText={t('memory.l2.lab.noMentions')}
        >
          {mentions.slice(0, 60).map((mention) => (
            <div key={String(mention.mention_id)} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[#2f231b]">{mention.mention_text}</span>
                {mention.resolved_entity_id ? (
                  <Badge variant="secondary">{mention.resolved_entity_id}</Badge>
                ) : (
                  <Badge variant="outline">{t('memory.l2.lab.unresolved')}</Badge>
                )}
              </div>
              <div className="mt-2 text-[#6e5a4a]">{mention.evidence_text || '-'}</div>
            </div>
          ))}
        </InfoCard>

        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.pages.knowledge.sections.recentEventContext')}
          emptyText={t('memory.l1.noEvents')}
        >
          {events.slice(0, 20).map((event) => (
            <div key={event.event_id} className={SOFT_PANEL_CLASS}>
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-[#2f231b]">{event.event_type}</span>
                <Badge variant="outline">{event.source}</Badge>
              </div>
              <div className="mt-2 line-clamp-3 text-[#6e5a4a]">{event.raw_content}</div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );

  const renderConflictRules = () => (
    <div className="grid gap-4 xl:grid-cols-[0.96fr_1.04fr]">
      <InfoCard
        icon={<GitMerge className="h-5 w-5" />}
        title={t('memory.l2.lab.conflictRules')}
        emptyText={t('memory.l2.lab.noConflictRules')}
      >
        {conflictRules.map((rule) => (
          <div key={rule.predicate} className={SOFT_PANEL_CLASS}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium text-[#2f231b]">{rule.predicate}</span>
              <Badge variant="outline">{rule.exclusive_group || t('memory.l2.lab.noExclusiveGroup')}</Badge>
            </div>
            <div className="mt-2 text-[#6e5a4a]">
              {rule.opposite_predicates.length > 0
                ? rule.opposite_predicates.join(', ')
                : t('memory.l2.lab.noOpposites')}
            </div>
          </div>
        ))}
      </InfoCard>

      <Card className={PANEL_CARD_CLASS}>
        <CardHeader>
          <CardTitle className="text-base text-[#443227]">{t('memory.l2.lab.ruleEditorTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={ruleForm.predicate}
            onChange={(event) => setRuleForm((current) => ({ ...current, predicate: event.target.value }))}
            placeholder={t('memory.l2.lab.rulePredicatePlaceholder')}
          />
          <Input
            value={ruleOppositesText}
            onChange={(event) => setRuleOppositesText(event.target.value)}
            placeholder={t('memory.l2.lab.ruleOppositesPlaceholder')}
          />
          <Input
            value={ruleForm.exclusive_group || ''}
            onChange={(event) => setRuleForm((current) => ({ ...current, exclusive_group: event.target.value }))}
            placeholder={t('memory.l2.lab.ruleExclusiveGroupPlaceholder')}
          />
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <label htmlFor="l2-rule-opposite-resolution" className="text-sm font-medium text-[#4d392c]">
                {t('memory.l2.lab.ruleOppositeResolution')}
              </label>
              <select
                id="l2-rule-opposite-resolution"
                className="flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]"
                value={ruleForm.opposite_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, opposite_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
            <div className="space-y-2">
              <label htmlFor="l2-rule-exclusive-resolution" className="text-sm font-medium text-[#4d392c]">
                {t('memory.l2.lab.ruleExclusiveResolution')}
              </label>
              <select
                id="l2-rule-exclusive-resolution"
                className="flex h-10 w-full rounded-xl border border-[#e3d9cf] bg-white px-3 py-2 text-sm text-[#3d2e23] outline-none focus:border-[#d4beaa] focus:ring-2 focus:ring-[#eadccf]"
                value={ruleForm.exclusive_resolution}
                onChange={(event) =>
                  setRuleForm((current) => ({ ...current, exclusive_resolution: event.target.value }))
                }
              >
                <option value="mark_deprecated">{t('memory.l2.lab.ruleResolutionOptions.mark_deprecated')}</option>
                <option value="mark_conflicted">{t('memory.l2.lab.ruleResolutionOptions.mark_conflicted')}</option>
              </select>
            </div>
          </div>
          <Button onClick={handleRuleSave} disabled={actionLoading || !ruleForm.predicate.trim()}>
            <GitMerge className="mr-2 h-4 w-4" />
            {t('memory.l2.lab.saveRule')}
          </Button>
        </CardContent>
      </Card>
    </div>
  );

  switch (section) {
    case 'overview':
      return renderOverview();
    case 'knowledgeGraph':
      return renderKnowledgeGraph();
    case 'theoryOfMind':
      return renderTheoryOfMind();
    case 'mindSnapshots':
      return renderMindSnapshots();
    case 'lab':
      return renderLab();
    case 'canonicalEntities':
      return renderCanonicalEntities();
    case 'recentMentions':
      return renderRecentMentions();
    case 'conflictRules':
      return renderConflictRules();
    default:
      return null;
  }
};

const MetricCard: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardContent className="pt-5">
      <div className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[#32261e]">{value}</div>
      <div className="mt-1 text-sm text-[#7c6657]">{label}</div>
    </CardContent>
  </Card>
);

const InfoCard: React.FC<{
  icon: React.ReactNode;
  title: string;
  emptyText: string;
  children: React.ReactNode;
}> = ({ icon, title, emptyText, children }) => {
  const items = React.Children.toArray(children).filter(Boolean);

  return (
    <Card className={PANEL_CARD_CLASS}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-[#443227]">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyState copy={emptyText} />
        ) : (
          <div className="space-y-3">{items}</div>
        )}
      </CardContent>
    </Card>
  );
};

const BreakdownCard: React.FC<{
  title: string;
  emptyText: string;
  entries: Array<[string, number]>;
}> = ({ title, emptyText, entries }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardHeader>
      <CardTitle className="text-base text-[#443227]">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      {entries.length === 0 ? (
        <EmptyState copy={emptyText} />
      ) : (
        <div className="space-y-3">
          {entries.map(([label, value]) => (
            <div key={label} className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
              <span className="font-medium text-[#3f3024]">{label}</span>
              <Badge variant="secondary">{value}</Badge>
            </div>
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

const SummaryPill: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="inline-flex items-center rounded-full border border-[#e7dbd0] bg-white/95 px-3 py-1 text-xs text-[#6a5547]">
    {children}
  </span>
);

const StatLine: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
    <span>{label}</span>
    <span className="text-base font-semibold text-[#30241c]">{value}</span>
  </div>
);

const EmptyState: React.FC<{ copy: string }> = ({ copy }) => (
  <div className="rounded-[1.15rem] border border-dashed border-[#e6d8cc] bg-[#fcf8f3] px-4 py-6 text-sm text-[#8a7260]">
    {copy}
  </div>
);

export default L2Tab;
