import React from 'react';
import { Brain, Check, GitMerge, Network, Orbit, RefreshCcw, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  type L1Event,
  type L2Assertion,
  type L2Entity,
  type L2Mention,
  type L2Relation,
  type L2Snapshot,
} from '@/api/modules/memory';
import {
  getReadableAssertionValue,
  getReadableTraitLabel,
  type MemoryTranslateFn,
} from '../l2KnowledgeModel';
import { InfoCard, MetricCard, PANEL_CARD_CLASS, SOFT_PANEL_CLASS, StatLine, SummaryPill } from './L2Primitives';

interface L2KnowledgeGraphSectionProps {
  relations: L2Relation[];
  t: MemoryTranslateFn;
}

interface L2TheoryOfMindSectionProps {
  actionLoading: boolean;
  assertions: L2Assertion[];
  dominantTraits: Array<[string, number]>;
  onSubmitAssertionFeedback?: (assertionId: string, feedback: 'confirmed') => Promise<void>;
  onRequestAssertionCorrection?: (assertion: L2Assertion, action: 'remove') => void;
  t: MemoryTranslateFn;
}

interface L2MindSnapshotsSectionProps {
  snapshots: L2Snapshot[];
  t: MemoryTranslateFn;
}

interface L2CanonicalEntitiesSectionProps {
  entities: L2Entity[];
  entityTypeBreakdown: Array<[string, number]>;
  t: MemoryTranslateFn;
}

interface L2RecentMentionsSectionProps {
  events: L1Event[];
  mentions: L2Mention[];
  t: MemoryTranslateFn;
}

export const L2KnowledgeGraphSection: React.FC<L2KnowledgeGraphSectionProps> = ({ relations, t }) => (
  <div className="space-y-4">
    <InfoCard
      icon={<Network className="h-5 w-5" />}
      title={t('memory.l2.relations')}
      emptyText={t('memory.l2.noRelations')}
    >
      {relations.slice(0, 60).map((relation) => (
        <div key={relation.triple_id} className={SOFT_PANEL_CLASS}>
          <div className="flex items-center justify-between gap-3">
            <div className="font-medium text-[hsl(var(--memory-title))]">{relation.subject_id}</div>
            <Badge variant={relation.status === 'active' ? 'secondary' : 'outline'}>{relation.status}</Badge>
          </div>
          <div className="mt-2 text-[hsl(var(--memory-body))]">
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
);

export const L2TheoryOfMindSection: React.FC<L2TheoryOfMindSectionProps> = ({
  actionLoading,
  assertions,
  dominantTraits,
  onSubmitAssertionFeedback,
  onRequestAssertionCorrection,
  t,
}) => (
  <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[0.8fr_1.2fr]">
      <Card className={PANEL_CARD_CLASS}>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
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
              <span className="font-medium text-[hsl(var(--memory-title))]">{assertion.entity_id}</span>
              <Badge variant="outline">{assertion.validation_state}</Badge>
            </div>
            <div className="mt-2 text-[hsl(var(--memory-body))]">
              {getReadableTraitLabel(t, assertion.trait_name)}: {getReadableAssertionValue(t, assertion)}
            </div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">{`${(assertion.confidence_score * 100).toFixed(0)}%`}</Badge>
                <Badge variant="outline">{assertion.inference_depth}</Badge>
                {assertion.user_feedback && (
                  <Badge variant={assertion.user_feedback === 'confirmed' ? 'default' : 'destructive'}>
                    {assertion.user_feedback === 'confirmed' ? t('memory.l2.confirmed') : t('memory.l2.rejected')}
                  </Badge>
                )}
              </div>
              {(onSubmitAssertionFeedback || onRequestAssertionCorrection) && (
                <div className="flex shrink-0 gap-1">
                  {onSubmitAssertionFeedback ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-green-600 hover:bg-green-100 dark:hover:bg-green-900/30"
                      disabled={actionLoading || assertion.user_feedback === 'confirmed'}
                      onClick={() => onSubmitAssertionFeedback(assertion.assertion_id, 'confirmed')}
                      title={t('memory.l2.confirmAssertion')}
                    >
                      <Check className="h-4 w-4" />
                    </Button>
                  ) : null}
                  {onRequestAssertionCorrection ? (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30"
                      disabled={actionLoading}
                      onClick={() => onRequestAssertionCorrection(assertion, 'remove')}
                      title={t('memory.l2.rejectAssertion')}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        ))}
      </InfoCard>
    </div>
  </div>
);

export const L2MindSnapshotsSection: React.FC<L2MindSnapshotsSectionProps> = ({ snapshots, t }) => (
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
            <span className="font-medium text-[hsl(var(--memory-title))]">{snapshot.entity_id}</span>
            {snapshot.current_mood ? <Badge variant="secondary">{snapshot.current_mood}</Badge> : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(snapshot.core_traits || {}).slice(0, 6).map(([trait, value]) => (
              <SummaryPill key={`${snapshot.snapshot_id}-${trait}`}>
                {trait}: {String(value)}
              </SummaryPill>
            ))}
            {Object.keys(snapshot.core_traits || {}).length === 0 ? (
              <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noCoreTraits')}</span>
            ) : null}
          </div>
        </div>
      ))}
    </InfoCard>
  </div>
);

export const L2CanonicalEntitiesSection: React.FC<L2CanonicalEntitiesSectionProps> = ({
  entities,
  entityTypeBreakdown,
  t,
}) => (
  <div className="space-y-4">
    <div className="grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
      <Card className={PANEL_CARD_CLASS}>
        <CardHeader className="pb-3">
          <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entities')}</CardTitle>
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
            <div className="font-medium text-[hsl(var(--memory-title))]">{entity.canonical_name}</div>
            <div className="mt-1 text-[hsl(var(--memory-body))]">{entity.entity_id}</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {entity.aliases.length > 0 ? (
                entity.aliases.map((alias) => (
                  <SummaryPill key={`${entity.entity_id}-${alias}`}>{alias}</SummaryPill>
                ))
              ) : (
                <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noAliases')}</span>
              )}
            </div>
          </div>
        ))}
      </InfoCard>
    </div>
  </div>
);

export const L2RecentMentionsSection: React.FC<L2RecentMentionsSectionProps> = ({ events, mentions, t }) => (
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
              <span className="font-medium text-[hsl(var(--memory-title))]">{mention.mention_text}</span>
              {mention.resolved_entity_id ? (
                <Badge variant="secondary">{mention.resolved_entity_id}</Badge>
              ) : (
                <Badge variant="outline">{t('memory.l2.lab.unresolved')}</Badge>
              )}
            </div>
            <div className="mt-2 text-[hsl(var(--memory-body))]">{mention.evidence_text || '-'}</div>
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
              <span className="font-medium text-[hsl(var(--memory-title))]">{event.event_type}</span>
              <Badge variant="outline">{event.source}</Badge>
            </div>
            <div className="mt-2 line-clamp-3 text-[hsl(var(--memory-body))]">{event.content}</div>
          </div>
        ))}
      </InfoCard>
    </div>
  </div>
);
