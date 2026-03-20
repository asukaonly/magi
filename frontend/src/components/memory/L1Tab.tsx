/**
 * L1Tab - L1 Event Memory tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L1Event, MemoryStatistics } from '@/api/modules/memory';
import { formatTimestamp } from '@/hooks/useMemory';

interface L1TabProps {
  stats: MemoryStatistics['l1'];
  events: L1Event[];
}

export const L1Tab: React.FC<L1TabProps> = ({ stats, events }) => {
  const { t } = useTranslation('app');

  const userAuthoredCount = events.filter((event) => event.author_type === 'user').length;
  const interactionCount = events.length - userAuthoredCount;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.event_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.totalEvents')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{userAuthoredCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.userAuthored')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{interactionCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l1.interaction')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            {t('memory.l1.events')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {events.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l1.noEvents')}
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {events.map((event) => (
                <div key={event.event_id} className="p-3 border rounded-lg">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="outline">{event.event_type}</Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatTimestamp(event.timestamp)}
                    </span>
                  </div>
                  <div className="text-sm truncate">{event.content}</div>
                  {event.user_id ? (
                    <div className="mt-2 font-mono text-xs text-muted-foreground">{event.user_id}</div>
                  ) : null}
                  <div className="flex gap-2 mt-2">
                    {event.source ? (
                      <Badge variant="secondary" className="text-xs">{event.source}</Badge>
                    ) : null}
                    <Badge variant="secondary" className="text-xs">{event.memory_domain}</Badge>
                    {event.author_type ? (
                      <Badge variant="secondary" className="text-xs">{event.author_type}</Badge>
                    ) : null}
                    {event.content_type ? (
                      <Badge variant="secondary" className="text-xs">{event.content_type}</Badge>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default L1Tab;
