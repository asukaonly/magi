import React, { useEffect, useMemo, useState } from 'react';
import { DatabaseZap, GitMerge, Orbit, RefreshCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { DEFAULT_USER_ID } from '@/constants';
import {
  type L1Event,
  type L2Entity,
  type ManualL2EventPayload,
} from '@/api/modules/memory';
import type { MemoryTranslateFn } from '../l2KnowledgeModel';
import { PANEL_CARD_CLASS, SOFT_PANEL_CLASS, SummaryPill } from './L2Primitives';

interface L2LabSectionProps {
  actionLoading: boolean;
  entities: L2Entity[];
  events: L1Event[];
  onSubmitManualEvent: (payload: ManualL2EventPayload) => Promise<void>;
  onReplayExtraction: (eventId: string) => Promise<void>;
  onRunReconcile: (entityIds: string[]) => Promise<void>;
  onRunSnapshotRefresh: (entityIds: string[]) => Promise<void>;
  t: MemoryTranslateFn;
}

const defaultManualState: ManualL2EventPayload = {
  text: '',
  user_id: DEFAULT_USER_ID,
  session_id: 'l2-lab',
  source: 'l2_lab',
  entity_focus_hint: '',
};

export const L2LabSection: React.FC<L2LabSectionProps> = ({
  actionLoading,
  entities,
  events,
  onSubmitManualEvent,
  onReplayExtraction,
  onRunReconcile,
  onRunSnapshotRefresh,
  t,
}) => {
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
    <div className="grid gap-4 xl:grid-cols-[1.12fr_0.88fr]">
      <Card className={`${PANEL_CARD_CLASS} border-dashed`}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
            <DatabaseZap className="h-5 w-5" />
            {t('memory.l2.lab.title')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="text-sm font-medium text-[hsl(var(--memory-title))]">{t('memory.l2.lab.manualEventLabel')}</label>
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
            <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.eventReplayLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
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
              className="w-full rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
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
            <CardTitle className="text-base text-[hsl(var(--memory-title))]">{t('memory.l2.lab.entityActionLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <select
              className="flex h-10 w-full rounded-xl border border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] px-3 py-2 text-sm text-[hsl(var(--memory-title))] outline-none focus:border-[hsl(var(--memory-accent)/0.5)] focus:ring-2 focus:ring-[hsl(var(--memory-accent-soft)/0.7)]"
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
                className="rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
                onClick={() => onRunReconcile(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <GitMerge className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.runReconcile')}
              </Button>
              <Button
                variant="outline"
                className="rounded-xl border-[hsl(var(--memory-input-border))] bg-[hsl(var(--memory-input-bg))] text-[hsl(var(--memory-title))] hover:bg-[hsl(var(--memory-panel-subtle))]"
                onClick={() => onRunSnapshotRefresh(selectedEntityId ? [selectedEntityId] : [])}
                disabled={actionLoading || !selectedEntityId}
              >
                <Orbit className="mr-2 h-4 w-4" />
                {t('memory.l2.lab.refreshSnapshot')}
              </Button>
            </div>
            {selectedEntity ? (
              <div className={SOFT_PANEL_CLASS}>
                <div className="font-medium text-[hsl(var(--memory-title))]">{selectedEntity.canonical_name}</div>
                <div className="mt-1 text-[hsl(var(--memory-body))]">{selectedEntity.entity_id}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedEntity.aliases.length > 0 ? (
                    selectedEntity.aliases.map((alias) => (
                      <SummaryPill key={`${selectedEntity.entity_id}-${alias}`}>{alias}</SummaryPill>
                    ))
                  ) : (
                    <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.l2.lab.noAliases')}</span>
                  )}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
};
