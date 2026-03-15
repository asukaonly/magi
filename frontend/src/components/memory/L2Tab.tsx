/**
 * L2Tab - L2 Cognition Graph tab component
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { Network, Brain } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { L2Relation, L2Assertion, MemoryStatistics } from '@/api/modules/memory';

interface L2TabProps {
  stats: MemoryStatistics['l2'];
  relations: L2Relation[];
  assertions: L2Assertion[];
}

export const L2Tab: React.FC<L2TabProps> = ({ stats, relations, assertions }) => {
  const { t } = useTranslation('app');

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.relation_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l2.relationCount')}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="text-2xl font-bold">{stats.assertion_count}</div>
            <div className="text-sm text-muted-foreground">{t('memory.l2.assertionCount')}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Network className="h-5 w-5" />
            {t('memory.l2.relations')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {relations.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l2.noRelations')}
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {relations.slice(0, 50).map((rel) => (
                <div key={rel.triple_id} className="p-2 border rounded text-sm">
                  <span className="font-medium">{rel.subject_id}</span>
                  <span className="text-blue-500 mx-2">→ {rel.predicate} →</span>
                  <span className="font-medium">{rel.object_id}</span>
                  <Badge variant="secondary" className="ml-2 text-xs">
                    {(rel.confidence * 100).toFixed(0)}%
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-5 w-5" />
            {t('memory.l2.assertions')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {assertions.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('memory.l2.noAssertions')}
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {assertions.slice(0, 50).map((assertion) => (
                <div key={assertion.assertion_id} className="p-2 border rounded text-sm">
                  <div className="flex items-center justify-between">
                    <span>
                      <Badge variant="outline" className="mr-2">{assertion.entity_type}</Badge>
                      {assertion.entity_id}
                    </span>
                    <Badge variant="secondary" className="text-xs">
                      {(assertion.confidence_score * 100).toFixed(0)}%
                    </Badge>
                  </div>
                  <div className="text-muted-foreground mt-1">
                    {assertion.trait_name}: {assertion.trait_value}
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

export default L2Tab;
