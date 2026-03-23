/**
 * L4Tab - L4 Procedural Memory tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Zap } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L4Skill, MemoryStatistics } from '@/api/modules/memory';

interface L4TabProps {
  stats: MemoryStatistics['l4'];
  skills: L4Skill[];
}

export const L4Tab: React.FC<L4TabProps> = ({ stats, skills }) => {
  const { t } = useTranslation('app');

  const highSuccessCount = skills.filter((s) => s.success_rate > 0.8).length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.skill_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.skillCount')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold text-[hsl(var(--memory-accent))]">
              {stats.open_circuit_breakers}
            </div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.openBreakers')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold text-[hsl(var(--trace-status-completed-fg))]">{highSuccessCount}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l4.highSuccess')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Zap className="h-5 w-5" />
            {t('memory.l4.skills')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {skills.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l4.noSkills')}
            </div>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {skills.map((skill) => (
                <div key={skill.skill_id} className="p-3 border rounded-lg">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{skill.skill_name}</span>
                      <Badge variant="outline">{skill.skill_category}</Badge>
                    </div>
                    <Badge
                      variant={skill.circuit_breaker_state === 'closed' ? 'default' : 'destructive'}
                    >
                      {skill.circuit_breaker_state}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <span>Success: {(skill.success_rate * 100).toFixed(1)}%</span>
                    <span>Attempts: {skill.total_attempts}</span>
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

export default L4Tab;
