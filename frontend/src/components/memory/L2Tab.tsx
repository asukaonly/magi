/**
 * L2Tab - L2 cognition lab and inspection workspace.
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
  L2Mention,
  L2Relation,
  L2Snapshot,
  MemoryStatistics,
  ManualL2EventPayload,
} from '@/api/modules/memory';

interface L2TabProps {
  stats: MemoryStatistics['l2'];
  relations: L2Relation[];
  assertions: L2Assertion[];
  entities: L2Entity[];
  mentions: L2Mention[];
  snapshots: L2Snapshot[];
  events: L1Event[];
  actionLoading: boolean;
  onSubmitManualEvent: (payload: ManualL2EventPayload) => Promise<void>;
  onReplayExtraction: (eventId: string) => Promise<void>;
  onRunReconcile: (entityIds: string[]) => Promise<void>;
  onRunSnapshotRefresh: (entityIds: string[]) => Promise<void>;
}

const defaultManualState: ManualL2EventPayload = {
  text: '',
  user_id: 'u1',
  session_id: 'l2-lab',
  source: 'l2_lab',
  entity_focus_hint: '',
};

export const L2Tab: React.FC<L2TabProps> = ({
  stats,
  relations,
  assertions,
  entities,
  mentions,
  snapshots,
  events,
  actionLoading,
  onSubmitManualEvent,
  onReplayExtraction,
  onRunReconcile,
  onRunSnapshotRefresh,
}) => {
  const { t } = useTranslation('app');
  const [manualEvent, setManualEvent] = useState<ManualL2EventPayload>(defaultManualState);
  const [selectedEntityId, setSelectedEntityId] = useState('');
  const [selectedEventId, setSelectedEventId] = useState('');

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

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <MetricCard label={t('memory.l2.relationCount')} value={stats.relation_count} />
        <MetricCard label={t('memory.l2.assertionCount')} value={stats.assertion_count} />
        <MetricCard label={t('memory.l2.lab.entityCount')} value={entities.length} />
        <MetricCard label={t('memory.l2.lab.snapshotCount')} value={snapshots.length} />
      </div>

      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseZap className="h-5 w-5" />
            {t('memory.l2.lab.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[1.4fr_0.9fr]">
            <div className="space-y-3">
              <label className="text-sm font-medium">{t('memory.l2.lab.manualEventLabel')}</label>
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
            </div>

            <div className="space-y-4 rounded-xl border bg-muted/20 p-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">{t('memory.l2.lab.eventReplayLabel')}</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
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
                  className="w-full"
                  onClick={() => onReplayExtraction(selectedEventId)}
                  disabled={actionLoading || !selectedEventId}
                >
                  <RefreshCcw className="mr-2 h-4 w-4" />
                  {t('memory.l2.lab.replayExtraction')}
                </Button>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">{t('memory.l2.lab.entityActionLabel')}</label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
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
                    onClick={() => onRunReconcile(selectedEntityId ? [selectedEntityId] : [])}
                    disabled={actionLoading || !selectedEntityId}
                  >
                    <GitMerge className="mr-2 h-4 w-4" />
                    {t('memory.l2.lab.runReconcile')}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => onRunSnapshotRefresh(selectedEntityId ? [selectedEntityId] : [])}
                    disabled={actionLoading || !selectedEntityId}
                  >
                    <Orbit className="mr-2 h-4 w-4" />
                    {t('memory.l2.lab.refreshSnapshot')}
                  </Button>
                </div>
                {selectedEntity ? (
                  <div className="rounded-lg border bg-background p-3 text-sm text-muted-foreground">
                    <div className="font-medium text-foreground">{selectedEntity.canonical_name}</div>
                    <div>{selectedEntity.entity_id}</div>
                    <div>
                      {selectedEntity.aliases.length > 0
                        ? selectedEntity.aliases.join(', ')
                        : t('memory.l2.lab.noAliases')}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-3">
        <InfoCard
          icon={<Network className="h-5 w-5" />}
          title={t('memory.l2.relations')}
          emptyText={t('memory.l2.noRelations')}
        >
          {relations.slice(0, 50).map((relation) => (
            <div key={relation.triple_id} className="rounded-lg border p-3 text-sm">
              <div className="font-medium">{relation.subject_id}</div>
              <div className="mt-1 text-muted-foreground">
                {relation.predicate} → {relation.object_id}
              </div>
              <Badge variant="secondary" className="mt-2">
                {(relation.confidence * 100).toFixed(0)}%
              </Badge>
            </div>
          ))}
        </InfoCard>

        <InfoCard
          icon={<Brain className="h-5 w-5" />}
          title={t('memory.l2.assertions')}
          emptyText={t('memory.l2.noAssertions')}
        >
          {assertions.slice(0, 50).map((assertion) => (
            <div key={assertion.assertion_id} className="rounded-lg border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{assertion.entity_id}</span>
                <Badge variant="outline">{assertion.validation_state}</Badge>
              </div>
              <div className="mt-2 text-muted-foreground">
                {assertion.trait_name}: {assertion.trait_value}
              </div>
            </div>
          ))}
        </InfoCard>

        <InfoCard
          icon={<Orbit className="h-5 w-5" />}
          title={t('memory.l2.lab.snapshots')}
          emptyText={t('memory.l2.lab.noSnapshots')}
        >
          {snapshots.slice(0, 50).map((snapshot) => (
            <div key={snapshot.snapshot_id} className="rounded-lg border p-3 text-sm">
              <div className="font-medium">{snapshot.entity_id}</div>
              <div className="mt-2 text-muted-foreground">
                {Object.keys(snapshot.core_traits || {}).length > 0
                  ? JSON.stringify(snapshot.core_traits)
                  : t('memory.l2.lab.noCoreTraits')}
              </div>
            </div>
          ))}
        </InfoCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <InfoCard
          icon={<GitMerge className="h-5 w-5" />}
          title={t('memory.l2.lab.entities')}
          emptyText={t('memory.l2.lab.noEntities')}
        >
          {entities.slice(0, 50).map((entity) => (
            <div key={entity.entity_id} className="rounded-lg border p-3 text-sm">
              <div className="font-medium">{entity.canonical_name}</div>
              <div className="text-muted-foreground">{entity.entity_id}</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {entity.aliases.length > 0 ? (
                  entity.aliases.map((alias) => (
                    <Badge key={`${entity.entity_id}-${alias}`} variant="secondary">
                      {alias}
                    </Badge>
                  ))
                ) : (
                  <span className="text-muted-foreground">{t('memory.l2.lab.noAliases')}</span>
                )}
              </div>
            </div>
          ))}
        </InfoCard>

        <InfoCard
          icon={<RefreshCcw className="h-5 w-5" />}
          title={t('memory.l2.lab.mentions')}
          emptyText={t('memory.l2.lab.noMentions')}
        >
          {mentions.slice(0, 50).map((mention) => (
            <div key={mention.mention_id} className="rounded-lg border p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{mention.mention_text}</span>
                {mention.resolved_entity_id ? (
                  <Badge variant="secondary">{mention.resolved_entity_id}</Badge>
                ) : (
                  <Badge variant="outline">{t('memory.l2.lab.unresolved')}</Badge>
                )}
              </div>
              <div className="mt-2 text-muted-foreground">{mention.evidence_text || '-'}</div>
            </div>
          ))}
        </InfoCard>
      </div>
    </div>
  );
};

const MetricCard: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <Card>
    <CardContent className="pt-4">
      <div className="text-2xl font-bold">{value}</div>
      <div className="text-sm text-muted-foreground">{label}</div>
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="py-8 text-center text-muted-foreground">{emptyText}</div>
        ) : (
          <div className="space-y-2">{items}</div>
        )}
      </CardContent>
    </Card>
  );
};

export default L2Tab;
