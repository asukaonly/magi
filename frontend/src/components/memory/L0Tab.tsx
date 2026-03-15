/**
 * L0Tab - L0 Working Memory tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Target, Database } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L0Session, L0Workbench, MemoryStatistics } from '@/api/modules/memory';

interface L0TabProps {
  stats: MemoryStatistics['l0'];
  sessions: L0Session[];
  workbench: L0Workbench | null;
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string | null) => void;
}

export const L0Tab: React.FC<L0TabProps> = ({
  stats,
  sessions,
  workbench,
  selectedSessionId,
  onSelectSession,
}) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.active_sessions}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.activeSessions')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.total_goals}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalGoals')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.total_entities}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalEntities')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.total_tactics}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l0.totalTactics')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            {t('memory.l0.sessions')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l0.noSessions')}
            </div>
          ) : (
            <div className="space-y-2">
              {sessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`p-3 border rounded-lg cursor-pointer hover:bg-accent ${
                    selectedSessionId === session.session_id ? 'bg-accent' : ''
                  }`}
                  onClick={() => onSelectSession(session.session_id)}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm">{session.session_id.slice(0, 8)}</span>
                    <Badge variant={session.status === 'active' ? 'default' : 'secondary'}>
                      {session.status}
                    </Badge>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Goals: {session.goal_count} | Entities: {session.entity_count} | Tactics: {session.tactic_count}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {workbench && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Database className="h-5 w-5" />
              {t('memory.l0.workbench')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.goalStack')}</h4>
                {workbench.goal_stack?.length > 0 ? (
                  <div className="space-y-1">
                    {workbench.goal_stack.map((goal: Record<string, unknown>, i: number) => (
                      <div key={i} className="p-2 bg-muted rounded text-sm">
                        {String(goal.description || goal.goal_id || 'Goal')}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noGoals')}</div>
                )}
              </div>
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.activeEntities')}</h4>
                {Object.keys(workbench.active_entities || {}).length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(workbench.active_entities).map(([id, entity]: [string, unknown]) => (
                      <Badge key={id} variant="outline">
                        {String((entity as Record<string, unknown>)?.name || id)}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noEntities')}</div>
                )}
              </div>
              <div>
                <h4 className="font-medium mb-2">{t('memory.l0.tactics')}</h4>
                {Object.keys(workbench.temporary_tactics || {}).length > 0 ? (
                  <div className="space-y-1">
                    {Object.entries(workbench.temporary_tactics).map(([id, tactic]: [string, unknown]) => (
                      <div key={id} className="p-2 bg-muted rounded text-sm">
                        {String((tactic as Record<string, unknown>)?.name || id)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">{t('memory.l0.noTactics')}</div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default L0Tab;
